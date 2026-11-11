# AGENTS.md - map of the Sealed Bounty workspace

Sealed Bounty: a private bug-bounty inbox. Reports are redacted, triaged and analyzed only by attested TEE models on NEAR AI Cloud, and bounties are paid exactly once on NEAR.

## Where things live
- `CONTEXT.md` - the pipeline: stage order, handoffs, what "done" means
- `stages/NN_*/` - one step each; read only that stage's `CONTEXT.md` when running it
- `_shared/` - stable rules: privacy tiers, model policy, severity rubric, schemas
- `_templates/` - copy these to make new outputs
- `_tools/` - scripts; `call_model.py` is the ONLY way to call NEAR AI
- `samples/input/` - fake reports for runs and demos (never real exploits)
- `app/ relay/ sidecar/ contract/` - the product, built from stages once proven
- `HACKATHON.md` - event rules, tracks, submission contract (re-read before submitting)

## Task routing
- Run the pipeline on a report -> `CONTEXT.md`, then each stage in order
- Change which models may see what -> `_shared/privacy-rules.md` + `_shared/policy.json`
- Change scoring -> `_shared/severity-rubric.md`
- Submit to the hackathon -> `HACKATHON.md` (human confirms the payload first)

## Hard rules
1. Never print, log, commit or echo `NEARAI_API_KEY`. It lives only in `.env`.
2. Raw report text goes only to models with tier `confidential` (see `_shared/policy.json`).
3. Never call Incognito-tier models (Anthropic, OpenAI, Google, xAI via NEAR) with report content.
4. Each stage stops at its `## Check`. A `check.md` starting with `fail` stops the run.
5. Never sign transactions, spend mainnet funds, push, or submit without the human's yes.
