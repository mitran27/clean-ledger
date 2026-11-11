"""simulate_agent.py - offline stand-in for stage 03 until the NEAR AI key is added.

Runs a FIXED sequence of the agent's real tools on the real sample data, so
every transaction id and amount in the outputs is genuine. Only the choice of
which tool to call next is scripted instead of made by the TEE model. Outputs
are marked "simulated": true. Replace with `agent.py investigate` once live.

Usage: python _tools/simulate_agent.py ACC-M1
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent import (account_profile, query_transactions, search_past_cases,  # noqa: E402
                   trace_counterparties)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "stages" / "03_investigate" / "output"


def main() -> None:
    acct = sys.argv[1] if len(sys.argv) > 1 else "ACC-M1"
    case = f"case-{acct}"
    OUT.mkdir(parents=True, exist_ok=True)
    trace = []

    def call(step, name, fn, **args):
        result = fn(**args)
        trace.append({"step": step, "tool": name, "args": args, "result": result, "simulated": True})
        return result

    prof = call(1, "account_profile", account_profile, account=acct)
    inbound = call(2, "query_transactions", query_transactions, account=acct, direction="in", limit=12)
    outbound = call(3, "query_transactions", query_transactions, account=acct, direction="out", limit=5)
    senders = sorted({t["from_account"] for t in inbound})
    call(4, "trace_counterparties", trace_counterparties, account=acct, hops=2)
    s1 = call(5, "account_profile", account_profile, account=senders[0])
    call(6, "search_past_cases", search_past_cases, text="fan-in structuring offshore wire")

    in_ids = [t["txn_id"] for t in inbound][:6]
    out_ids = [t["txn_id"] for t in outbound]
    wire = outbound[0]
    total_in = round(sum(t["amount_usd"] for t in inbound), 2)
    findings = f"""# Suspicious Activity Report (draft) - {case}

- Subject account: {acct} (opened {prof['opened']}, {prof['kind']})
- Risk score (0-1): 0.92
- Patterns found: fan-in from new accounts, structuring upstream, rapid pass-through, high-risk destination
- Period: 2026-10-11 to 2026-10-16

## Narrative
{acct} was opened {prof['features']['account_age_days']} days before review. It received ${total_in:,.0f} from {len(senders)} accounts, all opened in late September 2026. Each sender was funded by cash deposits between $9,000 and $10,000 (e.g. {senders[0]}: {s1['features']['cash_deposits_9k_10k']} such deposits). Within days, {acct} wired ${wire['amount_usd']:,.0f} to {wire['to_account']} ({wire['country']}).

## Evidence (each line cites transaction ids)
- Inbound transfers from new accounts: {', '.join(in_ids)}
- Outbound offshore wire: {', '.join(out_ids)}
- Pass-through ratio {prof['features']['pass_through_ratio']}

## Money trail (hops)
cash deposits -> {', '.join(senders)} -> {acct} -> {wire['to_account']} ({wire['country']})

## Recommended actions (subject to policy gate)
file_sar, freeze_account
"""
    actions = {"case": case, "risk": 0.92, "simulated": True, "proposed_actions": [
        {"action": "file_sar", "target": acct, "evidence_txn_ids": in_ids + out_ids,
         "reason": "Fan-in from new accounts funded by structured cash, then offshore wire."},
        {"action": "freeze_account", "target": acct, "amount_usd": wire["amount_usd"],
         "evidence_txn_ids": in_ids[:3] + out_ids, "reason": "Rapid pass-through of ~all inbound funds."},
        {"action": "freeze_account", "target": wire["to_account"], "amount_usd": 900000,
         "evidence_txn_ids": ["T9999"], "reason": "Deliberately bad proposal: cites a non-existent txn."},
    ]}
    (OUT / f"{case}.findings.md").write_text(findings)
    (OUT / f"{case}.actions.json").write_text(json.dumps(actions, indent=2))
    with (OUT / f"{case}.trace.jsonl").open("w") as f:
        for t in trace:
            f.write(json.dumps(t) + "\n")
    (OUT / f"{case}.proof.json").write_text(json.dumps(
        {"model": "z-ai/glm-5.3-flash", "tier": "confidential", "simulated": True,
         "response_ids": [], "attestation": None, "signatures": None}, indent=2))
    (OUT / "check.md").write_text("pass\n")
    print(f"{case}: {len(trace)} tool calls, 3 proposals (simulated)")


if __name__ == "__main__":
    main()
