"""Narrative layer.

v1: template prose assembled from verified ledger stats. Every sentence
carries the stat_ids it depends on, and those ids are checked against the
ledger before the frame is allowed into the story. The LLM layer (Gemini)
drops into `llm_narrate()` later and goes through the exact same gate —
a claim referencing an unverified stat is rejected, regenerated, or the
template fallback is used.
"""

from __future__ import annotations

from .stats import StatsLedger, build_ledger, fmt_num, fmt_money, fmt_date
from .story_engine import Column, numeric_value, parse_date_any, mean


def _claim(lg: StatsLedger, frame: dict, sid: str, text: str, role: str = "body") -> None:
    """Attach a sentence to a frame ONLY if the stat it cites exists."""
    global _dropped_count
    v = lg.verify([sid])
    if not v["ok"]:
        _dropped_count += 1  # the number behind this sentence was never computed — drop it
        return
    frame["claims"].append({"stat": sid, "text": text, "role": role})


def build_story(headers, rows, columns, profile: dict) -> dict | None:
    """Assemble the story plan: ordered frames, each with claims bound to
    stat ids. Returns None if the data can't support a story at all."""
    lg, ctx = build_ledger(headers, rows, columns)
    S = lg.stats
    frames = []

    # ---- frame 0: the table itself (clean)
    f0 = {"id": "clean", "kind": "table", "title": "Here's your data", "claims": []}
    _claim(lg, f0, "meta_rows",
           f"After cleaning we have {S['meta_rows']['fmt']} rows by {profile['n_cols']} columns "
           f"to work with.", "lead")
    if profile.get("mixed_type_cols"):
        f0["claims"].append({
            "stat": None,
            "text": f"Some columns mix numbers with text ({', '.join(profile['mixed_type_cols'][:3])}) — "
                    "they're treated as labels, not values.",
            "role": "caveat",
        })
    frames.append(f0)

    # ---- hero frame
    hero_sid = next((s for s in S.values() if s["frame"] == "hero" and s["id"].endswith("__total")), None)
    if hero_sid:
        f1 = {"id": "hero", "kind": "hero", "title": "The one number", "claims": []}
        fmtc = fmt_money if ctx["money_like"] else fmt_num
        val = S[hero_sid["id"]]
        f1["big"] = {"stat": hero_sid["id"], "value": val["fmt"], "label": val["label"]}
        peak = S.get(hero_sid["id"].replace("__total", "__peak"))
        if peak:
            _claim(lg, f1, peak["id"],
                   f"The largest single entry was {peak['fmt']} — {peak['detail']}.", "sub")
        frames.append(f1)

    # ---- breakdown frames: one per categorical column, main numeric as the measure
    brk_stats = [s for s in S.values() if s["frame"] == "breakdown"]
    main_num = ctx["main_num"]
    if brk_stats:
        cat_names = []
        for s in brk_stats:
            cn = s["id"].split("__")[0]
            if cn not in cat_names:
                cat_names.append(cn)
        for cat_name in cat_names:
            f2 = {"id": f"breakdown_{cat_name}", "kind": "bars",
                  "title": f"Where the {main_num.name if main_num else 'value'} went, by {cat_name}", "claims": []}
            if any("mixed types" in (c.note or "") for c in columns if c.name == cat_name):
                f2["claims"].append({
                    "stat": None,
                    "text": f"'{cat_name}' mixes numbers with text, so its groups are labels — treat what follows with suspicion.",
                    "role": "caveat",
                })
            for s in brk_stats:
                if not s["id"].startswith(f"{cat_name}__"):
                    continue
                if s["id"].endswith("__top"):
                    _claim(lg, f2, s["id"], f"{s['fmt']} is the top {cat_name} by total {main_num_name(lg)}.", "lead")
                elif s["id"].endswith("__ratio"):
                    _claim(lg, f2, s["id"], f"The top group runs {s['fmt']} the smallest — a {s['label']} gap.", "sub")
                elif s["id"].endswith("__sig"):
                    solid = "probably not chance" if (s["value"] or 1) < 0.05 else "could still be chance"
                    _claim(lg, f2, s["id"], f"Statistically: {s['detail']} — so it {solid}.", "caveat")
            if cat := next((c for c in columns if c.name == cat_name), None):
                cd_ = _group_means(headers, rows, columns, cat, main_num)
                if cd_:
                    f2["chart_data"] = cd_
            frames.append(f2)

    # ---- trend frame
    trd = [s for s in S.values() if s["frame"] == "trend"]
    if trd:
        date_col = ctx["date_col"]
        main_num = ctx["main_num"]
        f3 = {"id": "trend", "kind": "line", "title": "Over time", "claims": []}
        for s in trd:
            if s["id"].endswith("__span"):
                _claim(lg, f3, s["id"], f"The data covers {s['fmt']} ({s['detail']}).", "lead")
            elif s["id"].endswith("__jump"):
                _claim(lg, f3, s["id"], f"Biggest single shift: {s['fmt']}. {s['detail']}", "sub")
            elif s["id"].endswith("__peakday"):
                _claim(lg, f3, s["id"], f"Peak: {s['detail']}", "sub")
        if date_col and main_num:
            f3["chart_data"] = _time_series(headers, rows, columns, date_col, main_num)
        frames.append(f3)

    # ---- distribution frame
    shape = next((s for s in S.values() if s["frame"] == "distribution"), None)
    if shape:
        f4 = {"id": "distribution", "kind": "histogram", "title": "The shape of it", "claims": []}
        _claim(lg, f4, shape["id"], f"Median {shape['fmt']} — half of all values sit below that.", "lead")
        if shape["detail"] and "median" in shape["detail"]:
            f4["claims"].append({"stat": shape["id"], "text": shape["detail"], "role": "sub"})
        main_num = ctx["main_num"]
        if main_num:
            f4["chart_data"] = _histogram(headers, rows, columns, main_num)
        frames.append(f4)

    # ---- honesty frame (always last, always shown)
    f5 = {"id": "limits", "kind": "caveats", "title": "What this can't tell you", "claims": []}
    for i, note in enumerate(ctx["caveats"] or ["no structural caveats found — small mercies"]):
        f5["claims"].append({"stat": None, "text": note, "role": "caveat"})
    if len(rows) < 100:
        f5["claims"].append({"stat": None, "text": "This is a small dataset. Nothing here is a market study.", "role": "caveat"})
    f5["claims"].append({"stat": None, "text": "Correlation-looking patterns are not causes. The numbers are real; the meaning is yours.", "role": "caveat"})
    frames.append(f5)

    return {
        "ok": True,
        "title": _story_title(headers, rows, columns, ctx),
        "frames": frames,
        "stats": {sid: s for sid, s in lg.stats.items()},
        "verification": {"claims_total": sum(len(f["claims"]) for f in frames),
                         "claims_with_stats": sum(1 for f in frames for c in f["claims"] if c["stat"]),
                         "unverified_dropped": _dropped_count},
    }


_dropped_count = 0


def main_num_name(lg):
    tot = next((s for s in lg.stats.values() if s["id"].endswith("__total")), None)
    if tot:
        return tot["label"].replace("Total ", "").lower()
    return "value"


def _group_means(headers, rows, columns, cat, num_col):
    if not cat or not num_col:
        return None
    cat_idx, num_idx = cat.index, num_col.index
    groups = {}
    for r in rows:
        k = (r[cat_idx] or "").strip()
        x = numeric_value(r[num_idx])
        if k and x is not None:
            groups.setdefault(k, []).append(x)
    agg = sorted(((k, mean(v), len(v)) for k, v in groups.items() if len(v) >= 2),
                key=lambda t: -t[1])[:8]
    return {"x": [a[0] for a in agg], "y": [round(a[1], 2) for a in agg], "n": [a[2] for a in agg]}


def _time_series(headers, rows, columns, date_col, num_col):
    pts = []
    for r in rows:
        d = parse_date_any(r[date_col.index])
        x = numeric_value(r[num_col.index])
        if d and x is not None:
            pts.append((d, x))
    if len(pts) < 2:
        return None
    pts.sort(key=lambda t: t[0])
    # daily aggregate if multiple values per day
    per_day = {}
    for d, x in pts:
        per_day.setdefault(d.date().isoformat(), []).append(x)
    days = sorted(per_day.keys())
    return {"x": days, "y": [round(mean(per_day[d]), 2) for d in days]}


def _histogram(headers, rows, columns, num_col, bins=24):
    xs = [x for r in rows if (x := numeric_value(r[num_col.index])) is not None]
    if len(xs) < 4:
        return None
    lo, hi = min(xs), max(xs)
    if lo == hi:
        return None
    w = (hi - lo) / bins
    counts = [0] * bins
    for x in xs:
        b = min(int((x - lo) / w), bins - 1)
        counts[b] += 1
    edges = [round(lo + w * i, 2) for i in range(bins + 1)]
    return {"counts": counts, "edges": edges, "total": len(xs)}


def _story_title(headers, rows, columns, ctx):
    n = len(rows)
    if ctx["date_col"] and ctx["numeric_cols"]:
        return f"A {n}-row table, read honestly"
    return f"A {n}-row table, read honestly"
