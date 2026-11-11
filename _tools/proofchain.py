"""proofchain.py - signed-tool gate, transcript chain and case receipt.

verify_step(proof)
    The signed-tool gate. Checks one model step: the TEE's ed25519 signature over
    "model:request_hash:response_hash", and that the exact bytes this process sent and
    received hash to those values. The agent runs no tool unless this passes, so an
    altered or forged response (including a forged tool call) cannot act.
Chain
    Tamper-evident transcript: every step's hashes are linked to the previous step.
build_receipt / verify_receipt
    A portable case record with proofs and hashes but no customer data. An examiner can
    re-verify it offline:  .venv/bin/python _tools/proofchain.py verify case-ACC-M1

Scope: the gate proves the response came unaltered from the attested TEE model. It does not
stop that model from being misled by its inputs (prompt injection); that needs other controls.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from events import emit  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INV = ROOT / "stages" / "03_investigate" / "output"
EXE = ROOT / "stages" / "04_execute" / "output"
POLICY_FILES = ["_shared/policy.json", "_shared/privacy-rules.md", "_shared/risk-rubric.md"]
GENESIS = "0" * 64


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def verify_step(proof: dict | None) -> list[str]:
    """Signed-tool gate. Returns the problems found; an empty list means the step may act."""
    if not proof:
        return ["no TEE proof: this step did not go through the attestation sidecar"]
    probs = []
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(proof["signing_address"])).verify(
            bytes.fromhex(proof["signature"]), proof["signed_text"].encode())
    except ImportError:
        probs.append("cryptography is not installed: run with .venv/bin/python")
    except Exception:
        probs.append("TEE signature does not verify")
    try:
        _, req_h, resp_h = proof["signed_text"].rsplit(":", 2)
    except (KeyError, ValueError, AttributeError, TypeError):
        return probs + ["signed text missing or malformed"]
    if req_h != proof.get("request_sha256"):
        probs.append("request bytes differ from what the TEE signed")
    if resp_h != proof.get("response_sha256"):
        probs.append("response bytes differ from what the TEE signed")
    return probs


class Chain:
    """Append-only transcript where each entry carries the hash of the one before it."""

    def __init__(self, path: Path):
        self.path, self.head, self.length = path, GENESIS, 0
        path.write_text("")

    def add(self, entry: dict) -> str:
        body = {**entry, "prev": self.head}
        body["hash"] = sha(canon(body))
        with self.path.open("a") as f:
            f.write(json.dumps(body) + "\n")
        emit("receipt", "agent", f"Step {entry.get('step')} sealed in the transcript chain",
             because="its hashes are linked to the previous step, so any later edit breaks the chain",
             hash=body["hash"][:14] + "…", previous=body["prev"][:14] + "…")
        self.head, self.length = body["hash"], self.length + 1
        return self.head


def _read_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text().splitlines() if l] if p.exists() else []


def _file_sha(p: Path) -> str | None:
    return sha(p.read_bytes()) if p.exists() else None


def _outbox_keys_for_this_run(case: str) -> list[str]:
    """Keys of the outbox events for THIS run's proposed actions (same formula as outbox.key),
    so an event left over from an earlier run of the same case is not claimed by this receipt."""
    p = INV / f"{case}.actions.json"
    acts = json.loads(p.read_text())["proposed_actions"] if p.exists() else []
    wanted = [sha(f"{case}|{a['action']}|{a['target']}") for a in acts]
    if acts:
        wanted.append(sha(f"{case}|anchor_case|{case}"))
    present = {e["idempotency_key"] for e in _read_jsonl(EXE / "outbox.jsonl")}
    return [k for k in wanted if k in present]


def build_receipt(case: str) -> dict:
    chain = _read_jsonl(INV / f"{case}.chain.jsonl")
    proof = json.loads((INV / f"{case}.proof.json").read_text()) if (INV / f"{case}.proof.json").exists() else {}
    ingest = ROOT / "stages" / "01_ingest" / "output" / "ingest.json"
    rec = {
        "case": case,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": proof.get("model"), "tier": proof.get("tier"),
        "policy_sha256": {f: _file_sha(ROOT / f) for f in POLICY_FILES},
        "evidence_sha256": json.loads(ingest.read_text()).get("sha256_transactions") if ingest.exists() else None,
        "chain": {"length": len(chain), "head": chain[-1]["hash"] if chain else None,
                  "all_steps_gated": bool(chain) and all(e.get("gate") == "passed" for e in chain)},
        "signing_keys": sorted({e["signing_address"] for e in chain if e.get("signing_address")}),
        "attestation_tokens": sorted({p["attestation_jti"] for p in proof.get("proofs", []) if p.get("attestation_jti")}),
        "findings_sha256": _file_sha(INV / f"{case}.findings.md"),
        "actions_sha256": _file_sha(INV / f"{case}.actions.json"),
        "outbox_keys": _outbox_keys_for_this_run(case),
        "anchor_tx": None,  # NEAR anchor of receipt_sha256: next step
    }
    rec["receipt_sha256"] = sha(canon(rec))
    emit("receipt", "agent", "Case receipt sealed", because="proofs, policy hashes, chain head and outbox keys, "
         "with no customer data; an examiner can re-verify it offline", receipt_hash=rec["receipt_sha256"][:16] + "…",
         chain_steps=len(chain), outbox_keys=len(rec["outbox_keys"]))
    EXE.mkdir(parents=True, exist_ok=True)
    (EXE / f"{case}.receipt.json").write_text(json.dumps(rec, indent=2))
    return rec


def verify_receipt(case: str) -> list[tuple[str, bool, str]]:
    """Offline re-verification. Needs only the case files; no network, no API key."""
    out: list[tuple[str, bool, str]] = []
    path = EXE / f"{case}.receipt.json"
    if not path.exists():
        return [("receipt exists", False, str(path))]
    rec = json.loads(path.read_text())
    body = {k: v for k, v in rec.items() if k != "receipt_sha256"}
    out.append(("receipt hash recomputes", sha(canon(body)) == rec["receipt_sha256"], rec["receipt_sha256"][:16] + "…"))
    chain = _read_jsonl(INV / f"{case}.chain.jsonl")
    prev, links_ok = GENESIS, True
    for e in chain:
        b = {k: v for k, v in e.items() if k != "hash"}
        links_ok &= e["prev"] == prev and sha(canon(b)) == e["hash"]
        prev = e["hash"]
    out.append(("transcript chain links and hashes", links_ok and bool(chain), f"{len(chain)} steps"))
    out.append(("chain head matches receipt", bool(chain) and chain[-1]["hash"] == rec["chain"]["head"]
                and len(chain) == rec["chain"]["length"], (rec["chain"]["head"] or "")[:16] + "…"))
    bad = [e["step"] for e in chain if verify_step(e)]
    out.append(("every step's TEE signature and hashes verify", not bad and bool(chain),
                f"failed steps {bad}" if bad else f"{len(chain)} of {len(chain)}"))
    ungated = [e["step"] for e in chain if e.get("tool_results") and e.get("gate") != "passed"]
    out.append(("no tool ran on an unverified step", not ungated, f"steps {ungated}" if ungated else "all gated"))
    out.append(("SAR draft unchanged", _file_sha(INV / f"{case}.findings.md") == rec["findings_sha256"], ""))
    out.append(("proposed actions unchanged", _file_sha(INV / f"{case}.actions.json") == rec["actions_sha256"], ""))
    changed = [f for f, h in rec["policy_sha256"].items() if _file_sha(ROOT / f) != h]
    out.append(("policy files are the ones enforced", not changed, f"changed: {changed}" if changed else ""))
    keys = {e["idempotency_key"] for e in _read_jsonl(EXE / "outbox.jsonl")}
    out.append(("outbox actions match receipt", all(k in keys for k in rec["outbox_keys"]), f"{len(rec['outbox_keys'])} actions"))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("verify", "build"):
        sys.exit(__doc__)
    if sys.argv[1] == "build":
        print(json.dumps(build_receipt(sys.argv[2]), indent=2))
        sys.exit(0)
    results = verify_receipt(sys.argv[2])
    for name, ok, detail in results:
        print(("PASS  " if ok else "FAIL  ") + name + (f"  ({detail})" if detail else ""))
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)
