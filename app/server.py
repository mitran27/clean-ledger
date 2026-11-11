"""Clean Ledger API + UI.

Run from the workspace root:
  .venv/bin/uvicorn app.server:app --reload --port 8000
Then open http://localhost:8000

The API reads and writes the same ICM stage folders the scripts use, so the
UI, the scripts and any coding agent always see one state on disk.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "_tools"))

import agent  # noqa: E402
import call_model  # noqa: E402
import ledger  # noqa: E402
import outbox  # noqa: E402
from screen import rule_decision  # noqa: E402

STAGES = ROOT / "stages"
INV = STAGES / "03_investigate" / "output"
app = FastAPI(title="Clean Ledger", version="0.1.0")


def key_present() -> bool:
    call_model.load_env()
    return os.environ.get("NEARAI_API_KEY", "").startswith("sk-")


def read_json(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/log")
def log_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "log.html")


@app.get("/api/events")
def events_api() -> list[dict]:
    """The latest investigation's event log (public material only: keys, hashes, verdicts)."""
    import events
    return events.read()


@app.get("/api/status")
def status() -> dict:
    tx = ledger.transactions()
    return {"transactions": len(tx), "accounts": len(ledger.accounts()),
            "agent_mode": "live" if key_present() else "simulated",
            "agent_model": call_model.AGENT_MODEL,
            "agent_tier": call_model.POLICY["models"][call_model.AGENT_MODEL]["tier"],
            "ingest": read_json(STAGES / "01_ingest" / "output" / "ingest.json")}


@app.get("/api/alerts")
def alerts() -> list[dict]:
    """Stage 02 on the fly: every account that is not clear, worst first."""
    out = []
    acc = ledger.accounts()
    for a, f in ledger.features().items():
        decision, conf, signals = rule_decision(f)
        if decision != "clear":
            out.append({"account": a, "decision": decision, "confidence": round(conf, 2),
                        "signals": signals, "in_usd": f["in_usd"], "kind": acc.get(a, {}).get("kind"),
                        "cash_9k": f["cash_deposits_9k_10k"],
                        "case_exists": (INV / f"case-{a}.actions.json").exists()})
    order = {"escalate": 0, "review": 1}
    return sorted(out, key=lambda x: (order[x["decision"]], -x["in_usd"]))


@app.get("/api/accounts/{account}")
def account(account: str) -> dict:
    acc = ledger.accounts()
    if account not in acc:
        raise HTTPException(404, f"Unknown account {account}")
    tx = [t for t in ledger.transactions() if account in (t["from_account"], t["to_account"])]
    rows = []
    for t in sorted(tx, key=lambda t: (t["date"], t["txn_id"])):
        direction = "self" if t["from_account"] == t["to_account"] else \
            "in" if t["to_account"] == account else "out"
        rows.append({**t, "direction": direction, "flags": ledger.flags_for(t, account, acc)})
    return {"profile": acc[account], "features": ledger.features().get(account, {}),
            "transactions": rows, "flagged": sum(1 for r in rows if r["flags"])}


@app.get("/api/accounts/{account}/flow")
def flow(account: str) -> dict:
    """Money trail: cash -> upstream senders -> subject -> destinations."""
    acc = ledger.accounts()
    tx = ledger.transactions()
    up = defaultdict(lambda: {"usd": 0.0, "txns": []})
    down = defaultdict(lambda: {"usd": 0.0, "txns": [], "country": "US"})
    for t in tx:
        if t["to_account"] == account and t["from_account"] != account:
            up[t["from_account"]]["usd"] += t["amount_usd"]
            up[t["from_account"]]["txns"].append(t["txn_id"])
        if t["from_account"] == account and t["to_account"] != account:
            down[t["to_account"]]["usd"] += t["amount_usd"]
            down[t["to_account"]]["txns"].append(t["txn_id"])
            down[t["to_account"]]["country"] = t["country"]
    cash = {s: round(sum(t["amount_usd"] for t in tx if t["from_account"] == s == t["to_account"]
                         and t["type"] == "cash_deposit"), 2) for s in up}
    top_up = sorted(up.items(), key=lambda kv: -kv[1]["usd"])[:8]
    return {"subject": account,
            "upstream": [{"account": a, "usd": round(v["usd"], 2), "txns": v["txns"],
                          "cash_in": cash.get(a, 0), "opened": acc.get(a, {}).get("opened")} for a, v in top_up],
            "upstream_more": max(0, len(up) - len(top_up)),
            "downstream": [{"account": a, "usd": round(v["usd"], 2), "txns": v["txns"],
                            "country": v["country"]} for a, v in sorted(down.items(), key=lambda kv: -kv[1]["usd"])[:5]]}


@app.post("/api/investigate/{account}")
def investigate(account: str) -> dict:
    """Stage 03. Live TEE agent when the key is present, otherwise the scripted stand-in."""
    if account not in ledger.accounts():
        raise HTTPException(404, f"Unknown account {account}")
    if key_present():
        import agent
        try:
            agent.investigate(account)
        except call_model.PolicyError as e:
            raise HTTPException(403, f"Policy refused: {e}")
        except SystemExit as e:  # call_model exits on HTTP errors with a readable message
            raise HTTPException(502, str(e))
        mode = "live"
    else:
        import simulate_agent
        sys.argv = ["simulate_agent.py", account]
        simulate_agent.main()
        mode = "simulated"
    return {"mode": mode, **case(f"case-{account}")}


@app.get("/api/cases/{case_id}")
def case(case_id: str) -> dict:
    actions = read_json(INV / f"{case_id}.actions.json")
    if actions is None:
        raise HTTPException(404, f"No investigation yet for {case_id}")
    trace_file = INV / f"{case_id}.trace.jsonl"
    trace = [json.loads(l) for l in trace_file.read_text().splitlines() if l] if trace_file.exists() else []
    for t in trace:  # results can be large; the UI shows a summary
        r = t.pop("result", None)
        if r is not None:
            t["result_size"] = len(json.dumps(r))
    return {"case": case_id, "actions": actions,
            "findings": (INV / f"{case_id}.findings.md").read_text() if (INV / f"{case_id}.findings.md").exists() else "",
            "trace": trace, "proof": read_json(INV / f"{case_id}.proof.json"),
            "verification": verification(case_id),
            "outbox": [e for e in outbox.read_events() if e["case"] == case_id]}


def sidecar_proofs() -> dict[str, dict]:
    f = ROOT / "sidecar" / "proofs.jsonl"
    recs = [json.loads(l) for l in f.read_text().splitlines() if l] if f.exists() else []
    return {r["chat_id"]: r for r in recs}


def agent_chain(case_id: str) -> list[dict]:
    f = INV / f"{case_id}.chain.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l] if f.exists() else []


def verification(case_id: str) -> dict | None:
    """What the sidecar verified for this case's model calls (the 'Verified' panel)."""
    proof = read_json(INV / f"{case_id}.proof.json")
    recs = sidecar_proofs()
    mine = [recs[p["chat_id"]] for p in (proof or {}).get("proofs", []) if p.get("chat_id") in recs]
    if not mine:
        return None
    last = mine[-1]
    return {"calls": len(proof["proofs"]), "verified_calls": len(mine), "all_verified": proof.get("all_verified"),
            "model": last["model"], "tier": last["tier"], "tcb_status": last["tcb_status"], "gpu_ok": last["gpu_ok"],
            "request_hash_matches": all(r["request_hash_matches"] for r in mine),
            "response_hash_matches": all(r["response_hash_matches"] for r in mine),
            "checks": last["attestation_checks"] + last["signature_checks"],
            "e2ee_calls": sum(1 for e in agent_chain(case_id) if e.get("e2ee")),
            "models": sorted({e.get("model") for e in agent_chain(case_id) if e.get("model")}),
            "attestation_jti": last["attestation_jti"], "signing_address": last["signing_address"]}


FLAG_NOTES = {"structuring": "Cash deposit between $9,000 and $10,000: just under the $10k reporting threshold",
              "new_sender": "Sent by an account opened less than 60 days ago",
              "offshore": "Wire to a high-risk jurisdiction",
              "large": "Amount of $50,000 or more"}


def cited_in_text(txn_id: str, text: str) -> str | None:
    """'exact' if the id appears, 'range' if it falls inside a cited range like T0190–T0212."""
    if re.search(rf"\b{txn_id}\b", text):
        return "exact"
    n = int(txn_id[1:])
    for a, b in re.findall(r"T(\d{4})\s*[–—-]+\s*T?(\d{4})", text):
        if int(a) <= n <= int(b):
            return "range"
    return None


@app.get("/api/transactions/{txn_id}/flow")
def txn_flow(txn_id: str, account: str) -> dict:
    """One transaction through the four ICM stages: what each stage did with it, and who could see it."""
    tx = next((t for t in ledger.transactions() if t["txn_id"] == txn_id), None)
    if tx is None:
        raise HTTPException(404, f"Unknown transaction {txn_id}")
    if account not in (tx["from_account"], tx["to_account"]):
        raise HTTPException(422, f"{txn_id} does not involve {account}")
    acc = ledger.accounts()
    case_id = f"case-{account}"
    stages = []

    # 01 ingest: the row is fingerprinted as part of the evidence file
    ingest = read_json(STAGES / "01_ingest" / "output" / "ingest.json") or {}
    line = next((l for l in (ROOT / "samples" / "transactions.csv").read_text().splitlines()[1:]
                 if l.startswith(txn_id + ",")), "")
    stages.append({"id": "01_ingest", "folder": "stages/01_ingest", "title": "Ingest", "state": "hash",
                   "label": "fingerprinted", "sees": "Local files and hashes only",
                   "files": ["ingest.json"], "badges": [],
                   "notes": ["Row read from samples/transactions.csv",
                             f"Row sha256 {hashlib.sha256(line.encode()).hexdigest()[:14]}…",
                             f"Part of the evidence file hash {str(ingest.get('sha256_transactions', ''))[:14]}…",
                             "Anchoring that hash on NEAR: planned"]})

    # 02 screen: which rubric signals this transaction trips, and the account-level call
    feats = ledger.features().get(account)
    decision, conf, signals = rule_decision(feats) if feats else ("clear", 0.0, [])
    flags = ledger.flags_for(tx, account, acc)
    notes = [FLAG_NOTES[f] for f in flags] or ["No rubric signal on this transaction by itself"]
    notes.append(f"Account call: {decision} ({conf:.2f})" + (f" on {', '.join(signals)}" if signals else ""))
    notes.append("Screening sees counts and amounts only, never names")
    stages.append({"id": "02_screen", "folder": "stages/02_screen", "title": "Screen",
                   "state": "flag" if flags else "clear", "label": f"{len(flags)} signal{'s' if len(flags) != 1 else ''}" if flags else "clear",
                   "sees": "Pseudonymous numbers only", "files": ["alerts.json"], "badges": [], "notes": notes})

    # 03 investigate: did the agent see it, cite it, and was the model call attested
    actions = read_json(INV / f"{case_id}.actions.json")
    if actions is None:
        stages.append({"id": "03_investigate", "folder": "stages/03_investigate", "title": "Investigate",
                       "state": "idle", "label": "not run", "sees": "Plaintext only inside the attested TEE",
                       "files": [], "badges": [], "notes": [f"No investigation for {account} yet", "Press Investigate in TEE below"]})
        stages.append({"id": "04_execute", "folder": "stages/04_execute", "title": "Execute", "state": "idle",
                       "label": "nothing to run", "sees": "Hashes and ids only", "files": [], "badges": [], "notes": ["Runs after an investigation proposes actions"]})
        return {"txn": tx, "account": account, "stages": stages}
    trace = [json.loads(l) for l in (INV / f"{case_id}.trace.jsonl").read_text().splitlines() if l]
    seen = []
    for t in trace:
        args, tool = t.get("args") or {}, t.get("tool")
        try:
            if tool == "query_transactions":
                hit = any(r["txn_id"] == txn_id for r in agent.query_transactions(**args))
            elif tool == "trace_counterparties":
                hit = any(e["txn"] == txn_id for e in agent.trace_counterparties(**args)["edges"])
            else:
                hit = False
        except TypeError:
            hit = False
        if hit:
            seen.append((t["step"], tool))
    findings = (INV / f"{case_id}.findings.md").read_text() if (INV / f"{case_id}.findings.md").exists() else ""
    cite = cited_in_text(txn_id, findings)
    proposals = actions["proposed_actions"]
    citing = [(i, p) for i, p in enumerate(proposals, 1) if txn_id in (p.get("evidence_txn_ids") or [])]
    proof = read_json(INV / f"{case_id}.proof.json") or {}
    n_calls = len(proof.get("proofs", []))
    n3 = []
    if seen:
        n3.append(f"Returned to the agent at step {seen[0][0]} by {seen[0][1]}" + (f" (+{len(seen) - 1} more)" if len(seen) > 1 else ""))
    if cite:
        n3.append("Cited in the SAR draft" + (" (inside a cited id range)" if cite == "range" else ""))
    for i, p in citing:
        n3.append(f"Evidence for {p['action']} on {p['target']}")
    mem = next((t for t in trace if t.get("tool") == "search_past_cases" and t.get("preview")), None)
    if mem and (seen or cite):
        top = mem["preview"][0]
        n3.append(f"Pattern matched closed {top['case_id']} (similarity {top['similarity']}): {top['outcome']}")
    flagged = [f for t in trace for f in (t.get("guard_flags") or []) if f.get("txn_id") == txn_id]
    if flagged:
        n3.insert(0, f"Memo withheld by the injection guard ({flagged[0]['verdict']}, confidence "
                     f"{flagged[0]['confidence']}): it tried to instruct the AI reviewer")
    badges = []
    if flagged:
        badges.append({"text": "injection blocked", "cls": "warn"})
    if seen and n_calls:
        incl = max(0, n_calls - (seen[0][0] - 1))
        badges.append({"text": f"in {incl} attested model call{'s' if incl != 1 else ''}", "cls": "vio"})
    if proof.get("all_verified"):
        badges.append({"text": "TEE + signatures verified", "cls": "ok"})
    if not n3:
        n3 = ["The agent did not need this transaction to reach its conclusion"]
    state3 = "evidence" if citing else "seen" if (seen or cite) else "idle"
    stages.append({"id": "03_investigate", "folder": "stages/03_investigate", "title": "Investigate", "state": state3,
                   "label": {"evidence": "cited as evidence", "seen": "seen by agent", "idle": "not used"}[state3],
                   "sees": "Plaintext only inside the attested TEE", "files": ["findings.md", "trace.jsonl", "proof.json"],
                   "badges": badges, "notes": n3})

    # 04 execute: outbox events that exist because of this transaction
    ids = {f"{case_id}-a{i}" for i, _ in citing}
    events = [e for e in outbox.read_events() if e["case"] == case_id and e["action_id"] in ids]
    held = [p for _, p in citing if p.get("held")]
    if events:
        n4 = [f"{e['type']} on {e['target']}: {e['status']}, key {e['idempotency_key'][:14]}…" for e in events]
        n4 += [f"{p['action']} on {p['target']} held: second model disagreed" for p in held]
        n4.append("Each key is stored once, so a re-run cannot repeat the action")
        state4, label4 = "acted", "action queued"
    elif citing:
        n4, state4, label4 = ["Action proposed but the outbox has not run yet"], "flag", "proposed"
    else:
        n4, state4, label4 = ["No action depends on this transaction"], "idle", "no action"
    stages.append({"id": "04_execute", "folder": "stages/04_execute", "title": "Execute", "state": state4,
                   "label": label4, "sees": "Hashes and ids only", "files": ["outbox.jsonl"], "badges": [], "notes": n4})
    return {"txn": tx, "account": account, "stages": stages}


@app.post("/api/cases/{case_id}/execute")
def execute(case_id: str) -> dict:
    """Stage 04. Safe to call repeatedly: idempotency keys skip what already ran."""
    if not (INV / f"{case_id}.actions.json").exists():
        raise HTTPException(404, f"No investigation yet for {case_id}")
    try:
        new, skipped = outbox.run(case_id)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"new": new, "skipped": skipped,
            "events": [e for e in outbox.read_events() if e["case"] == case_id]}
