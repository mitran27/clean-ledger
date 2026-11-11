"""intake.py - stage 01: hash a report and record intake metadata.

Usage: python _tools/intake.py samples/input/<id>.md
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "stages" / "01_intake" / "output"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = ROOT / sys.argv[1]
    if not src.exists() or src.stat().st_size == 0:
        sys.exit(f"missing or empty input: {sys.argv[1]}")
    data = src.read_bytes()
    rid = src.stem
    m = re.search(r"^Researcher:\s*(\S+)", data.decode(errors="replace"), re.M)
    record = {
        "id": rid,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "researcher": m.group(1) if m else None,
        "anchor_tx": None,  # Nov 13: NEAR anchor transaction hash
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{rid}.intake.json").write_text(json.dumps(record, indent=2))
    ok = hashlib.sha256(src.read_bytes()).hexdigest() == record["sha256"]
    (OUT / "check.md").write_text("pass\n" if ok else "fail: hash mismatch on re-read\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
