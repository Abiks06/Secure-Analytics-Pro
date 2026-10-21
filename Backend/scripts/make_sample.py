"""Generate a deliberately messy e-commerce dataset for demos and tests.

uv run python scripts/make_sample.py ../samples/messy_sales.csv --rows 5000
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

REGIONS = {"West": 1.6, "East": 1.0, "North": 0.8, "South": 0.55}
CHANNELS = ["Web", "Mobile App", "Retail", "Partner"]
PRODUCTS = {"Starter": 49, "Pro": 149, "Business": 499, "Enterprise": 2400}
FIRST = ["Ada", "Kwame", "Lena", "Tunde", "Mia", "Diego", "Aisha", "Chen", "Noah", "Zara", "Ife", "Omar"]
LAST = ["Mensah", "Okafor", "Schmidt", "Garcia", "Kim", "Ade", "Novak", "Silva", "Brown", "Boateng"]


def luhn_card(rng: random.Random) -> str:
    digits = [4] + [rng.randint(0, 9) for _ in range(14)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            d -= 9 if d > 9 else 0
        total += d
    digits.append((10 - total % 10) % 10)
    s = "".join(map(str, digits))
    return f"{s[:4]} {s[4:8]} {s[8:12]} {s[12:]}"


def messy_date(d: date, rng: random.Random) -> str:
    r = rng.random()
    if r < 0.6:
        return d.isoformat()
    if r < 0.8:
        return d.strftime("%m/%d/%Y")
    if r < 0.93:
        return d.strftime("%b %d, %Y")
    return d.strftime("%Y-%m-%dT10:%M:00Z").replace("%M", "00")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--rows", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    start = date(2024, 1, 1)
    rows = []
    for i in range(args.rows):
        # Order volume grows over time (a growing business); Nov/Dec get a holiday lift below.
        day = start + timedelta(days=int(640 * rng.random() ** 0.6))
        region = rng.choices(list(REGIONS), weights=[3, 4, 2, 2])[0]
        product = rng.choices(list(PRODUCTS), weights=[6, 4, 2, 0.6])[0]
        growth = 1 + (day - start).days / 900
        units = max(1, int(rng.expovariate(1 / (2.2 * REGIONS[region]))) + 1)
        price = PRODUCTS[product] * rng.uniform(0.9, 1.1)
        discount = rng.choice([0, 0, 0, 5, 10, 15, 20])
        revenue = units * price * (1 - discount / 100) * growth * (1.35 if day.month in (11, 12) else 1)
        if rng.random() < 0.004:
            revenue *= 40  # data-entry blow-ups
        ad_spend = units * price * rng.uniform(0.05, 0.2) + rng.gauss(0, 25)
        first, last = rng.choice(FIRST), rng.choice(LAST)
        rev = f"${revenue:,.2f}" if rng.random() < 0.7 else f"{revenue:.2f}"
        if rng.random() < 0.01:
            rev = f"({abs(revenue):,.2f})"
        if rng.random() < 0.02:
            rev = rng.choice(["N/A", "", "-", "null"])
        rows.append(
            {
                "Order ID": f"ORD-{100000 + i}",
                " Order Date ": messy_date(day, rng),
                "Customer Name": f"{first} {last}",
                "Email": f"{first.lower()}.{last.lower()}{rng.randint(1, 99)}@example.com"
                if rng.random() > 0.03
                else "n/a",
                "Phone": f"+1 ({rng.randint(200, 989)}) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}",
                "Card Number": luhn_card(rng),
                "Region": rng.choice([region, region.upper(), region.lower(), f" {region} "])
                if rng.random() < 0.15
                else region,
                "Channel": rng.choice(CHANNELS),
                "Product": product,
                "Units": str(units),
                "Unit Price": f"{price:.2f}",
                "Discount": f"{discount}%",
                "Revenue": rev,
                "Ad Spend": f"{max(ad_spend, 0):.2f}",
                "Satisfaction": rng.choice(["5", "4", "4", "3", "", "4", "5", "2"]),
                "Returned": rng.choice(["No", "no", "N", "No", "No", "Yes", "FALSE", "no"]),
            }
        )
    rows += rng.sample(rows, k=max(1, args.rows // 100))  # exact duplicates
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
