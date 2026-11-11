"""forge_demo.py - show the signed-tool gate refusing forged tool calls.

One real call to the TEE model (through the sidecar) asks it to call a tool. Then the gate
checks four versions of that response:
  1. genuine                     -> tool may run
  2. tool argument changed       -> refused (response bytes no longer match what the TEE signed)
  3. extra tool call injected    -> refused
  4. signature forged            -> refused

Usage (sidecar running):  .venv/bin/python _tools/forge_demo.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import call_model  # noqa: E402
import proofchain  # noqa: E402
from agent import TOOL_SCHEMAS  # noqa: E402


def signed_call() -> tuple[bytes, dict]:
    call_model.load_env()
    base = os.environ.get("SIDECAR_URL") or sys.exit("Set SIDECAR_URL and start the sidecar (./run.sh).")
    body = {"model": call_model.AGENT_MODEL, "tool_choice": "auto", "tools": TOOL_SCHEMAS,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": "Call query_transactions for account ACC-M1, direction in."}]}
    sent = json.dumps(body).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=sent, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=480) as r:
        got, h = r.read(), r.headers
    proof = {"signing_address": h["X-Signing-Address"], "signature": h["X-Signature"],
             "signed_text": h["X-Signed-Text"], "request_sha256": hashlib.sha256(sent).hexdigest()}
    return got, proof


def check(label: str, raw: bytes, proof: dict) -> None:
    p = {**proof, "response_sha256": hashlib.sha256(raw).hexdigest()}
    problems = proofchain.verify_step(p)
    calls = json.loads(raw)["choices"][0]["message"].get("tool_calls") or []
    shown = ", ".join(f"{c['function']['name']}({c['function']['arguments']})" for c in calls) or "no tool call"
    verdict = "RUNS   " if not problems else "REFUSED"
    print(f"{verdict} {label:30} {shown[:90]}")
    for pr in problems:
        print(f"          - {pr}")


def main() -> None:
    raw, proof = signed_call()
    msg = json.loads(raw)["choices"][0]["message"]
    if not msg.get("tool_calls"):
        sys.exit("The model answered without a tool call this time; run again.")
    check("1 genuine TEE response", raw, proof)

    d = json.loads(raw)
    tc = d["choices"][0]["message"]["tool_calls"][0]["function"]
    tc["arguments"] = tc["arguments"].replace("ACC-M1", "ACC-X1")
    check("2 tool argument changed", json.dumps(d).encode(), proof)

    d = json.loads(raw)
    d["choices"][0]["message"]["tool_calls"].append(
        {"id": "forged", "type": "function", "function": {"name": "query_transactions",
                                                           "arguments": json.dumps({"account": "ACC-D1"})}})
    check("3 extra tool call injected", json.dumps(d).encode(), proof)

    forged = {**proof, "signature": ("00" if proof["signature"][:2] != "00" else "11") + proof["signature"][2:]}
    check("4 signature forged", raw, forged)


if __name__ == "__main__":
    main()
