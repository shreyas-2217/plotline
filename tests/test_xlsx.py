"""Test the stdlib xlsx reader against a real .xlsx written by openpyxl.

openpyxl is a TEST-ONLY dependency — production code stays stdlib.
"""
import sys
import random
from datetime import date, timedelta

sys.path.insert(0, r"C:\Users\user\Documents\plotline")

import openpyxl

from server.xlsx_reader import read_xlsx_bytes, is_xlsx
from server.story_engine import profile_bytes
from server import narrative

random.seed(7)

wb = openpyxl.Workbook()
ws = wb.active
ws.append(["date", "region", "product", "units", "revenue"])  # header row

start = date(2026, 1, 1)
for i in range(90):
    d = start + timedelta(days=i)
    region = random.choice(["north", "south", "east", "west"])
    product = random.choice(["Widget", "Gadget", "Gizmo"])
    units = random.randint(1, 40)
    # weekly seasonality + growth so the trend frame has signal
    rev = round(units * random.uniform(80, 160) * (1 + i / 200) * (1.35 if d.weekday() >= 5 else 1.0), 2)
    ws.append([d, region, product, units, rev])

# set the date column to a real date format so style detection must fire
for row in ws.iter_rows(min_row=2, min_col=1, max_col=1):
    row[0].number_format = "dd-mm-yyyy"

path = r"C:\Users\user\Documents\plotline\data\sales.xlsx"
wb.save(path)
print(f"wrote {path}")

# now the stdlib reader
raw = open(path, "rb").read()
assert is_xlsx(raw), "magic bytes not detected"
headers, rows = read_xlsx_bytes(raw)
print(f"read back: {len(rows)} rows x {len(headers)} cols")
print("header:", headers)
print("row 1:", rows[0])
assert headers == ["date", "region", "product", "units", "revenue"]
assert len(rows) == 90
assert rows[0][0] == "2026-01-01", f"date serial not converted: {rows[0][0]}"
assert rows[0][3] == "1" or rows[0][3].isdigit() or rows[0][3].replace(".", "", 1).isdigit(), rows[0][3]

# full pipeline: profile -> story
p = profile_bytes(raw)
print("\nkinds:", {c["name"]: c["kind"] for c in p["columns"]})
assert p["columns"][0]["kind"] == "date", p["columns"][0]

story = narrative.build_story(headers, rows,
                              __import__("api.story", fromlist=["x"]).make_columns(p, headers), p)
print("\ntitle:", story["title"])
for f in story["frames"]:
    print(f"  [{f['id']}] {f['title']}")
    for c in f["claims"][:2]:
        print(f"      {c['text'][:100]}")
print("\nverification:", story["verification"])
print("\nXLSX PIPELINE OK")
