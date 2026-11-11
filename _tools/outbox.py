"""outbox.py - stage 05: gate-allowed actions become outbox events, exactly once.

Idempotency key = sha256(case | action | target). A key already in outbox.jsonl
is skipped, so re-running this script never duplicates an action.

Usage: python _tools/outbox.py <case>
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROP = ROOT / "stages" / "04_propose" / "output"
OUT = ROOT / "stages" / "05_execute" / "output"
EVENT = {"file_sar": "FileSAR", "freeze_account": "FreezeAccount",
         "request_info": "RequestInfo", "close_case": "CloseCase"}


def key(case: str, action: str, target: str) -> str:
    return hashlib.sha256(f"{case}|{action}|{target}".encode()).hexdigest()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    case = sys.argv[1]
    props = json.loads((PROP / f"{case}.proposals.json").read_text())["proposals"]
    OUT.mkdir(parents=True, exist_ok=True)
    box = OUT / "outbox.jsonl"
    existing = {json.loads(l)["idempotency_key"] for l in box.read_text().splitlines() if l} \
        if box.exists() else set()

    to_write = [p for p in props if p["verdict"] == "allowed"]
    if to_write:
        to_write.append({"action": "anchor_case", "target": case, "action_id": f"{case}-anchor"})
    EVENT["anchor_case"] = "AnchorCase"

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
    print(f"{new} new outbox events ({len(to_write) - new} already present, skipped)")
    (OUT / "check.md").write_text("pass\n")


if __name__ == "__main__":
    main()
