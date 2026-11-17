"""The stats ledger — every number the story may claim, computed here and
given a stable stat_id. The narrative layer may ONLY reference these ids.

This is the guardrail made structural: the LLM proposes sentences that
carry stat ids; anything referencing an id that isn't in this ledger is
rejected before it reaches the UI.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional

from .story_engine import Column, parse_date_any, numeric_value, median, pct, mean, stdev


Z_95 = 1.959963984540054  # two-sided 95%


def fmt_money(v: float) -> str:
    a = abs(v)
    if a >= 1e7:
        return f"₹{v/1e7:.2f} cr"
    if a >= 1e5:
        return f"₹{v/1e5:.2f} L"
    if a >= 1e3:
        return f"₹{v/1e3:.1f}k"
    return f"₹{v:.0f}"


def fmt_num(v: float) -> str:
    a = abs(v)
    if a >= 1e7:
        return f"{v/1e7:.2f} cr"
    if a >= 1e5:
        return f"{v/1e5:.2f} L"
    if a >= 1e3:
        return f"{v/1e3:.1f}k"
    if a == int(v):
        return f"{int(v)}"
    return f"{v:.2f}"


def fmt_date(d: datetime) -> str:
    return d.strftime("%d %b %Y")


def clamp01(p: float) -> float:
    return max(0.0, min(1.0, p))


class StatsLedger:
    def __init__(self):
        self.stats: dict[str, dict] = {}

    def add(self, sid: str, label: str, value, fmt: str, detail: str = "", frame: str = "") -> str:
        self.stats[sid] = {
            "id": sid,
            "label": label,
            "value": value,
            "fmt": fmt,
            "detail": detail,
            "frame": frame,
        }
        return sid

    def verify(self, claim_stat_ids: list[str]) -> dict:
        unknown = [s for s in claim_stat_ids if s not in self.stats]
        return {"ok": len(unknown) == 0, "unknown": unknown}


def ttest_welch(m1, s1, n1, m2, s2, n2):
    """Return (difference, t, approx p-value via normal approx)."""
    d = m1 - m2
    se2 = (s1 * s1 / n1) + (s2 * s2 / n2)
    if se2 <= 0 or n1 < 2 or n2 < 2:
        return d, 0.0, 0.5
    se = math.sqrt(se2)
    t = d / se
    # normal approximation of p (two-sided); good enough for a "is this
    # likely chance?" flag, and we SAY it's an approximation on screen.
    p = math.erfc(abs(t) / math.sqrt(2))
    return d, t, p


def _pick_main_numeric(numeric_cols):
    """Prefer the most money-like numeric column; fall back to the first."""
    money_names = ("amount", "amt", "total", "price", "cost", "value", "revenue", "spend", "balance", "sales")
    for c in numeric_cols:
        if any(k in c.name.lower() for k in money_names):
            return c
    return numeric_cols[0] if numeric_cols else None


def build_ledger(headers: list[str], rows: list[list[str]], columns: list[Column]) -> tuple[StatsLedger, dict]:
    """Compute the full stats ledger from cleaned rows. Returns (ledger, context)."""
    lg = StatsLedger()
    # main numeric: money-like column if present, else first numeric.
    # Everything downstream (hero, breakdown, trend) tells THIS column's story.
    all_numeric = [c for c in columns if c.kind == "numeric"]
    main_pick = _pick_main_numeric(all_numeric)
    # main numeric first: the hero loop and every downstream frame tells
    # THIS column's story; other numerics are supporting detail
    ordered_numeric = ([main_pick] + [c for c in all_numeric if c is not main_pick]) if main_pick else all_numeric
    ctx = {
        "n_rows": len(rows),
        "numeric_cols": ordered_numeric,
        "main_num": main_pick,
        "date_col": next((c for c in columns if c.kind == "date"), None),
        "cat_cols": [c for c in columns if c.kind == "categorical"],
        "money_like": False,
    }
    money_names = ("amount", "amt", "total", "price", "cost", "value", "revenue", "spend", "balance", "sales")
    if any(any(k in c.name.lower() for k in money_names) for c in ctx["numeric_cols"]):
        ctx["money_like"] = True

    lg.add(
        "meta_rows", "Rows analysed",
        len(rows), fmt_num(len(rows)), f"{len(rows)} x {len(headers)} table after cleaning",
        frame="clean",
    )

    # ---- primary numeric: total + peak/trough framing
    for c in ctx["numeric_cols"]:
        xs_all = [(i, numeric_value(r[c.index])) for i, r in enumerate(rows)]
        xs_all = [(i, x) for i, x in xs_all if x is not None]
        xs = [x for _, x in xs_all]
        if len(xs) < 3:
            continue
        sid_total = f"{c.name}__total"
        is_money = any(k in c.name.lower() for k in money_names)
        fmtc = (lambda v: fmt_money(v)) if is_money else (lambda v: fmt_num(v))
        lg.add(
            sid_total, f"Total {c.name}",
            round(sum(xs), 2),
            fmtc(sum(xs)),
            f"sum over {len(xs)} non-null values; column mean {fmtc(c.meanv)}, median {fmtc(c.medv)}",
            frame="hero",
        )
        # outlier: max vs p75 heuristic
        mx_i, mx_v = max(xs_all, key=lambda t: t[1])
        fold = (mx_v / c.meanv) if c.meanv else None
        lg.add(
            f"{c.name}__peak", f"Largest single {c.name}",
            round(mx_v, 2), fmtc(mx_v),
            f"row index {mx_i}; mean is {fmtc(c.meanv)} — this is {fold:.1f}x the mean" if fold else "",
            frame="hero",
        )
        # distribution shape
        skew_note = ""
        if c.medv and c.meanv and c.meanv != 0 and c.medv != 0:
            r = c.meanv / c.medv
            if r >= 1.4:
                skew_note = f"mean is {r:.1f}x the median — a few large values pull it up"
            elif r <= 0.7:
                skew_note = f"mean is {1/r:.1f}x below the median — a few small values pull it down"
        lg.add(
            f"{c.name}__shape", f"Shape of {c.name}",
            round(c.medv, 2), fmtc(c.medv),
            f"median {fmtc(c.medv)}, p25 {fmtc(c.p25)}, p75 {fmtc(c.p75)}; {skew_note}" if skew_note
            else f"median {fmtc(c.medv)}, p25 {fmtc(c.p25)}, p75 {fmtc(c.p75)}",
            frame="distribution",
        )
        # only continue the "main" story on one numeric: the most money-like, else first
        break

    # ---- breakdown by categorical
    main_num = ctx["main_num"]
    for cat in ctx["cat_cols"][:2]:
        if not main_num:
            break
        groups: dict[str, list[float]] = {}
        for r in rows:
            key = (r[cat.index] or "").strip()
            x = numeric_value(r[main_num.index])
            if key and x is not None:
                groups.setdefault(key, []).append(x)
        if len(groups) < 2:
            continue
        agg = sorted(
            ((k, mean(v), len(v), sum(v)) for k, v in groups.items() if len(v) >= 3),
            key=lambda t: -t[3],
        )
        if len(agg) >= 2:
            top_k, top_m, top_n, top_s = agg[0]
            low_k, low_m, low_n, low_s = agg[-1]
            ratio = (top_m / low_m) if low_m else None
            lg.add(
                f"{cat.name}__top", f"Top {cat.name}",
                top_k, str(top_k),
                f"mean {fmt_num(top_m)} across {top_n} rows; total {fmt_num(top_s)}",
                frame="breakdown",
            )
            if ratio and ratio >= 1.15:
                lg.add(
                    f"{cat.name}__ratio", f"{top_k} vs {low_k}",
                    round(ratio, 2), f"{ratio:.1f}x",
                    f"{top_k} averages {fmt_num(top_m)} vs {low_k} {fmt_num(low_m)}",
                    frame="breakdown",
                )
            # significance flag (approx)
            svc = [x for r in rows if (r[cat.index] or "").strip() == top_k
                   for x in [numeric_value(r[main_num.index])] if x is not None]
            svr = [x for r in rows if (r[cat.index] or "").strip() == low_k
                   for x in [numeric_value(r[main_num.index])] if x is not None]
            if len(svc) >= 8 and len(svr) >= 8:
                d, t, p = ttest_welch(
                    mean(svc), stdev(svc) or 0.01, len(svc),
                    mean(svr), stdev(svr) or 0.01, len(svr),
                )
                solid = p < 0.05 and min(len(svc), len(svr)) >= 15
                note = (
                    f"approx p = {p:.3f} — probably a real difference"
                    if solid
                    else f"approx p = {p:.3f} — could be chance; needs more rows"
                )
                lg.add(
                    f"{cat.name}__sig", f"Is the {cat.name} gap real?",
                    round(p, 3), f"p ≈ {p:.2f}",
                    f"Welch t-test (normal approx): {top_k} n={len(svc)}, {low_k} n={len(svr)}; "
                    + ("significant at the 5% level" if solid else "NOT significant — treat as a hint only"),
                    frame="breakdown",
                )

    # ---- time trend when a date column exists
    dc = ctx["date_col"]
    if dc and main_num:
        pts = []
        for r in rows:
            d = parse_date_any(r[dc.index])
            x = numeric_value(r[main_num.index])
            if d and x is not None:
                pts.append((d, x))
        if len(pts) >= 8:
            pts.sort(key=lambda t: t[0])
            days = (pts[-1][0] - pts[0][0]).days
            # monthly buckets
            buckets: dict[str, list[float]] = {}
            for d, x in pts:
                key = d.strftime("%Y-%m")
                buckets.setdefault(key, []).append(x)
            keys = sorted(buckets.keys())
            if len(keys) >= 3:
                first_m = mean(buckets[keys[0]]) if len(buckets[keys[0]]) > 1 else buckets[keys[0]][0]
                last_m = mean(buckets[keys[-1]]) if len(buckets[keys[-1]]) > 1 else buckets[keys[-1]][0]
                lg.add(
                    f"{dc.name}__span", f"Time span",
                    days, f"{days} days",
                    f"{fmt_date(pts[0][0])} → {fmt_date(pts[-1][0])}",
                    frame="trend",
                )
                # biggest month-over-month jump
                bmean = {k: mean(v) for k, v in buckets.items()}
                jumps = [(keys[i + 1], (bmean[keys[i + 1]] - bmean[keys[i]]) / abs(bmean[keys[i]]))
                         for i in range(len(keys) - 1) if bmean[keys[i]] != 0]
                if jumps:
                    jk, jr = max(jumps, key=lambda t: abs(t[1]))
                    if abs(jr) >= 0.15:
                        lg.add(
                            f"{dc.name}__jump", f"Biggest shift",
                            f"{jk}", jk,
                            f"month mean moved {jr*100:+.0f}% vs the month before — real shift or small-sample, see trend",
                            frame="trend",
                        )
                # best/worst single day
                bd, bv = max(pts, key=lambda t: t[1])
                wd, wv = min(pts, key=lambda t: t[1])
                fold = bv / c_med if (c_med := main_num.medv) else None
                lg.add(
                    f"{dc.name}__peakday", f"Peak day for {main_num.name}",
                    fmt_date(bd), fmt_date(bd),
                    f"{fmt_num(bv)} on {fmt_date(bd)}; lowest was {fmt_num(wv)} on {fmt_date(wd)}"
                    + (f" — {fold:.1f}x the median" if fold else ""),
                    frame="trend",
                )

    # ---- caveats anyone honest must state
    caveats = []
    drop_cols = [c.name for c in columns if c.drop_share >= 0.05 and c.kind != "identifier"]
    if drop_cols:
        caveats.append(f"missing values: {', '.join(drop_cols[:3])} are ≥5% blank — dropped from those claims")
    mixed = [c.name for c in columns if "mixed types" in (c.note or "")]
    if mixed:
        caveats.append(f"mixed data types: {', '.join(mixed[:3])} treated as labels, not numbers")
    id_cols = [c.name for c in columns if c.kind == "identifier"]
    if id_cols:
        caveats.append(f"identifier columns excluded from narrative: {', '.join(id_cols[:3])}")
    if len(rows) < 40:
        caveats.append(f"only {len(rows)} rows — every pattern here is a hint, not a conclusion")
    ctx["caveats"] = caveats

    return lg, ctx
