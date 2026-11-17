"""Quick check that the refactored api/story.py still serves stories."""
import sys
import json

sys.path.insert(0, r"C:\Users\user\Documents\plotline")
from api.story import handler  # noqa: E402

r1 = handler({"method": "POST", "body": open(r"C:\Users\user\Documents\plotline\data\upi_transactions.csv", "rb").read()})
j1 = json.loads(r1["body"])
print("upi:", r1["statusCode"], "ok:", j1["ok"], "frames:", len(j1["frames"]))

r2 = handler({"method": "POST", "body": open(r"C:\Users\user\Documents\plotline\data\tiny.csv", "rb").read()})
j2 = json.loads(r2["body"])
print("tiny: too_small =", j2.get("too_small"))

r3 = handler({"method": "POST", "body": open(r"C:\Users\user\Documents\plotline\data\sales.xlsx", "rb").read()})
j3 = json.loads(r3["body"])
print("xlsx:", r3["statusCode"], "ok:", j3["ok"], "frames:", len(j3["frames"]))

assert j1["ok"] and j2.get("too_small") and j3["ok"]
print("API REFACTOR OK")
