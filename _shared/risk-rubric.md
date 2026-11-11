# risk-rubric.md - money-laundering patterns the agent looks for

| Pattern | Signal | Weight |
|---|---|---|
| Structuring | Many cash deposits just under $10,000 within days | high |
| Fan-in | Many new or unrelated accounts send to one account | high |
| Rapid pass-through | Money arrives and leaves within 48 hours, balance near zero | high |
| High-risk destination | Outbound wire to a high-risk jurisdiction | medium |
| New account burst | Account opened < 30 days ago with sudden volume | medium |
| Round amounts | Repeated round-number transfers | low |

Risk score: 0.0-1.0. Two high signals with cited transactions -> at least 0.8.
Every finding must cite transaction ids. No citation = not evidence.
