# 01_intake - verify, hash, anchor report

One job: accept one report file and record its fingerprint.

## Inputs
- Working (this run): `../../samples/input/<id>.md`

Do NOT load: other stages, `_shared/`, other reports.

## Process
1. If the input is missing or empty, stop and say which.
2. Run `python _tools/intake.py samples/input/<id>.md` from the workspace root.
3. Today: on-chain anchoring is stubbed (`anchor_tx: null`). Nov 13: replace with the NEAR anchor call.

## Outputs
- `<id>.intake.json` -> `output/` with `{id, sha256, bytes, received_at, researcher, anchor_tx}`

## Check
Script: `intake.py` re-hashes the input and writes `check.md` = `pass` if it matches.
