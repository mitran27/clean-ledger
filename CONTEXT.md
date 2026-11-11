# CONTEXT.md - the Clean Ledger pipeline

One run = one alert (a flagged account), identified by `<case>` (e.g. `case-ACC-M1`).

| Stage | Job | Who / model (tier) | Output |
|---|---|---|---|
| 01_ingest | Load transactions, hash the evidence | script | `ingest.json` |
| 02_screen | Score every account, raise alerts | `typesafe/jev-1.13` (features only, no names) | `alerts.json` |
| 03_investigate | Agent loop: trace money, gather evidence | `z-ai/glm-5.3-flash` (confidential) + tools | `<case>.findings.md`, `<case>.trace.jsonl`, `<case>.proof.json` |
| 04_propose | Agent proposes actions; policy gate rules on each | agent + `_tools/policy_gate.py` | `<case>.proposals.json` |
| 05_execute | Gate-allowed actions -> outbox events (exactly once) | `_tools/outbox.py` | `outbox.jsonl` |

Routing: an alert below the screen threshold never reaches 03. A proposal denied by the gate never reaches 05; denials are kept with the rule that fired.

Done = `stages/05_execute/output/outbox.jsonl` holds the case's allowed actions, each with an idempotency key, and every earlier `check.md` says `pass`.

Stages map 1:1 to outbox event handlers in `relay/` once proven. The agent's tools become sidecar-proxied calls.
