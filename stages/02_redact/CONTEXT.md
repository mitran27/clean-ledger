# 02_redact - strip secrets and personal data

One job: produce a redacted copy that non-confidential models may see.

## Inputs
- Working (this run): `../../samples/input/<id>.md`, `../01_intake/output/<id>.intake.json`
- Reference (every run): `../../_shared/privacy-rules.md`

Do NOT load: other reports, stages 03-06.

## Process
1. If `01_intake/output/check.md` does not start with `pass`, stop.
2. Run `python _tools/call_model.py redact samples/input/<id>.md > stages/02_redact/output/<id>.redacted.md`
3. Keep code structure, endpoints and steps; replace keys, emails, names, account ids with `[REDACTED:<type>]`.

## Outputs
- `<id>.redacted.md` -> `output/`

## Check
A person scans the redacted file for anything secret-looking (keys, emails, private URLs), then writes `check.md` = `pass` or `fail: <what leaked>`.
