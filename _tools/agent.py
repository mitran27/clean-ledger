"""agent.py - stage 03 + 04 input: the investigator agent.

A tool-calling loop on a confidential TEE model. The agent chooses which tool to
call next until it calls `finish` or hits MAX_STEPS. Every step is logged to the
trace. The agent PROPOSES actions; it never executes them.

Usage: python _tools/agent.py investigate <account>
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402
import memory  # noqa: E402
import guard  # noqa: E402
import proofchain  # noqa: E402
from call_model import AGENT_MODEL, POLICY, PolicyError, secure_chat  # noqa: E402

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


def search_past_cases(text: str, exclude_case: str | None = None) -> list[dict] | dict:
    """Closed-case memory: embeddings shortlist, reranker order. Pattern text only, no names."""
    try:
        return memory.search(text, exclude_case=exclude_case)
    except PolicyError as e:  # the model sees the refusal and can rephrase
        return {"error": str(e)}


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
    schema("search_past_cases", "Find similar closed cases by pattern. Describe the pattern only: amounts, counts, "
           "account ages, destinations. Never include names. Returns case ids with outcomes.",
           {"text": {"type": "string"}}, ["text"]),
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


ACTIONS = {"close_case", "request_info", "file_sar", "freeze_account"}


def validate_finish(args: dict) -> list[str]:
    """Shape and citation checks on the agent's final answer. Returns problems to fix."""
    known = {t["txn_id"] for t in ledger.transactions()}
    accounts = ledger.accounts()
    probs = []
    if not isinstance(args.get("risk"), (int, float)) or not 0 <= args["risk"] <= 1:
        probs.append("risk must be a number between 0 and 1")
    for i, p in enumerate(args.get("proposed_actions") or [], 1):
        where = f"proposed_actions[{i}]"
        if p.get("action") not in ACTIONS:
            probs.append(f"{where}.action must be one of {sorted(ACTIONS)}")
        if p.get("target") not in accounts:
            probs.append(f"{where} needs 'target': the account id this action applies to (e.g. ACC-M1)")
        ids = p.get("evidence_txn_ids") or []
        if not ids:
            probs.append(f"{where} needs evidence_txn_ids")
        bad = [t for t in ids if t not in known]
        if bad:
            probs.append(f"{where} cites transaction ids that do not exist: {bad}")
    return probs


def investigate(account: str) -> None:
    case = f"case-{account}"
    rubric = (ROOT / "_shared" / "risk-rubric.md").read_text()
    template = (ROOT / "_templates" / "sar.md").read_text()
    messages = [
        {"role": "system", "content":
            "You are an anti-money-laundering investigator. Use tools to gather evidence about the "
            "subject account, deciding each next step from what you found. Cite transaction ids for "
            "every claim. If the activity has a legitimate explanation, say so and propose close_case. "
            "Early on, call search_past_cases with a short description of the pattern you see (no names). "
            "If a closed case matches, cite it in the narrative, e.g. 'matches closed case CASE-012 (SAR filed)'. "
            "A past case is precedent, not proof: every claim still needs transaction ids. "
            f"Call finish within {MAX_STEPS} steps.\n\nRUBRIC:\n{rubric}\n\nSAR TEMPLATE:\n{template}"},
        {"role": "user", "content": f"Investigate {account}. Case id {case}."},
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    trace_path = OUT / f"{case}.trace.jsonl"
    trace_path.write_text("")
    response_ids: list[str] = []
    proofs: list[dict] = []

    def log(entry: dict) -> None:
        with trace_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    chain = proofchain.Chain(OUT / f"{case}.chain.jsonl")
    done_calls: set = set()  # (tool, args) already executed, so relayed text echoes don't re-run

    def finish_case(result: dict) -> None:
        write_result(case, result, response_ids, proofs)
        proofchain.build_receipt(case)

    for step in range(1, MAX_STEPS + 1):
        r = secure_chat(messages, tools=TOOL_SCHEMAS)  # E2EE, attested model, failover pool
        response_ids.append(r.get("id"))
        proof = r.get("_proof")
        if proof:
            proofs.append(proof)
        msg = r["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:  # E2EE relay: a tool call may come back written as text
            calls = _text_tool_calls(msg.get("content") or "", step, done_calls)
            if calls:
                msg = {**msg, "tool_calls": calls}
        # Signed-tool gate: nothing from this response may act unless its TEE signature and byte hashes verify.
        gate = proofchain.verify_step(proof)
        rec = {"step": step, "chat_id": (proof or {}).get("chat_id"), "model": r.get("_model"), "e2ee": r.get("_e2ee", False),
               **{k: (proof or {}).get(k) for k in ("request_sha256", "response_sha256", "signed_text",
                                                    "signature", "signing_address")},
               "tool_calls": [{"name": c["function"]["name"],
                               "args_sha256": proofchain.sha(c["function"]["arguments"] or "")} for c in calls],
               "tool_results": [], "gate": "passed" if not gate else "refused: " + "; ".join(gate)}
        if gate:
            log({"step": step, "gate_refused": gate})
            chain.add(rec)
            return finish_case({"risk": None, "proposed_actions": [], "findings_markdown":
                                "Investigation stopped: a model step failed TEE verification, so no tool ran.\n\n- "
                                + "\n- ".join(gate)})
        messages.append(msg)
        if not calls:
            log({"step": step, "note": "no tool call", "content": msg.get("content")})
            messages.append({"role": "user", "content": "Use a tool, or call finish."})
            chain.add(rec)
            continue
        for c in calls:
            name = c["function"]["name"]
            args = json.loads(c["function"]["arguments"] or "{}")
            if name == "finish":
                problems = validate_finish(args)
                if problems:  # send the errors back so the model fixes its own answer
                    log({"step": step, "tool": "finish", "rejected": problems})
                    rec["tool_results"].append({"name": "finish", "rejected": True})
                    messages.append({"role": "tool", "tool_call_id": c["id"],
                                     "content": json.dumps({"error": "finish rejected", "fix": problems})})
                    continue
                log({"step": step, "tool": "finish", "args": {k: v for k, v in args.items()
                                                               if k != "findings_markdown"}})
                rec["tool_results"].append({"name": "finish", "accepted": True})
                chain.add(rec)
                second_opinion(args, chain, log, response_ids, proofs)
                return finish_case(args)
            if name == "search_past_cases":
                result = search_past_cases(exclude_case=case, **args)
            else:
                result = TOOLS[name](**args) if name in TOOLS else {"error": f"unknown tool {name}"}
            done_calls.add((name, json.dumps(args, sort_keys=True)))
            result, gflags = guard.sanitize(result)  # untrusted free text screened before the model sees it
            entry = {"step": step, "tool": name, "args": args, "result_size": len(json.dumps(result))}
            if gflags:
                entry["guard_flags"] = gflags
            if name == "search_past_cases" and isinstance(result, list):
                entry["preview"] = [{k: m[k] for k in ("case_id", "title", "outcome", "similarity", "rerank_score")}
                                    for m in result]
            log(entry)
            rec["tool_results"].append({"name": name, "result_sha256": proofchain.sha(json.dumps(result, sort_keys=True)),
                                        "guard_flags": len(gflags)})
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)[:12000]})
        chain.add(rec)
    finish_case({"risk": None, "findings_markdown": "Agent hit the step limit without finishing.",
                 "proposed_actions": []})


def _text_tool_calls(text: str, step: int, done: set) -> list[dict]:
    """Under E2EE, tool results are relayed as text, and the model sometimes answers with a tool call
    written as text (e.g. `[called finish({...})]`). Parse those. They come from the signed response,
    so the gate already covers them. Calls that already ran are skipped; a finish call wins."""
    names = "|".join(re.escape(n) for n in list(TOOLS) + ["finish"])
    dec, calls = json.JSONDecoder(), []
    for m in re.finditer(rf"\b({names})\(", text or ""):
        try:
            obj, _ = dec.raw_decode(text, m.end())
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        sig = (m.group(1), json.dumps(obj, sort_keys=True))
        if sig in done or sig in {(c["function"]["name"], json.dumps(json.loads(c["function"]["arguments"]), sort_keys=True)) for c in calls}:
            continue
        calls.append({"id": f"text-{step}-{len(calls)}", "type": "function",
                      "function": {"name": m.group(1), "arguments": json.dumps(obj)}})
    fin = [c for c in calls if c["function"]["name"] == "finish"]
    return fin[-1:] if fin else calls


def _parse_verdict(text: str) -> dict | None:
    for m in reversed(re.findall(r"\{[^{}]*\"agree\"[^{}]*\}", text or "")):
        try:
            return json.loads(m)
        except ValueError:
            continue
    return None


def second_opinion(args: dict, chain, log, response_ids: list, proofs: list) -> None:
    """Two-model rule: a freeze needs an independent attested model from another vendor to agree.
    Otherwise the action is held and the outbox will not run it."""
    pool = POLICY.get("reviewer_pool", [])
    for i, p in enumerate(args["proposed_actions"], 1):
        if p["action"] != "freeze_account":
            continue
        rows, _ = guard.sanitize([t for t in ledger.transactions() if t["txn_id"] in set(p["evidence_txn_ids"])])
        prompt = (f"A first investigator proposes to FREEZE account {p['target']}. Its reason: {p['reason']}\n\n"
                  f"Evidence transactions:\n{json.dumps(rows, indent=1)}\n\nIts SAR draft:\n{args['findings_markdown'][:6000]}\n\n"
                  "Review independently and skeptically. Does the cited evidence justify freezing THIS account now? "
                  'Answer only with JSON: {"agree": true or false, "reason": "one sentence"}')
        try:
            r = secure_chat([{"role": "system", "content": "You are an independent anti-money-laundering reviewer."},
                             {"role": "user", "content": prompt}], models=pool, max_tokens=1500)
        except SystemExit as e:
            p["held"], p["second_opinion"] = True, {"agree": False, "reason": f"no reviewer available: {str(e)[:140]}"}
            continue
        proof = r.get("_proof")
        response_ids.append(r.get("id"))
        if proof:
            proofs.append(proof)
        gate = proofchain.verify_step(proof)
        m = r["choices"][0]["message"]
        verdict = _parse_verdict(m.get("content") or "") or _parse_verdict(m.get("reasoning_content") or "")
        agree = bool(verdict and verdict.get("agree") is True) and not gate
        p["second_opinion"] = {"model": r.get("_model"), "agree": agree,
                               "reason": str((verdict or {}).get("reason", "answer could not be parsed"))[:300]}
        if not agree:
            p["held"] = True
        chain.add({"step": f"review-a{i}", "chat_id": (proof or {}).get("chat_id"), "model": r.get("_model"), "e2ee": True,
                   **{k: (proof or {}).get(k) for k in ("request_sha256", "response_sha256", "signed_text",
                                                        "signature", "signing_address")},
                   "tool_calls": [], "tool_results": [{"name": "second_opinion", "agree": agree}],
                   "gate": "passed" if not gate else "refused: " + "; ".join(gate)})
        log({"step": f"review-a{i}", "tool": "second_opinion", "args": {"target": p["target"]}, "review": p["second_opinion"]})


def write_result(case: str, args: dict, response_ids: list, proofs: list | None = None) -> None:
    (OUT / f"{case}.findings.md").write_text(args["findings_markdown"])
    (OUT / f"{case}.actions.json").write_text(json.dumps(
        {"case": case, "risk": args["risk"], "proposed_actions": args["proposed_actions"]}, indent=2))
    proof = {"model": AGENT_MODEL, "tier": POLICY["models"][AGENT_MODEL]["tier"],
             "response_ids": response_ids, "proofs": proofs or [],
             "all_verified": bool(proofs) and len(proofs) == len(response_ids) and all(p.get("verified") for p in proofs),
             "via_sidecar": bool(proofs)}
    (OUT / f"{case}.proof.json").write_text(json.dumps(proof, indent=2))
    print(f"{case}: risk={args['risk']} actions={[a['action'] for a in args['proposed_actions']]}")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "investigate":
        sys.exit(__doc__)
    try:
        investigate(sys.argv[2])
    except PolicyError as e:
        sys.exit(f"POLICY REFUSED: {e}")
