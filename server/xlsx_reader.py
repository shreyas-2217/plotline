"""Minimal .xlsx reader — stdlib only (zipfile + ElementTree).

An .xlsx is a zip of XML files: xl/worksheets/sheet1.xml holds the rows,
xl/sharedStrings.xml holds the string table. We need only those two plus
a light pass over styles to notice date-formatted numeric cells.

Supports: shared strings, inline strings, formula result strings, numbers,
date-styled serials (converted to iso dates), blank cells.
Does NOT support: formulas (values only), multiple sheets beyond the first
(v1 read is first worksheet), charts, macros.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EXCEL_EPOCH = datetime(1899, 12, 30)  # Excel day 0 (Windows serials)

DATE_FORMAT_CODES = ("yy", "mm", "dd")  # style id is a date if its numFmt has these


def is_xlsx(raw: bytes) -> bool:
    return len(raw) > 4 and raw[:2] == b"PK" and raw[2:4] == b"\x03\x04"


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        data = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    out = []
    root = ET.fromstring(data)
    for si in root.findall(f"{NS}si"):
        parts = [t.text or "" for t in si.iter(f"{NS}t")]
        out.append("".join(parts))
    return out


def _date_style_ids(z: zipfile.ZipFile) -> set[int]:
    """Style indices (xfId) whose number format looks like a date."""
    try:
        styles = ET.fromstring(z.read("xl/styles.xml"))
    except KeyError:
        return set()
    date_fmt = set()
    numfmts = styles.find(f"{NS}numFmts")
    fmt_is_date = {}
    if numfmts is not None:
        for nf in numfmts.findall(f"{NS}numFmt"):
            code = (nf.get("formatCode") or "").lower()
            fmt_is_date[nf.get("numFmtId")] = ("y" in code and "d" in code) or ("y" in code and "m" in code)
    date_ids = set()
    cellxfs = styles.find(f"{NS}cellXfs")
    if cellxfs is None:
        return date_ids
    for i, xf in enumerate(cellxfs.findall(f"{NS}xf")):
        fid = xf.get("numFmtId")
        if fid is None:
            continue
        if fid in fmt_is_date and fmt_is_date[fid]:
            date_ids.add(i)
        elif fid not in fmt_is_date and int(fid) in (14, 15, 16, 17, 22, 45, 46):  # builtin date formats
            date_ids.add(i)
    return date_ids


def _col_index(ref: str) -> int:
    """'B7' -> 1, 'AA3' -> 26."""
    col = 0
    for ch in ref:
        if ch.isalpha():
            col = col * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return col - 1


def read_xlsx_bytes(raw: bytes, max_rows: int = 100_000):
    """Return (headers, rows) in the same string-matrix shape the CSV
    reader produces, so the rest of the pipeline needs no changes."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    # zip-bomb guard: refuse archives that decompress to absurd sizes
    total_uncompressed = sum(i.file_size for i in z.infolist())
    if total_uncompressed > 400 * 1024 * 1024:
        raise ValueError("This workbook expands to over 400 MB — too large to analyse.")
    # first worksheet: find its path from the workbook (sheet order), with
    # a fallback to the common literal name
    sheet_path = "xl/worksheets/sheet1.xml"
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid = None
        for sh in wb.iter(f"{NS}sheet"):
            rid = sh.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            if rid:
                break
        if rid:
            for rel in rels:
                if rel.get("Id") == rid:
                    target = (rel.get("Target") or "").lstrip("/")
                    if target:
                        if target.startswith("xl/"):
                            sheet_path = target
                        elif target.startswith("worksheets/"):
                            sheet_path = "xl/" + target
                        else:
                            sheet_path = "xl/" + target
    except KeyError:
        pass

    shared = _shared_strings(z)
    date_ids = _date_style_ids(z)
    sheet = ET.fromstring(z.read(sheet_path))

    rows: list[list[str]] = []
    for row in sheet.iter(f"{NS}row"):
        if len(rows) > max_rows + 1:
            break
        cells: list[str] = []
        for c in row.findall(f"{NS}c"):
            idx = _col_index(c.get("r", "A1"))
            while len(cells) < idx:
                cells.append("")  # gaps -> blanks
            t = c.get("t")
            v = c.find(f"{NS}v")
            if t == "s":  # shared string
                val = shared[int(v.text)] if v is not None and v.text and int(v.text) < len(shared) else ""
            elif t == "inlineStr":
                is_el = c.find(f"{NS}is")
                val = "".join(x.text or "" for x in is_el.iter(f"{NS}t")) if is_el is not None else ""
            elif t == "str":  # formula result as string
                val = v.text if v is not None and v.text else ""
            else:
                raw_val = v.text if v is not None and v.text else ""
                s = c.get("s")
                if raw_val and s is not None and int(s) in date_ids:
                    try:  # Excel serial date -> ISO
                        val = (EXCEL_EPOCH + timedelta(days=float(raw_val))).date().isoformat()
                    except (ValueError, OverflowError):
                        val = raw_val
                else:
                    val = raw_val
            cells.append(val)
        if any(c.strip() != "" for c in cells):
            rows.append(cells)

    if not rows:
        raise ValueError("No rows found in the first worksheet.")
    headers = [h.strip() or f"col{i}" for i, h in enumerate(rows[0])]
    width = len(headers)
    body = []
    for r in rows[1:]:
        if len(r) < width:
            r = list(r) + [""] * (width - len(r))
        body.append(r[:width])
    return headers, body
