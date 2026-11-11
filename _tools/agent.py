"""agent.py - stage 03 + 04 input: the investigator agent.

A tool-calling loop on a confidential TEE model. The agent chooses which tool to
call next until it calls `finish` or hits MAX_STEPS. Every step is logged to the
trace. The agent PROPOSES actions; it never executes them.

Usage: python _tools/agent.py investigate <account>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402
from call_model import AGENT_MODEL, POLICY, PolicyError, chat  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "stages" / "03_investigate" / "output"
MAX_STEPS = 8

# ---------- tools (read-only over the ledger) ----------


def query_transactions(account: str, direction: str = "both", limit: int = 25) -> list[dict]:
    rows = [t for t in ledger.transactions()
            if (direction in ("in", "both") and t["to_account"] == account)
            or (direction in ("out", "both") and t["from_account"] == account)]
    return sorted(rows, key=lambda t: -t["amount_usd"])[:limit]


def trace_counterparties(account: str, hops: int = 2) -> dict:
    tx = ledger.transactions()
    frontier, seen, edges = {account}, {account}, []
    for _ in range(min(hops, 3)):
        nxt = set()
        for t in tx:
            a, b = t["from_account"], t["to_account"]
            if a != b and (a in frontier or b in frontier):
                edges.append({"from": a, "to": b, "usd": t["amount_usd"], "txn": t["txn_id"]})
                nxt |= {a, b} - seen
        seen |= nxt
        frontier = nxt
    return {"accounts": sorted(seen), "edges": edges[:60]}


def account_profile(account: str) -> dict:
    acc = ledger.accounts().get(account, {})
    return {**acc, "features": ledger.features().get(account, {})}


def search_past_cases(text: str) -> list[dict]:
    # Nov 12: embeddings + rerank over closed cases. Empty shelf today.
    return []


TOOLS = {"query_transactions": query_transactions, "trace_counterparties": trace_counterparties,
         "account_profile": account_profile, "search_past_cases": search_past_cases}


def schema(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}}


TOOL_SCHEMAS = [
    schema("query_transactions", "Transactions in/out of an account, largest first.",
           {"account": {"type": "string"}, "direction": {"type": "string", "enum": ["in", "out", "both"]},
            "limit": {"type": "integer"}}, ["account"]),
    schema("trace_counterparties", "Follow money up to 3 hops from an account.",
           {"account": {"type": "string"}, "hops": {"type": "integer"}}, ["account"]),
    schema("account_profile", "Owner, open date, country, kind, and risk features.",
           {"account": {"type": "string"}}, ["account"]),
    schema("search_past_cases", "Find similar closed cases.", {"text": {"type": "string"}}, ["text"]),
    schema("finish", "Stop investigating and report.",
           {"risk": {"type": "number", "description": "0-1 per the rubric"},
            "findings_markdown": {"type": "string", "description": "Filled SAR template"},
            "proposed_actions": {"type": "array", "items": {"type": "object", "properties": {
                "action": {"type": "string", "enum": ["close_case", "request_info", "file_sar", "freeze_account"]},
                "target": {"type": "string"}, "amount_usd": {"type": "number"},
                "evidence_txn_ids": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"}}, "required": ["action", "target", "evidence_txn_ids", "reason"]}}},
           ["risk", "findings_markdown", "proposed_actions"]),
]


def investigate(account: str) -> None:
    case = f"case-{account}"
    rubric = (ROOT / "_shared" / "risk-rubric.md").read_text()
    template = (ROOT / "_templates" / "sar.md").read_text()
    messages = [
        {"role": "system", "content":
            "You are an anti-money-laundering investigator. Use tools to gather evidence about the "
            "subject account, deciding each next step from what you found. Cite transaction ids for "
            "every claim. If the activity has a legitimate explanation, say so and propose close_case. "
            f"Call finish within {MAX_STEPS} steps.\n\nRUBRIC:\n{rubric}\n\nSAR TEMPLATE:\n{template}"},
        {"role": "user", "content": f"Investigate {account}. Case id {case}."},
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    trace_path = OUT / f"{case}.trace.jsonl"
    trace_path.write_text("")
    response_ids: list[str] = []

    def log(entry: dict) -> None:
        with trace_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    for step in range(1, MAX_STEPS + 1):
        r = chat(AGENT_MODEL, messages, raw=True, tools=TOOL_SCHEMAS, tool_choice="auto")
        response_ids.append(r.get("id"))
        msg = r["choices"][0]["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            log({"step": step, "note": "no tool call", "content": msg.get("content")})
            messages.append({"role": "user", "content": "Use a tool, or call finish."})
            continue
        for c in calls:
            name = c["function"]["name"]
            args = json.loads(c["function"]["arguments"] or "{}")
            if name == "finish":
                log({"step": step, "tool": "finish", "args": {k: v for k, v in args.items()
                                                               if k != "findings_markdown"}})
                return write_result(case, args, response_ids)
            result = TOOLS[name](**args) if name in TOOLS else {"error": f"unknown tool {name}"}
            log({"step": step, "tool": name, "args": args, "result_size": len(json.dumps(result))})
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)[:12000]})
    write_result(case, {"risk": None, "findings_markdown": "Agent hit the step limit without finishing.",
                        "proposed_actions": []}, response_ids)


def write_result(case: str, args: dict, response_ids: list) -> None:
    (OUT / f"{case}.findings.md").write_text(args["findings_markdown"])
    (OUT / f"{case}.actions.json").write_text(json.dumps(
        {"case": case, "risk": args["risk"], "proposed_actions": args["proposed_actions"]}, indent=2))
    proof = {"model": AGENT_MODEL, "tier": POLICY["models"][AGENT_MODEL]["tier"],
             "response_ids": response_ids, "attestation": None, "signatures": None,
             "note": "ITA attestation + per-response signature verification lands with the sidecar"}
    (OUT / f"{case}.proof.json").write_text(json.dumps(proof, indent=2))
    print(f"{case}: risk={args['risk']} actions={[a['action'] for a in args['proposed_actions']]}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "investigate":
        sys.exit(__doc__)
    try:
        investigate(sys.argv[2])
    except PolicyError as e:
        sys.exit(f"POLICY REFUSED: {e}")
