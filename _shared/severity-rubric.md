# severity-rubric.md - how severity is scored

| Severity | Meaning | Example |
|---|---|---|
| critical | Unauthenticated fund loss or full takeover | Anyone can drain the escrow contract |
| high | Authenticated fund loss, or data exposure of many users | Owner-only check missing on a payout path |
| medium | Limited impact or needs unlikely conditions | Rate limit bypass leading to spam |
| low | Hardening, information leak without direct harm | Verbose error reveals a stack trace |
| none | Not a vulnerability | Feature request, out of scope |

Duplicate = same root cause AND same affected component as an earlier report, even if worded differently.
Spam = no concrete component, no steps, or unrelated to the program scope.
