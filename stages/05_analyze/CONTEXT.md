# 05_analyze - TEE analysis with proof

One job: reproduce, explain and propose a fix inside a confidential TEE model.

## Inputs
- Working (this run): `../../samples/input/<id>.md` (RAW: allowed only because the model tier is confidential), `../04_triage/output/<id>.decision.json`
- Reference (every run): `../../_shared/severity-rubric.md`, `../../_templates/analysis.md`

Do NOT load: other reports, the redacted copy (the model needs the real details).

## Process
1. If `04_triage` route is `close`, stop: this stage does not run.
2. Run `python _tools/call_model.py analyze <id>` (model `z-ai/glm-5.3-flash`, confidential).
3. The tool saves the response id and attestation info to `<id>.proof.json`.

## Outputs
- `<id>.analysis.md` -> `output/` (filled `_templates/analysis.md`)
- `<id>.proof.json` -> `output/`

## Check
A person reads the analysis: is the severity justified by the rubric, and do the repro steps match the report? Write `check.md`.
