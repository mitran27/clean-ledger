# 03_dedup - find similar past reports

One job: list the earlier reports most likely to be duplicates.

## Inputs
- Working (this run): `../02_redact/output/<id>.redacted.md`
- Working (all prior runs): `../02_redact/output/*.redacted.md` except `<id>`

Do NOT load: raw `samples/input/`, any unredacted text.

## Process
1. If `02_redact/output/check.md` does not start with `pass`, stop.
2. Run `python _tools/call_model.py dedup <id>`: embeddings over redacted reports, cosine top 20, then rerank to top 3.
3. No prior reports -> write an empty candidate list; that is valid.

## Outputs
- `<id>.candidates.json` -> `output/` as `[{id, score}]`, at most 3

## Check
Script writes `check.md` = `pass` if the JSON parses and has <= 3 entries.
