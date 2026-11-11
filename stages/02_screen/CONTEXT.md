# 02_screen - score every account, raise alerts

One job: turn transactions into per-account features and let Jev decide which accounts need an investigation.

## Inputs
- Working (this run): `../../samples/transactions.csv`, `../01_ingest/output/ingest.json`
- Reference (every run): `../../_shared/risk-rubric.md`

Do NOT load: `samples/accounts.csv` (names must not reach a non-confidential model).

## Process
1. If `01_ingest/output/check.md` does not start with `pass`, stop.
2. Run `python _tools/screen.py`: computes features per account (deposit count under $10k, distinct senders, pass-through ratio, outbound high-risk wires), then asks Jev `clear | review | escalate` with confidence.
3. Until the Jev schema is confirmed, `screen.py --rules` uses the rubric as fixed rules so the pipeline still runs.

## Outputs
- `alerts.json` -> `output/` as `[{account, features, decision, confidence, source}]`, escalations first

## Check
Script writes `check.md` = `pass` if every escalation has at least one feature above its rubric threshold.
