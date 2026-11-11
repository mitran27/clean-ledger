"""ledger.py - read-only access to the synthetic data, shared by screen.py and agent tools."""
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIGH_RISK = {"KY", "PA", "VG"}


def transactions() -> list[dict]:
    rows = list(csv.DictReader((ROOT / "samples" / "transactions.csv").open()))
    for r in rows:
        r["amount_usd"] = float(r["amount_usd"])
    return rows


def accounts() -> dict[str, dict]:
    return {r["account"]: r for r in csv.DictReader((ROOT / "samples" / "accounts.csv").open())}


def features(as_of: str = "2026-11-10") -> dict[str, dict]:
    """Pseudonymous per-account features: ids and numbers only, no names."""
    acc = accounts()
    tx = transactions()
    f = defaultdict(lambda: {"in_usd": 0.0, "out_usd": 0.0, "senders": set(), "near_10k": 0,
                             "new_senders": 0, "high_risk_out": 0})
    for t in tx:
        a, b, amt = t["from_account"], t["to_account"], t["amount_usd"]
        if t["type"] == "cash_deposit" and 9000 <= amt < 10000:
            f[a]["near_10k"] += 1
        if a == b:
            continue
        f[a]["out_usd"] += amt
        f[b]["in_usd"] += amt
        f[b]["senders"].add(a)
        if t["country"] in HIGH_RISK:
            f[a]["high_risk_out"] += 1
    ref = date.fromisoformat(as_of)
    out = {}
    for k, v in f.items():
        new = [s for s in v["senders"]
               if (ref - date.fromisoformat(acc[s]["opened"])).days < 60]
        age = (ref - date.fromisoformat(acc[k]["opened"])).days if k in acc else None
        out[k] = {
            "in_usd": round(v["in_usd"], 2),
            "out_usd": round(v["out_usd"], 2),
            "distinct_senders": len(v["senders"]),
            "new_account_senders": len(new),
            "cash_deposits_9k_10k": v["near_10k"],
            "pass_through_ratio": round(v["out_usd"] / v["in_usd"], 2) if v["in_usd"] else 0.0,
            "high_risk_wires_out": v["high_risk_out"],
            "account_age_days": age,
        }
    return out
