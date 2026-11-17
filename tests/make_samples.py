"""Make realistic sample CSVs for local testing.

1. upi_transactions.csv  — Spendlytics-style: date, description, category, amount
2. food_orders.csv       — Food-Delivery-style: date, city, restaurant, dish, qty, revenue
3. tiny.csv              — 12 rows: below the story threshold, must trigger the honesty frame
4. messy.csv             — mixed types, blanks, an ID column, semicolon delimiter
"""

import csv
import random
from datetime import date, timedelta

random.seed(42)
OUT = r"C:\Users\user\Documents\plotline\data"


def upi():
    cats = {
        "Food": (80, 450, 0.30),
        "Transport": (30, 180, 0.18),
        "Shopping": (200, 3200, 0.10),
        "Bills": (150, 2400, 0.08),
        "Groceries": (120, 900, 0.14),
        "Entertainment": (60, 700, 0.10),
        "Health": (100, 1800, 0.06),
        "Travel": (500, 9000, 0.04),
    }
    start = date(2026, 6, 1)
    rows = []
    d = start
    # a Diwali-ish spike in november
    while d <= date(2026, 11, 15):
        # festival spike window
        p_multi = 3.2 if d >= date(2026, 11, 8) else 1.0
        n = random.randint(0, 3)
        for _ in range(n):
            cat = random.choices(list(cats), weights=[c[2] for c in cats.values()])[0]
            lo, hi, _ = cats[cat]
            amt = random.uniform(lo, hi) * p_multi
            merch = random.choice(["Swiggy", "Zomato", "BigBasket", "Amazon", "IRCTC", "Airtel", "Namma Metro", "PVR"])
            rows.append([d.isoformat(), f"{merch} — {cat}", cat, f"{amt:.2f}"])
        d += timedelta(days=1)
    with open(f"{OUT}\\upi_transactions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "description", "category", "amount"])
        w.writerows(rows)
    print(f"upi_transactions.csv: {len(rows)} rows")


def food():
    cities = ["Bengaluru", "Mumbai", "Delhi", "Chennai", "Pune"]
    rests = [f"{c} Kitchen {i}" for c in ["Anand", "Biryani", "Dosa", "Curry", "Punjabi"] for i in range(1, 4)]
    dishes = ["Biryani", "Dosa", "Pizza", "Burger", "Pasta", "Thali", "Noodles"]
    start = date(2026, 1, 1)
    rows = []
    d = start
    while d <= date(2026, 9, 30):
        for _ in range(random.randint(4, 12)):
            qty = random.randint(1, 5)
            price = random.choice([149, 199, 249, 299, 349, 449])
            rows.append([d.isoformat(), random.choice(cities), random.choice(rests),
                         random.choice(dishes), str(qty), str(qty * price)])
        d += timedelta(days=1)
    with open(f"{OUT}\\food_orders.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["order_date", "city", "restaurant", "dish", "quantity", "order_value"])
        w.writerows(rows)
    print(f"food_orders.csv: {len(rows)} rows")


def tiny():
    rows = [[date(2026, 10, i + 1).isoformat(), f"item{i}", str(random.randint(50, 500))]
            for i in range(12)]
    with open(f"{OUT}\\tiny.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "note", "amount"])
        w.writerows(rows)
    print("tiny.csv: 12 rows (below story threshold)")


def messy():
    rows = []
    for i in range(60):
        rows.append([
            f"CUST-{1000+i}",                    # id-like
            random.choice(["", "", "bengaluru", "mumbai", "pune"]),  # blanks
            random.choice(["1", "2", "abc", "3"]),                 # mixed type
            f"{random.uniform(10, 900):.2f}",
        ])
    with open(f"{OUT}\\messy.csv", "w", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["customer_id", "city", "visits", "spend"])
        w.writerows(rows)
    print("messy.csv: 60 rows, semicolon, blanks, id column, mixed types")


if __name__ == "__main__":
    upi()
    food()
    tiny()
    messy()
