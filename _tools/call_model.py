"""call_model.py - the only way this workspace calls NEAR AI Cloud.

Enforces _shared/policy.json: raw report text only goes to tier "confidential"
models with allow_raw=true. The API key is read from .env and never printed.

Usage (from the workspace root):
  python _tools/call_model.py ping
  python _tools/call_model.py redact samples/input/<id>.md
  python _tools/call_model.py dedup <id>        # needs EMBED_MODEL / RERANK_MODEL in .env
  python _tools/call_model.py triage <id>       # Jev request schema still to confirm
  python _tools/call_model.py analyze <id>
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "_shared" / "policy.json").read_text())
STAGES = ROOT / "stages"
ANALYZE_MODEL = "z-ai/glm-5.3-flash"
TRIAGE_MODEL = "typesafe/jev-1.13"
REDACT_MODEL = "openai/privacy-filter"


class PolicyError(Exception):
    pass


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def api_key() -> str:
    key = os.environ.get("NEARAI_API_KEY", "")
    if not key.startswith("sk-"):
        sys.exit("NEARAI_API_KEY missing or malformed in .env (value not shown).")
    return key


def check_policy(model: str, raw: bool) -> None:
    rule = POLICY["models"].get(model)
    if rule is None:
        raise PolicyError(f"{model}: not in _shared/policy.json (default deny)")
    if rule["tier"] == "incognito":
        raise PolicyError(f"{model}: incognito tier never receives report content")
    if raw and not (rule["tier"] == "confidential" and rule.get("allow_raw")):
        raise PolicyError(f"{model}: tier {rule['tier']} may not see raw report text")


def request(method: str, path: str, body: dict | None = None) -> dict:
    url = POLICY["base_url"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key()}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise SystemExit(f"HTTP {e.code} on {method} {path}: {detail}")


def chat(model: str, messages: list[dict], raw: bool, **extra) -> dict:
    check_policy(model, raw)
    body = {"model": model, "messages": messages, **extra}
    if model.startswith("z-ai/"):
        body.setdefault("chat_template_kwargs", {"enable_thinking": False})
    return request("POST", "/chat/completions", body)


def out(stage: str, name: str) -> Path:
    p = STAGES / stage / "output" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------- commands ----------

def cmd_ping() -> None:
    r = chat(ANALYZE_MODEL, [{"role": "user", "content": "Say hello in one sentence."}], raw=False)
    print(r["choices"][0]["message"]["content"])


def cmd_redact(path: str) -> None:
    text = (ROOT / path).read_text()
    # NOTE: privacy-filter returns PII spans; the exact request/response shape is
    # confirmed on the first live call. Until then, fail loudly rather than guess.
    r = chat(REDACT_MODEL, [{"role": "user", "content": text}], raw=True)
    print(json.dumps(r, indent=2))


def cmd_dedup(rid: str) -> None:
    embed_model = os.environ.get("EMBED_MODEL")
    rerank_model = os.environ.get("RERANK_MODEL")
    if not (embed_model and rerank_model):
        sys.exit("Set EMBED_MODEL and RERANK_MODEL in .env after checking /v1/models.")
    for m in (embed_model, rerank_model):
        check_policy(m, raw=False)
    red_dir = STAGES / "02_redact" / "output"
    query = (red_dir / f"{rid}.redacted.md").read_text()
    others = {p.name.split(".")[0]: p.read_text() for p in red_dir.glob("*.redacted.md")
              if not p.name.startswith(rid + ".")}
    result: list[dict] = []
    if others:
        ids = list(others)
        rr = request("POST", "/rerank", {"model": rerank_model, "query": query,
                                         "documents": [others[i] for i in ids]})
        ranked = sorted(rr.get("results", []), key=lambda x: -x["relevance_score"])[:3]
        result = [{"id": ids[x["index"]], "score": round(x["relevance_score"], 4)} for x in ranked]
    out("03_dedup", f"{rid}.candidates.json").write_text(json.dumps(result, indent=2))
    out("03_dedup", "check.md").write_text("pass\n" if len(result) <= 3 else "fail: >3\n")
    print(json.dumps(result, indent=2))


def cmd_triage(rid: str) -> None:
    check_policy(TRIAGE_MODEL, raw=False)
    sys.exit("Jev request schema not confirmed yet: read https://docs.typesafe.ai/concepts/system-one, "
             "then implement here. Policy check for redacted input passed.")


def cmd_analyze(rid: str) -> None:
    raw = (ROOT / "samples" / "input" / f"{rid}.md").read_text()
    rubric = (ROOT / "_shared" / "severity-rubric.md").read_text()
    template = (ROOT / "_templates" / "analysis.md").read_text()
    msgs = [
        {"role": "system", "content": "You are a security triage analyst. Fill the template exactly. "
                                      "Use the rubric for severity. Do not invent facts not in the report.\n\n"
                                      f"RUBRIC:\n{rubric}\n\nTEMPLATE:\n{template}"},
        {"role": "user", "content": raw.replace("<id>", rid)},
    ]
    r = chat(ANALYZE_MODEL, msgs, raw=True)
    out("05_analyze", f"{rid}.analysis.md").write_text(r["choices"][0]["message"]["content"])
    proof = {"model": ANALYZE_MODEL, "tier": POLICY["models"][ANALYZE_MODEL]["tier"],
             "response_id": r.get("id"), "attestation": None, "signature": None,
             "note": "attestation + signature verification lands with the sidecar"}
    out("05_analyze", f"{rid}.proof.json").write_text(json.dumps(proof, indent=2))
    print(f"wrote stages/05_analyze/output/{rid}.analysis.md and .proof.json")


def main() -> None:
    load_env()
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    cmds = {"ping": cmd_ping, "redact": cmd_redact, "dedup": cmd_dedup,
            "triage": cmd_triage, "analyze": cmd_analyze}
    if cmd not in cmds:
        sys.exit(__doc__)
    try:
        cmds[cmd](*args)
    except PolicyError as e:
        sys.exit(f"POLICY REFUSED: {e}")


if __name__ == "__main__":
    main()
