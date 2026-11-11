# 04_execute - outbox, exactly once

One job: write each action the agent proposed as an outbox event with an idempotency key.

## Inputs
- Working (this run): `../03_investigate/output/<case>.actions.json`

Do NOT load: findings, CSVs.

## Process
1. If `03_investigate/output/check.md` does not start with `pass`, stop.
2. Run `python _tools/outbox.py <case>`: idempotency key = sha256(case + action + target). A key already in `outbox.jsonl` is skipped, so re-running is safe.
3. Today: handlers are mocks (`FileSAR` -> mock regulator, `FreezeAccount` -> mock core banking, `AnchorCase` -> stubbed NEAR anchor).

## Outputs
- `outbox.jsonl` -> `output/` (append-only)

## Check
Script: re-run produces zero new rows -> `check.md` = `pass` (proves idempotency).
