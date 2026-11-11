"""ingest.py - stage 01: load and fingerprint the evidence.

Usage: python _tools/ingest.py
"""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TX, AC = ROOT / "samples" / "transactions.csv", ROOT / "samples" / "accounts.csv"
OUT = ROOT / "stages" / "01_ingest" / "output"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    for p in (TX, AC):
        if not p.exists() or p.stat().st_size == 0:
            raise SystemExit(f"missing or empty: {p.relative_to(ROOT)}")
    rec = {
        "rows": sum(1 for _ in csv.DictReader(TX.open())),
        "accounts": sum(1 for _ in csv.DictReader(AC.open())),
        "sha256_transactions": sha(TX),
        "sha256_accounts": sha(AC),
        "loaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "anchor_tx": None,  # NEAR anchor of the evidence hash: Nov 13
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ingest.json").write_text(json.dumps(rec, indent=2))
    ok = sha(TX) == rec["sha256_transactions"] and sha(AC) == rec["sha256_accounts"]
    (OUT / "check.md").write_text("pass\n" if ok else "fail: hash changed during ingest\n")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
