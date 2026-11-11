"""screen.py - stage 02: score every account, raise alerts.

Usage:
  python _tools/screen.py --rules   # fixed rubric rules (works offline)
  python _tools/screen.py           # Jev decides (needs the Jev schema confirmed)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger import features  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "stages" / "02_screen" / "output"


def rule_decision(f: dict) -> tuple[str, float, list[str]]:
    hits = []
    if f["cash_deposits_9k_10k"] >= 2:
        hits.append("structuring")
    if f["new_account_senders"] >= 3:
        hits.append("fan_in_new_accounts")
    if f["in_usd"] > 20000 and f["pass_through_ratio"] >= 0.9:
        hits.append("rapid_pass_through")
    if f["high_risk_wires_out"] > 0:
        hits.append("high_risk_destination")
    if f["account_age_days"] is not None and f["account_age_days"] < 60 and f["in_usd"] > 20000:
        hits.append("new_account_burst")
    if len(hits) >= 2:
        return "escalate", min(0.5 + 0.12 * len(hits), 0.98), hits
    if hits:
        return "review", 0.55, hits
    return "clear", 0.9, hits


def jev_decision(account: str, f: dict) -> tuple[str, float, list[str]]:
    from call_model import SCREEN_MODEL, check_policy
    check_policy(SCREEN_MODEL, raw=False)  # features only: ids and numbers, no names
    raise SystemExit("Jev request schema not confirmed yet (docs.typesafe.ai). Use --rules for now.")


def main() -> None:
    use_rules = "--rules" in sys.argv
    alerts = []
    for acct, f in features().items():
        decision, conf, hits = (rule_decision(f) if use_rules else jev_decision(acct, f))
        if decision != "clear":
            alerts.append({"account": acct, "decision": decision, "confidence": round(conf, 2),
                           "signals": hits, "features": f, "source": "rules" if use_rules else "jev"})
    order = {"escalate": 0, "review": 1}
    alerts.sort(key=lambda a: (order[a["decision"]], -a["confidence"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "alerts.json").write_text(json.dumps(alerts, indent=2))
    bad = [a["account"] for a in alerts if a["decision"] == "escalate" and not a["signals"]]
    (OUT / "check.md").write_text("pass\n" if not bad else f"fail: escalated without signals {bad}\n")
    for a in alerts:
        print(f'{a["decision"]:9} {a["account"]:8} {a["confidence"]:.2f} {",".join(a["signals"])}')


if __name__ == "__main__":
    main()
