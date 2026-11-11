"""call_model.py - the only way this workspace calls NEAR AI Cloud.

Enforces _shared/policy.json: customer-identifying data only goes to tier
"confidential" models with allow_raw=true. The API key is read from .env and
never printed. Import it as a library, or run:
  python _tools/call_model.py ping
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
AGENT_MODEL = "z-ai/glm-5.3-flash"
SCREEN_MODEL = "typesafe/jev-1.13"


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
    load_env()
    key = os.environ.get("NEARAI_API_KEY", "")
    if not key.startswith("sk-"):
        sys.exit("NEARAI_API_KEY missing or malformed in .env (value not shown).")
    return key


def check_policy(model: str, raw: bool) -> None:
    rule = POLICY["models"].get(model)
    if rule is None:
        raise PolicyError(f"{model}: not in _shared/policy.json (default deny)")
    if rule["tier"] == "incognito":
        raise PolicyError(f"{model}: incognito tier never receives customer data")
    if raw and not (rule["tier"] == "confidential" and rule.get("allow_raw")):
        raise PolicyError(f"{model}: tier {rule['tier']} may not see customer-identifying data")


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
    """POST /chat/completions after the privacy check. `raw` = contains customer identity."""
    check_policy(model, raw)
    body = {"model": model, "messages": messages, **extra}
    if model.startswith("z-ai/"):
        body.setdefault("chat_template_kwargs", {"enable_thinking": False})
    return request("POST", "/chat/completions", body)


if __name__ == "__main__":
    if sys.argv[1:] != ["ping"]:
        sys.exit(__doc__)
    try:
        r = chat(AGENT_MODEL, [{"role": "user", "content": "Say hello in one sentence."}], raw=False)
    except PolicyError as e:
        sys.exit(f"POLICY REFUSED: {e}")
    print(r["choices"][0]["message"]["content"])
