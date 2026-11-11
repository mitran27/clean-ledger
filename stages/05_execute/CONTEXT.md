# 05_execute - outbox, exactly once

One job: write every gate-allowed action as an outbox event with an idempotency key.

## Inputs
- Working (this run): `../04_propose/output/<case>.proposals.json`

Do NOT load: findings, CSVs.

## Process
1. If `04_propose/output/check.md` does not start with `pass`, stop.
2. Run `python _tools/outbox.py <case>`: idempotency key = sha256(case + action + target). A key already in `outbox.jsonl` is skipped, so re-running is safe.
3. Today: handlers are mocks (`FileSAR` -> mock regulator, `FreezeAccount` -> mock core banking, `AnchorCase` -> stubbed NEAR anchor).

## Outputs
- `outbox.jsonl` -> `output/` (append-only)

## Check
Script: re-run produces zero new rows -> `check.md` = `pass` (proves idempotency).
