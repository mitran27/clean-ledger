# 03_investigate - the agent traces the money

One job: for one escalated account, an agent decides which tools to call until it has enough evidence or rules it a false alarm.

## Inputs
- Working (this run): `../02_screen/output/alerts.json` (one account), `../../samples/*.csv` (via tools only)
- Reference (every run): `../../_shared/risk-rubric.md`, `../../_templates/sar.md`

Do NOT load: other cases, the whole CSV into the prompt (tools return slices).

## Process
1. If the account's decision is not `escalate`, stop.
2. Run `python _tools/agent.py investigate <account>` (model `z-ai/glm-5.3-flash`, confidential, tool calling).
3. Tools: `query_transactions`, `trace_counterparties`, `account_profile`, `search_past_cases`, `finish`. Max 8 steps.
4. Every tool call and result is appended to `<case>.trace.jsonl`.

## Outputs
- `<case>.findings.md` -> `output/` (filled `_templates/sar.md`)
- `<case>.trace.jsonl` -> `output/` (the agent's reasoning trail)
- `<case>.proof.json` -> `output/` (model, tier, response ids, attestation, signatures)

## Check
A person reads the findings: does every evidence line cite real transaction ids from the trace? Write `check.md`.
