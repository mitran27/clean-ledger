# 04_triage - Jev decides spam, duplicate or valid

One job: a typed decision with confidence that routes the report.

## Inputs
- Working (this run): `../02_redact/output/<id>.redacted.md`, `../03_dedup/output/<id>.candidates.json`
- Reference (every run): `../../_shared/severity-rubric.md`, `../../_templates/jev-question.json`

Do NOT load: raw `samples/input/`, stage 05 outputs.

## Process
1. If `03_dedup/output/check.md` does not start with `pass`, stop.
2. Run `python _tools/call_model.py triage <id>` (model `typesafe/jev-1.13`, redacted only).
3. Route: `label in {spam, duplicate}` AND `confidence >= 0.9` -> `close`; otherwise -> `analyze`.

## Outputs
- `<id>.decision.json` -> `output/` as `{label, duplicate_of, severity, confidence, route}`

## Check
Script validates the schema and writes `check.md`. A person spot-checks every `close` decision during the demo week.
