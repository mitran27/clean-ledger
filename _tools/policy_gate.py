"""policy_gate.py - stage 04: every proposed action is checked before a human sees it.

Usage: python _tools/policy_gate.py <case>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "_shared" / "action-policy.json").read_text())
IN = ROOT / "stages" / "03_investigate" / "output"
OUT = ROOT / "stages" / "04_propose" / "output"


def judge(p: dict, risk: float, known_txns: set[str]) -> str:
    rule = POLICY["actions"].get(p["action"])
    if rule is None:
        return "denied: unknown action"
    if risk is None or risk < rule["min_risk"]:
        return f"denied: risk {risk} < {rule['min_risk']}"
    cited = p.get("evidence_txn_ids", [])
    if POLICY["global"]["evidence_must_cite_txn_ids"]:
        fake = [t for t in cited if t not in known_txns]
        if fake:
            return f"denied: cites unknown txn ids {fake}"
    if len(cited) < rule["min_evidence"]:
        return f"denied: {len(cited)} evidence < {rule['min_evidence']}"
    cap = rule.get("max_amount_usd")
    if cap is not None and p.get("amount_usd", 0) > cap:
        return f"denied: amount {p['amount_usd']} > cap {cap}"
    return "allowed"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    case = sys.argv[1]
    src = json.loads((IN / f"{case}.actions.json").read_text())
    known = {t["txn_id"] for t in ledger.transactions()}
    proposals = src["proposed_actions"]
    limit = POLICY["global"]["max_actions_per_case"]
    out = []
    for i, p in enumerate(proposals):
        verdict = "denied: too many actions" if i >= limit else judge(p, src["risk"], known)
        out.append({"action_id": f"{case}-a{i + 1}", **p, "verdict": verdict})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{case}.proposals.json").write_text(json.dumps({"case": case, "risk": src["risk"],
                                                             "proposals": out}, indent=2))
    ok = all(p["verdict"] for p in out) and not any(
        p["verdict"] == "allowed" and p["action"] not in POLICY["actions"] for p in out)
    (OUT / "check.md").write_text("pass\n" if ok else "fail: verdict missing or unknown action allowed\n")
    for p in out:
        print(f'{p["action_id"]:22} {p["action"]:15} -> {p["verdict"]}')


if __name__ == "__main__":
    main()
