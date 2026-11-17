"""Smoke-test the full pipeline: profile -> ledger -> story plan."""
import sys, json

sys.path.insert(0, r"C:\Users\user\Documents\plotline")
from server.story_engine import profile_bytes, read_csv_bytes, Column
from server import narrative


def cols_from(p, headers):
    cols = []
    for cd in p["columns"]:
        c = Column(name=cd["name"], index=headers.index(cd["name"]), kind=cd["kind"], raw_kind=cd["kind"])
        c.nulls = cd["nulls"]
        c.drop_share = cd["drop_share"]
        c.note = cd.get("note", "")
        c.minv = cd.get("min")
        c.maxv = cd.get("max")
        c.meanv = cd.get("mean")
        c.medv = cd.get("median")
        c.stddev = cd.get("std")
        c.p25 = cd.get("p25")
        c.p75 = cd.get("p75")
        c.top_values = cd.get("top", [])
        cols.append(c)
    return cols


if __name__ == "__main__":
    for name in ["upi_transactions", "food_orders", "messy", "tiny"]:
        raw = open(rf"C:\Users\user\Documents\plotline\data\{name}.csv", "rb").read()
        p = profile_bytes(raw)
        headers, rows = read_csv_bytes(raw)
        if p["too_small"]:
            print(f"=== {name}: too small ({p['n_rows']} rows) -> honesty frame only ===")
            print(f"  profile: {json.dumps({k: v for k, v in p.items() if k != 'columns'})}")
            continue
        story = narrative.build_story(headers, rows, cols_from(p, headers), p)
        print(f'=== {name}: {story["title"]} ===')
        print(f'  verification: {json.dumps(story["verification"])}')
        for f in story["frames"]:
            print(f'  [{f["id"]}] {f["title"]}')
            for c in f["claims"]:
                tag = c["stat"] or "—"
                print(f'      ({c["role"]:6}) [{tag}] {c["text"][:105]}')
            if f.get("chart_data"):
                cd_ = f["chart_data"]
                keys = list(cd_.keys())
                print(f"      chart: {keys}")
        print()
