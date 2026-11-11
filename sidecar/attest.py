"""attest.py - verify NEAR AI Cloud TEE attestation and response signatures.

Trust chain checked here:
  1. Intel Trust Authority (ITA) JWT for the model's CPU+GPU TEE: Intel signature (JWKS),
     expiry, our fresh nonce echoed inside the signed claims, TDX TCB status, debug off,
     NVIDIA GPU attestation passed.
  2. The model's attestation report: its TDX quote embeds the signing key (and our nonce)
     in report_data, so the key is hardware-bound.
  3. Each response signature (ed25519) verifies under that key; the signed text carries
     the model id and the request/response hashes, which we recompute from the bytes.

NOT verified here: that the quote in step 2 is itself Intel-signed (needs DCAP or a second
ITA call on that exact quote). Step 1 covers the same platform through Intel.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jwt import PyJWKClient

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "_shared" / "policy.json").read_text())
ATT = POLICY.get("attestation", {})
BASE = POLICY["base_url"].rstrip("/")

_jwks: dict[str, PyJWKClient] = {}
_cache: dict[str, dict] = {}


def _get(path: str, key: str | None = None) -> dict:
    req = urllib.request.Request(BASE + path)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _check(checks: list, name: str, ok: bool, detail: str = "") -> bool:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    return bool(ok)


def _decode_jwt(token: str, jwks_url: str) -> dict:
    client = _jwks.setdefault(jwks_url, PyJWKClient(jwks_url, cache_keys=True))
    key = client.get_signing_key_from_jwt(token).key
    return jwt.decode(token, key, algorithms=["PS384", "RS256", "ES384"],
                      options={"verify_aud": False}, leeway=10)


def _maybe_json(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return {}
    return v or {}


def quote_report_data(quote_hex: str) -> bytes:
    """report_data (64 bytes) from a TDX v4 quote: 48-byte header, then the TD report body."""
    q = bytes.fromhex(quote_hex)
    if int.from_bytes(q[0:2], "little") != 4 or int.from_bytes(q[4:8], "little") != 0x81:
        raise ValueError("not a TDX v4 quote")
    return q[48 + 520: 48 + 584]


def verify_model(model: str, key: str | None = None, force: bool = False) -> dict:
    """Attest the TEE that serves `model`. Cached until shortly before the ITA token expires."""
    hit = _cache.get(model)
    if hit and not force and hit["expires"] - time.time() > 30:
        return hit
    checks: list = []
    nonce = os.urandom(32).hex()
    try:
        ita = _get(f"/attestation/ita-token?model={urllib.parse.quote(model)}&nonce={nonce}")
    except Exception as e:  # no Intel-signed evidence for this model: fail closed, never crash
        _check(checks, "Intel Trust Authority token available", False, str(e)[:120])
        out = {"model": model, "verified": False, "checks": checks, "signing_addresses": [], "jti": None,
               "tcb_status": None, "gpu_ok": False, "fetched_at": int(time.time()), "expires": time.time() + 60}
        _cache[model] = out
        return out
    tokens = [("gateway", ita["gateway"]["token"])]
    mt = next((m for m in ita["models"] if m["model"] == model), ita["models"][0] if ita["models"] else None)
    if mt:
        tokens.append(("model", mt["token"]))
    claims, expires = {}, time.time() + 300
    for who, tok in tokens:
        try:
            claims[who] = _decode_jwt(tok, ita["jwks_url"])
            expires = min(expires, claims[who]["exp"])
            _check(checks, f"ITA {who} token signed by Intel", True, f"iss {claims[who]['iss']}, alg PS384, not expired")
        except Exception as e:  # signature, expiry, network
            _check(checks, f"ITA {who} token signed by Intel", False, str(e)[:120])
    allowed = ATT.get("allowed_tcb_status", ["UpToDate"])
    for who, c in claims.items():
        tdx = c.get("tdx", {})
        rt = _maybe_json(tdx.get("attester_runtime_data"))
        _check(checks, f"{who}: fresh nonce echoed in signed claims", rt.get("caller_nonce") == nonce)
        _check(checks, f"{who}: Intel TDX platform up to date", tdx.get("attester_tcb_status") in allowed,
               f"TCB {tdx.get('attester_tcb_status')}")
        _check(checks, f"{who}: TDX debug disabled",
               tdx.get("dbgstat") == "disabled" and tdx.get("tdx_is_debuggable") is False)
    gpu = claims.get("model", {}).get("nvgpu")
    if ATT.get("require_gpu", True):
        details = _maybe_json((gpu or {}).get("claim_details"))
        gpu_ok = bool(gpu) and gpu.get("x-nvidia-overall-att-result") is True and \
            all(g.get("dbgstat") == "disabled" for g in details.values() if isinstance(g, dict))
        _check(checks, "NVIDIA GPU attestation passed, debug off", gpu_ok,
               f"{len(details)} GPU(s)" if gpu else "no GPU claims")
    addresses: list[str] = []
    try:
        n2 = os.urandom(32).hex()
        rep = _get(f"/attestation/report?model={urllib.parse.quote(model)}&nonce={n2}&signing_algo=ed25519", key)
        for a in rep.get("model_attestations", []):
            rd = quote_report_data(a["intel_quote"])
            bound = rd[:32] == bytes.fromhex(a["signing_address"]) and rd[32:64] == bytes.fromhex(n2)
            if _check(checks, "signing key bound in the TDX quote", bound, f"key {a['signing_address'][:16]}…"):
                addresses.append(a["signing_address"])
    except Exception as e:
        _check(checks, "signing key bound in the TDX quote", False, str(e)[:120])
    verified = bool(checks) and all(c["ok"] for c in checks)
    out = {"model": model, "verified": verified, "checks": checks, "signing_addresses": addresses,
           "jti": (claims.get("model") or claims.get("gateway") or {}).get("jti"),
           "tcb_status": claims.get("model", {}).get("tdx", {}).get("attester_tcb_status"),
           "gpu_ok": bool(gpu and gpu.get("x-nvidia-overall-att-result") is True),
           "fetched_at": int(time.time()), "expires": expires}
    _cache[model] = out
    return out


def verify_signature(chat_id: str, model: str, key: str, request_bytes: bytes, response_bytes: bytes) -> dict:
    """Check the TEE's ed25519 signature over `model:request_hash:response_hash`."""
    checks: list = []
    sig = _get(f"/signature/{urllib.parse.quote(chat_id)}?model={urllib.parse.quote(model)}&signing_algo=ed25519", key)
    text = sig["text"]
    _check(checks, "signed inside the model TEE (provider_tee)", sig.get("signature_kind") == "provider_tee",
           str(sig.get("signature_kind")))
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(sig["signing_address"])).verify(
            bytes.fromhex(sig["signature"]), text.encode())
        ok = True
    except (InvalidSignature, ValueError):
        ok = False
    _check(checks, "ed25519 signature valid", ok)
    att = _cache.get(model) or {}
    _check(checks, "signing key is the attested key", sig["signing_address"] in att.get("signing_addresses", []),
           f"key {sig['signing_address'][:16]}…")
    signed_model, req_h, resp_h = text.rsplit(":", 2)
    _check(checks, "signed model id matches", signed_model == model, signed_model)
    req_ok = req_h == hashlib.sha256(request_bytes).hexdigest()
    resp_ok = resp_h == hashlib.sha256(response_bytes).hexdigest()
    return {"chat_id": chat_id, "ok": all(c["ok"] for c in checks), "checks": checks,
            "signing_address": sig["signing_address"], "signature": sig["signature"], "request_hash_matches": req_ok,
            "response_hash_matches": resp_ok, "signed_text": text}
