# AGENTS.md - map of the Clean Ledger workspace

Clean Ledger: an agentic anti-money-laundering investigator. A tool-using agent investigates flagged transactions inside a confidential TEE on NEAR AI Cloud, proposes actions, and the outbox executes each one exactly once.

## Where things live
- `CONTEXT.md` - the pipeline: stage order, handoffs, what "done" means
- `stages/NN_*/` - one step each; read only that stage's `CONTEXT.md` when running it
- `_shared/` - stable rules: privacy tiers, model policy, action policy, risk rubric
- `_templates/` - copy these to make new outputs (SAR draft)
- `_tools/` - scripts; `call_model.py` is the ONLY way to call NEAR AI
- `samples/` - synthetic bank data (never real customers)
- `app/ relay/ sidecar/ contract/` - the product, built from stages once proven
- `HACKATHON.md` - event rules, tracks, submission contract (re-read before submitting)

## Task routing
- Run an investigation -> `CONTEXT.md`, then each stage in order
- Change which models may see what -> `_shared/privacy-rules.md` + `_shared/policy.json`
- Submit to the hackathon -> `HACKATHON.md` (human confirms the payload first)

## Hard rules
1. Never print, log, commit or echo `NEARAI_API_KEY`. It lives only in `.env`.
2. Customer-identifying data goes only to models with tier `confidential` (see `_shared/policy.json`).
3. The agent proposes actions; it never executes them. Only `04_execute` writes outbox events.
4. Each stage stops at its `## Check`. A `check.md` starting with `fail` stops the run.
5. Never sign transactions, spend mainnet funds, push, or submit without the human's yes.
