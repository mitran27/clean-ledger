"""call_model.py - the only way this workspace calls NEAR AI Cloud.

Enforces _shared/policy.json: customer-identifying data only goes to tier
"confidential" models with allow_raw=true. The API key is read from .env and
never printed. Import it as a library, or run:
  python _tools/call_model.py ping
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
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
            if not os.environ.get(k.strip()):  # also replaces a value that was empty at first load
                os.environ[k.strip()] = v.strip()


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
    last = None
    for attempt in range(3):  # slow TEE responses and 5xx are retried; 4xx are not
        try:
            with urllib.request.urlopen(req, timeout=420) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < 2:
                last = e
                time.sleep(2 * (attempt + 1))
                continue
            detail = e.read().decode(errors="replace")[:500]
            raise SystemExit(f"HTTP {e.code} on {method} {path}: {detail}")
        except (TimeoutError, urllib.error.URLError) as e:
            last = e
    raise SystemExit(f"NEAR AI request failed after 3 tries on {method} {path}: {last}")


def chat(model: str, messages: list[dict], raw: bool, **extra) -> dict:
    """POST /chat/completions after the privacy check. `raw` = contains customer identity."""
    check_policy(model, raw)
    body = {"model": model, "messages": messages, **extra}
    if model.startswith("z-ai/"):
        body.setdefault("chat_template_kwargs", {"enable_thinking": False})
    load_env()
    sidecar = os.environ.get("SIDECAR_URL")
    if sidecar and POLICY["models"][model]["tier"] in ("confidential", "attested-3p"):
        return via_sidecar(sidecar, body)  # fail closed: never fall back to a direct call
    return request("POST", "/chat/completions", body)


class AttestedModelUnavailable(Exception):
    pass


_breaker: dict[str, tuple[int, float]] = {}  # model -> (consecutive failures, open until)
_attest_cache: dict[str, dict] = {}


def _attest(base: str, model: str) -> dict:
    hit = _attest_cache.get(model)
    if hit and hit["expires"] - time.time() > 30:
        return hit
    root = base.rsplit("/v1", 1)[0]
    try:
        with urllib.request.urlopen(f"{root}/attest?model={urllib.parse.quote(model)}", timeout=60) as r:
            a = json.loads(r.read())
    except (urllib.error.URLError, TimeoutError) as e:
        raise AttestedModelUnavailable(f"attestation unavailable: {e}")
    if not a.get("verified") or not a.get("signing_addresses"):
        raise AttestedModelUnavailable("attestation did not verify")
    _attest_cache[model] = a
    return a


def to_wire(messages: list[dict], session) -> list[dict]:
    """Encrypt every message to the attested model key. NEAR's E2EE path rejects role 'tool'
    messages, so tool calls and results are relayed as encrypted assistant/user text."""
    calls, out = {}, []
    for m in messages:
        role = m["role"]
        if role in ("system", "user"):
            out.append({"role": role, "content": session.encrypt(m["content"])})
        elif role == "assistant":
            text = m.get("content") or ""
            for tc in m.get("tool_calls") or []:
                call = f'{tc["function"]["name"]}({tc["function"]["arguments"]})'
                calls[tc["id"]] = call
                text += f"\n[called {call}]"
            out.append({"role": "assistant", "content": session.encrypt(text.strip() or "(no text)")})
        elif role == "tool":
            out.append({"role": "user", "content": session.encrypt(
                f"Result of {calls.get(m.get('tool_call_id'), 'the tool call')}:\n{m['content']}")})
    return out


def _decrypt_message(msg: dict, session, all_fields: bool) -> None:
    def dec(v):
        try:
            return session.decrypt(v)
        except Exception:
            return v
    for f in ("content", "reasoning_content", "reasoning"):
        if msg.get(f):
            msg[f] = dec(msg[f])
    for tc in msg.get("tool_calls") or []:
        if all_fields:
            tc["function"]["name"] = dec(tc["function"]["name"])
            tc["function"]["arguments"] = dec(tc["function"]["arguments"])


def secure_chat(messages: list[dict], tools: list | None = None, models: list[str] | None = None,
                all_fields: bool = True, **extra) -> dict:
    """End-to-end encrypted chat through the sidecar, failing over only to other attested
    TEE models. Each model gets its own attested key; a model that fails twice is skipped
    for 60 s (circuit breaker)."""
    sys.path.insert(0, str(ROOT / "sidecar"))
    import e2ee  # needs PyNaCl: run with .venv/bin/python
    load_env()
    base = os.environ.get("SIDECAR_URL") or sys.exit("End-to-end encrypted chat needs the sidecar (SIDECAR_URL).")
    errors = []
    for model in models or POLICY.get("failover_pool", [AGENT_MODEL]):
        fails, until = _breaker.get(model, (0, 0.0))
        if until > time.time():
            errors.append(f"{model}: circuit open")
            continue
        try:
            check_policy(model, raw=True)
            att = _attest(base, model)
            s = e2ee.Session(att["signing_addresses"][0])
            body = {"model": model, "messages": to_wire(messages, s), **extra}
            if tools:
                body["tools"] = tools
                body.setdefault("tool_choice", "auto")
            if model.startswith(("z-ai/", "Qwen/")):  # otherwise the answer can be spent on reasoning
                body.setdefault("chat_template_kwargs", {"enable_thinking": False})
            resp = via_sidecar(base, body, s.headers(all_fields))
            _decrypt_message(resp["choices"][0]["message"], s, all_fields)
            resp["_model"], resp["_e2ee"] = model, True
            _breaker.pop(model, None)
            return resp
        except (AttestedModelUnavailable, PolicyError, SystemExit) as e:
            fails += 1
            _breaker[model] = (fails, time.time() + 60 if fails >= 2 else 0.0)
            errors.append(f"{model}: {str(e)[:160]}")
    raise SystemExit("No attested model answered: " + " | ".join(errors))


def via_sidecar(base: str, body: dict, headers: dict | None = None) -> dict:
    """TEE chat through the attestation sidecar. The sidecar holds the key and verifies the TEE
    before sending and the signature after receiving; this process never needs the key."""
    sent = json.dumps(body).encode()
    req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=sent, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=480) as r:
            got, h = r.read(), r.headers
            resp = json.loads(got)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Sidecar refused ({e.code}): {e.read().decode(errors='replace')[:400]}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(f"Sidecar unreachable at {base} ({e}). Start it with ./run.sh; refusing to send around it.")
    resp["_proof"] = {"verified": h.get("X-Attestation-Verified") == "true" and h.get("X-Signature-Valid") == "true",
                      "attestation_jti": h.get("X-Attestation-Jti"), "chat_id": h.get("X-Chat-Id"),
                      "signing_address": h.get("X-Signing-Address"),
                      "signed_text": h.get("X-Signed-Text"), "signature": h.get("X-Signature"),
                      # hashes of the exact bytes THIS process sent and received, checked by the gate
                      "request_sha256": hashlib.sha256(sent).hexdigest(),
                      "response_sha256": hashlib.sha256(got).hexdigest()}
    return resp


if __name__ == "__main__":
    if sys.argv[1:] != ["ping"]:
        sys.exit(__doc__)
    try:
        r = chat(AGENT_MODEL, [{"role": "user", "content": "Say hello in one sentence."}], raw=False)
    except PolicyError as e:
        sys.exit(f"POLICY REFUSED: {e}")
    print(r["choices"][0]["message"]["content"])
