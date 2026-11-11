"""outbox.py - stage 04: the agent's proposed actions become outbox events, exactly once.

Idempotency key = sha256(case | action | target). A key already in outbox.jsonl
is skipped, so re-running this script never duplicates an action.

Usage: python _tools/outbox.py <case>
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory  # noqa: E402
import proofchain  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROP = ROOT / "stages" / "03_investigate" / "output"
OUT = ROOT / "stages" / "04_execute" / "output"
EVENT = {"file_sar": "FileSAR", "freeze_account": "FreezeAccount", "request_info": "RequestInfo",
         "close_case": "CloseCase", "anchor_case": "AnchorCase"}


def key(case: str, action: str, target: str) -> str:
    return hashlib.sha256(f"{case}|{action}|{target}".encode()).hexdigest()


def read_events() -> list[dict]:
    box = OUT / "outbox.jsonl"
    return [json.loads(l) for l in box.read_text().splitlines() if l] if box.exists() else []


def run(case: str) -> tuple[int, int]:
    """Write the case's proposed actions to the outbox. Returns (new, skipped)."""
    props = [{**p, "action_id": f"{case}-a{i + 1}"} for i, p in enumerate(
        json.loads((PROP / f"{case}.actions.json").read_text())["proposed_actions"])]
    for p in props:
        if p.get("action") not in EVENT or not p.get("target"):
            raise ValueError(f"{p['action_id']} is malformed (needs a known action and a target): {p}")
    props = [p for p in props if not p.get("held")]  # two-model rule: held actions never run
    OUT.mkdir(parents=True, exist_ok=True)
    box = OUT / "outbox.jsonl"
    existing = {e["idempotency_key"] for e in read_events()}

    to_write = list(props)
    if to_write:
        to_write.append({"action": "anchor_case", "target": case, "action_id": f"{case}-anchor"})

    new = 0
    with box.open("a") as f:
        for p in to_write:
            k = key(case, p["action"], p["target"])
            if k in existing:
                continue
            f.write(json.dumps({"idempotency_key": k, "type": EVENT[p["action"]], "case": case,
                                "action_id": p["action_id"], "target": p["target"],
                                "status": "PENDING",
                                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                    + "\n")
            existing.add(k)
            new += 1
    if new:  # the case is now closed: add it to the past-case memory
        memory.remember_case(case, [p["action"] for p in props])
    proofchain.build_receipt(case)  # receipt now includes the outbox keys
    (OUT / "check.md").write_text("pass\n")
    return new, len(to_write) - new


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    new, skipped = run(sys.argv[1])
    print(f"{new} new outbox events ({skipped} already present, skipped)")


if __name__ == "__main__":
    main()
