# 06_review - program owner decides

One job: record approve or reject, which later triggers payout or refund.

## Inputs
- Working (this run): `../05_analyze/output/<id>.analysis.md`, `../05_analyze/output/<id>.proof.json`, `../04_triage/output/<id>.decision.json`

Do NOT load: raw report, other reports.

## Process
1. If `05_analyze/output/check.md` does not start with `pass`, stop.
2. The person decides. Write the review file by hand.
3. Today: payout is not executed. Nov 13: `approve` writes a `ReleaseBounty` outbox event.

## Outputs
- `<id>.review.json` -> `output/` as `{decision: approve|reject, severity, amount_usdc, reviewer, reason}`

## Check
The person is the check. `check.md` = `pass` once the file is saved.
