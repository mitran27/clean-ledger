"""make_samples.py - generate synthetic bank data (deterministic, seed 7).

Planted cases:
  ACC-M1  mule: structuring cash deposits + fan-in from 6 new accounts, then a fast
          offshore wire (should be escalated, SAR + freeze proposed).
  ACC-D1  decoy: busy coffee shop with many small payers, old accounts, no
          pass-through (should be cleared by the agent: false-positive bait).
Usage: python _tools/make_samples.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples"
rng = random.Random(7)
START = date(2026, 10, 1)
FIRST = ["Ana", "Ben", "Chen", "Dara", "Eli", "Fay", "Gus", "Hana", "Ivan", "Jo", "Kai", "Lea"]
LAST = ["Ortiz", "Nguyen", "Smith", "Patel", "Kim", "Rossi", "Haddad", "Novak"]


def name() -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def main() -> None:
    accounts, txns = [], []
    n = 0

    def tx(day, frm, to, amt, kind, country="US"):
        nonlocal n
        n += 1
        txns.append([f"T{n:04d}", (START + timedelta(days=day)).isoformat(), frm, to,
                     f"{amt:.2f}", kind, country])

    for i in range(1, 26):
        accounts.append([f"ACC-{i:03d}", name(), "2019-05-01", "US", "personal"])
    accounts.append(["ACC-D1", "Bluebird Coffee LLC", "2015-03-12", "US", "business"])
    accounts.append(["ACC-M1", name(), "2026-09-20", "US", "personal"])
    for i in range(1, 7):
        accounts.append([f"ACC-S{i}", name(), f"2026-09-{22 + i:02d}", "US", "personal"])
    accounts.append(["ACC-X1", "Harbor Trade Ltd", "2024-01-01", "KY", "business"])

    normal = [a[0] for a in accounts if a[0].startswith("ACC-0")]
    for _ in range(140):  # background noise
        a, b = rng.sample(normal, 2)
        tx(rng.randint(0, 40), a, b, rng.uniform(20, 2500), "transfer")
    for _ in range(45):  # decoy: many small payers, money stays
        tx(rng.randint(0, 40), rng.choice(normal), "ACC-D1", rng.uniform(4, 60), "card")
    for d in range(0, 40, 14):
        tx(d, "ACC-D1", "ACC-007", 3200, "payroll")
    for i in range(1, 7):  # mule: structuring + fan-in
        for _ in range(2):
            day = 10 + rng.randint(0, 3)
            tx(day, f"ACC-S{i}", f"ACC-S{i}", rng.uniform(9100, 9900), "cash_deposit")
            tx(day + 1, f"ACC-S{i}", "ACC-M1", rng.uniform(9000, 9800), "transfer")
    tx(15, "ACC-M1", "ACC-X1", 112000, "wire", "KY")  # rapid pass-through offshore

    txns.sort(key=lambda r: (r[1], r[0]))
    OUT.mkdir(exist_ok=True)
    with open(OUT / "transactions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["txn_id", "date", "from_account", "to_account", "amount_usd", "type", "country"])
        w.writerows(txns)
    with open(OUT / "accounts.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["account", "name", "opened", "country", "kind"])
        w.writerows(accounts)
    print(f"{len(txns)} transactions, {len(accounts)} accounts -> samples/")


if __name__ == "__main__":
    main()
