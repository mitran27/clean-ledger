# CONTEXT.md - the Sealed Bounty pipeline

One run = one report, identified by `<id>` (the input file name without extension).

| Stage | Job | Model (tier) | Output |
|---|---|---|---|
| 01_intake | Verify, hash, anchor | none | `<id>.intake.json` |
| 02_redact | Strip secrets and personal data | privacy-filter (confidential) | `<id>.redacted.md` |
| 03_dedup | Find similar past reports | embeddings + rerank (redacted text only) | `<id>.candidates.json` |
| 04_triage | Spam / duplicate / valid + severity | typesafe/jev-1.13 (redacted text only) | `<id>.decision.json` |
| 05_analyze | Reproduce, explain, fix + proof | z-ai/glm-5.3-flash (confidential) | `<id>.analysis.md`, `<id>.proof.json` |
| 06_review | Human approve or reject | person | `<id>.review.json` |

Routing: 04 with `route: close` ends the run after 04. Everything else continues to 05.

Done = `stages/06_review/output/<id>.review.json` exists with `decision` set, and every earlier stage's `check.md` says `pass`.

Each stage's `output/` is the next stage's input. Stages map 1:1 to outbox event handlers in `relay/` once proven.
