"""events.py - plain-language event log behind the Flow Log page (logs/events.jsonl).

Every component (sidecar, agent, guard, outbox, receipt) appends one line per meaningful step,
with a colour category and a "because" that names what caused it. Only public material is
logged: public keys, nonce and hash prefixes, ids, verdicts. Never the API key or a private key.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "logs" / "events.jsonl"
_lock = threading.Lock()


def short(v, n: int = 12):
    return (v[:n] + "…") if isinstance(v, str) and len(v) > n else v


def emit(kind: str, actor: str, title: str, because: str | None = None, status: str = "ok", **detail) -> None:
    """kind: attest | key | crypto | model | sign | gate | tool | guard | memory | review | outbox | receipt | info"""
    rec = {"ts": round(time.time(), 3), "kind": kind, "actor": actor, "title": title, "because": because,
           "status": status, "detail": {k: v for k, v in detail.items() if v is not None}}
    try:
        LOG.parent.mkdir(exist_ok=True)
        with _lock, LOG.open("a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except OSError:
        pass  # logging must never break the pipeline


def reset() -> None:
    LOG.unlink(missing_ok=True)


def read() -> list[dict]:
    return [json.loads(l) for l in LOG.read_text().splitlines() if l] if LOG.exists() else []
