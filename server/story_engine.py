"""Plotline — profile a tabular CSV and emit a story plan.

The engine computes every number. The LLM (later) only writes prose around
stat IDs the engine hands it. Any claim that references a stat the engine
did not compute is rejected before it reaches the UI.

Zero heavy dependencies on purpose: stdlib csv + hand-rolled stats, so this
runs anywhere Python runs. The server layer (FastAPI) is optional glue.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

MAX_ROWS = 100_000
MAX_COLS = 60
MAX_CELLS = 2_000_000
MIN_ROWS_FOR_STORY = 20
IDENTIFIER_SAMPLE = 40  # rows sampled to sniff identifier-ish columns


# --------------------------------------------------------------------------
# tiny stats library (no numpy/pandas needed for this step)
# --------------------------------------------------------------------------

def mean(xs):
    return sum(xs) / len(xs)


def pct(xs, p):
    """Linear-interpolated percentile (same result as numpy's default)."""
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return s[int(k)]
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def median(xs):
    return pct(xs, 50)


def stdev(xs):
    if len(xs) < 2:
        return None
    m = mean(xs)
    ss = sum((x - m) ** 2 for x in xs)
    return math.sqrt(ss / (len(xs) - 1))


def is_numeric_string(v: str) -> bool:
    if v is None:
        return False
    v = v.strip()
    if not v:
        return False
    m = re.fullmatch(
        r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?",
        v,
    )
    return m is not None


def is_date_string(v: str) -> bool:
    if not v:
        return False
    v = v.strip()
    for fmt in (
        "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d",
        "%m/%d/%Y", "%d-%m-%y", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M", "%d-%b-%Y", "%d %b %Y",
    ):
        try:
            datetime.strptime(v, fmt)
            return True
        except ValueError:
            pass
    return False


# --------------------------------------------------------------------------
# column profiling
# --------------------------------------------------------------------------

@dataclass
class Column:
    name: str
    index: int
    kind: str                      # numeric | date | categorical | identifier | text
    raw_kind: str                  # numeric | date | string
    nulls: int = 0
    distinct: int = 0
    note: str = ""
    # numeric
    minv: Optional[float] = None
    maxv: Optional[float] = None
    meanv: Optional[float] = None
    medv: Optional[float] = None
    stddev: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    # categorical
    top_values: list = field(default_factory=list)  # [(value, count, share)]
    # date
    dmin: Optional[datetime] = None
    dmax: Optional[datetime] = None
    # identifier heuristics
    distinct_ratio: float = 0.0
    drop_share: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "nulls": self.nulls,
            "drop_share": round(self.drop_share, 4),
            "note": self.note,
            "distinct": self.distinct,
            **({
                "min": self.minv, "max": self.maxv, "mean": round(self.meanv, 4),
                "median": self.medv, "std": (round(self.stddev, 4) if self.stddev is not None else None),
                "p25": self.p25, "p75": self.p75,
            } if self.kind in ("numeric",) else {}),
            **({
                "dmin": self.dmin.isoformat() if self.dmin else None,
                "dmax": self.dmax.isoformat() if self.dmax else None,
            } if self.kind == "date" else {}),
            **({"top": self.top_values[:8]} if self.kind in ("categorical",) else {}),
        }


DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d",
    "%m/%d/%Y", "%d-%m-%y", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y %H:%M", "%d-%b-%Y", "%d %b %Y",
)


def parse_date_any(v: str):
    v = (v or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    return None


def looks_like_identifier(header: str, values: list) -> bool:
    """Sniff columns that are identifiers: mostly-unique strings that look
    like ids, emails, phones, or names. Claims must never be made about them."""
    h = header.lower()
    if re.search(r"\b(id|uuid|guid|no|num|number|code)\b", h):
        return True
    sample = [v for v in values[:IDENTIFIER_SAMPLE] if v not in (None, "")]
    if not sample:
        return False
    k = len(sample)
    distinct = len(set(sample))
    pct_email_phone = 0
    for v in sample:
        if re.match(r"[^@\s]+@[^@\s]+\.\w+", v):
            pct_email_phone += 1
        elif re.fullmatch(r"(\+?\d[\d\s\-()]{7,14}\d)", v):
            pct_email_phone += 1
    if pct_email_phone / k >= 0.7 and distinct >= 0.7 * k:
        return True
    # mostly-unique proper-noun-ish strings with high cardinality
    if k >= 10 and distinct / k >= 0.9:
        words = " ".join(sample)
        caps = len(re.findall(r"\b[A-Z][a-z]+\b", words))
        if caps / max(1, len(re.findall(r"\b\w+\b", words))) >= 0.8:
            return True
    return False


# --------------------------------------------------------------------------
# loading + cleaning
# --------------------------------------------------------------------------

def sniff_dialect(raw: bytes) -> csv.Dialect:
    head = raw[:64_000].decode("utf-8", errors="replace")
    return csv.Sniffer().sniff(head, delimiters=",;\t|") or csv.excel


def read_csv_bytes(raw: bytes):
    """Return (headers, rows-as-lists). Tolerates BOM/utf-8-sig."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    dialect = sniff_dialect(raw)
    rdr = csv.reader(io.StringIO(text, newline=""), dialect)
    rows = []
    for i, row in enumerate(rdr):
        if i > MAX_ROWS + 1:
            break
        rows.append(row)
    if not rows:
        raise ValueError("Empty file: no rows found.")
    headers = [h.strip() or f"col{i}" for i, h in enumerate(rows[0])]
    body = rows[1:]
    width = len(headers)
    fixed = []
    short = 0
    for r in body:
        if not r or all((c or "").strip() == "" for c in r):
            continue
        if len(r) < width:
            r = list(r) + [""] * (width - len(r))
        elif len(r) > width:
            r = r[:width]
        if all((c or "").strip() == "" for c in r):
            continue
        fixed.append(r)
        short += 1
    return headers, fixed


def numeric_value(cell: str) -> Optional[float]:
    """Parse a number from a cell. The search fallback is deliberately
    strict: it only fires when the number covers basically the entire
    cell, so '2026-06-01' or 'Kitchen 2' never parse as numbers."""
    if cell is None:
        return None
    s = cell.strip().replace(",", "").replace("\u20b9", "").replace("₹", "").replace("INR", "").strip()
    if not s or s.lower() in ("nan", "null", "na", "n/a", "-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        pass
    # fallback: extract a number ONLY if what remains is symbols/punct
    # (currency marks, units, slashes — not other digits or letters)
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", s)
    if m:
        rest = (s[: m.start()] + s[m.end():]).strip()
        rest = rest.strip("/- ₹%kg pcs")
        if rest and re.search(r"[0-9A-Za-z]", rest):
            return None  # 'Kitchen 2', '2026-06-01', 'CUST-1001' land here
        try:
            return float(m.group().replace(",", ""))
        except ValueError:
            return None
    return None


class TooBig(Exception):
    pass


def profile_bytes(raw: bytes) -> dict:
    headers, rows = read_csv_bytes(raw)
    if len(rows) > MAX_ROWS:
        raise TooBig(f"{len(rows)} rows exceeds the {MAX_ROWS:,} row limit.")
    if len(headers) > MAX_COLS:
        raise TooBig(f"{len(headers)} columns exceeds the {MAX_COLS} column limit.")
    if len(rows) * len(headers) > MAX_CELLS:
        raise TooBig("file too large for the in-browser engine")

    columns: list[Column] = []
    ctx_mixed: list[str] = []
    for j, h in enumerate(headers):
        vals = [r[j] for r in rows]
        nonnull = [v for v in vals if v is not None and v.strip() != ""]
        nulls = len(vals) - len(nonnull)
        drop_share = nulls / max(1, len(vals))

        numeric_hits = sum(1 for v in nonnull[:200] if numeric_value(v) is not None)
        is_numeric = nonnull and numeric_hits / min(len(nonnull), 200) >= 0.95
        is_date = (not is_numeric) and nonnull and (
            sum(1 for v in nonnull[:80] if is_date_string(v)) / min(len(nonnull), 80) >= 0.85
        )

        c = Column(name=h, index=j, kind="", raw_kind="", nulls=nulls, drop_share=drop_share)
        if is_numeric:
            c.raw_kind = "numeric"
            xs = [x for x in (numeric_value(v) for v in nonnull) if x is not None]
            if xs:
                c.kind = "numeric"
                c.minv, c.maxv = min(xs), max(xs)
                c.meanv = mean(xs)
                c.medv = median(xs)
                c.stddev = stdev(xs)
                c.p25, c.p75 = pct(xs, 25), pct(xs, 75)
            else:
                c.kind = "text"
                c.raw_kind = "string"
        elif is_date:
            c.raw_kind = "date"
            ds = [parse_date_any(v) for v in nonnull]
            ds = [d for d in ds if d]
            if ds:
                c.kind = "date"
                c.dmin, c.dmax = min(ds), max(ds)
            else:
                c.kind = "text"
        else:
            c.raw_kind = "string"
            if looks_like_identifier(h, nonnull):
                c.kind = "identifier"
                c.note = "identifier-like column — excluded from narrative"
            else:
                # mixed-type sniff: if a chunk of the column parses as numeric
                # but the column isn't numeric overall, the mess is the story
                numish = sum(1 for v in nonnull[:200] if numeric_value(v) is not None)
                num_share = numish / max(1, min(len(nonnull), 200))
                if 0.1 <= num_share < 0.95:
                    c.kind = "categorical"
                    c.note = f"mixed types: {round(num_share*100)}% numeric — treated as labels, shown as a caveat"
                    ctx_mixed.append(c.name)
                elif len(set(nonnull)) <= max(50, len(nonnull) // 10) + 1:
                    c.kind = "categorical"
                    counts: dict[str, int] = {}
                    for v in nonnull:
                        counts[v] = counts.get(v, 0) + 1
                else:
                    c.kind = "text"
        columns.append(c)

    # fill top values for categoricals after kind decided
    for c in columns:
        if c.kind == "categorical":
            vals = [r[c.index] for r in rows if r[c.index]]
            counts = {}
            for v in vals:
                counts[v] = counts.get(v, 0) + 1
            total = max(1, len(vals))
            c.distinct = len(counts)
            c.top_values = [
                [v, n, round(n / total, 4)] for v, n in
                sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
            ]
        elif c.kind not in ("numeric", "date"):
            c.distinct = len(set(r[c.index] for r in rows if r[c.index]))

    n_rows = len(rows)
    mixed_cols = list(ctx_mixed)
    fully_empty_cols = [
        c.name for c in columns
        if c.nulls == n_rows and n_rows > 0
    ]
    return {
        "ok": True,
        "n_rows": n_rows,
        "n_cols": len(columns),
        "headers": headers,
        "columns": [c.to_dict() for c in columns],
        "fully_empty_cols": fully_empty_cols,
        "mixed_type_cols": mixed_cols,
        "too_small": n_rows < MIN_ROWS_FOR_STORY,
    }
