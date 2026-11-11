# 01_ingest - load and fingerprint the evidence

One job: load transactions and accounts, and record a hash of exactly what was investigated.

## Inputs
- Working (this run): `../../samples/transactions.csv`, `../../samples/accounts.csv`

Do NOT load: other stages, `_shared/`.

## Process
1. If an input is missing or empty, stop and say which.
2. Run `python _tools/ingest.py` from the workspace root.
3. Today: anchoring the evidence hash on NEAR is stubbed (`anchor_tx: null`).

## Outputs
- `ingest.json` -> `output/` with `{rows, accounts, sha256_transactions, sha256_accounts, loaded_at, anchor_tx}`

## Check
Script re-hashes both files and writes `check.md` = `pass` if they match.
