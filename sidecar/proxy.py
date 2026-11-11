"""Attestation sidecar: an OpenAI-compatible proxy in front of NEAR AI Cloud's TEE models.

Run from the workspace root:
  .venv/bin/uvicorn sidecar.proxy:app --port 8787

Per request it (1) refuses models that are not TEE-tier in _shared/policy.json,
(2) verifies the model's TEE attestation BEFORE any data leaves, (3) forwards with the
only copy of the API key, (4) verifies the response signature, (5) records a proof and
returns it in headers. The app talks to localhost and never needs the key.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sidecar"))
sys.path.insert(0, str(ROOT / "_tools"))
import attest  # noqa: E402
import call_model  # noqa: E402

PROOFS = ROOT / "sidecar" / "proofs.jsonl"
app = FastAPI(title="Clean Ledger attestation sidecar")
TEE_TIERS = {"confidential", "attested-3p"}


def key() -> str:
    call_model.load_env()
    k = os.environ.get("NEARAI_API_KEY", "")
    if not k.startswith("sk-"):
        raise HTTPException(500, "sidecar has no NEARAI_API_KEY")
    return k


def read_proofs() -> list[dict]:
    return [json.loads(l) for l in PROOFS.read_text().splitlines() if l] if PROOFS.exists() else []


@app.get("/health")
def health() -> dict:
    return {"ok": True, "attested_models": {m: {"verified": a["verified"], "expires_in": int(a["expires"] - time.time())}
                                            for m, a in attest._cache.items()}, "proofs": len(read_proofs())}


@app.get("/proofs/{chat_id}")
def proof(chat_id: str) -> dict:
    for p in read_proofs():
        if p["chat_id"] == chat_id:
            return p
    raise HTTPException(404, "no proof for that chat id")


E2EE_HEADERS = ("x-signing-algo", "x-client-pub-key", "x-model-pub-key", "x-encryption-version", "x-encrypt-all-fields")


@app.get("/attest")
def attest_model(model: str) -> dict:
    """Attest one model for the caller (used to pick an encryption key and to fail over safely)."""
    rule = call_model.POLICY["models"].get(model)
    if not rule or rule["tier"] not in TEE_TIERS:
        raise HTTPException(403, f"{model}: not a TEE-tier model in policy")
    a = attest.verify_model(model, key())
    return {k: a[k] for k in ("model", "verified", "signing_addresses", "jti", "tcb_status", "gpu_ok", "expires", "checks")}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Response:
    # the upstream call can take minutes: run it off the event loop so /health stays responsive
    hdrs = {k: request.headers[k] for k in E2EE_HEADERS if k in request.headers}
    return await run_in_threadpool(handle, await request.body(), hdrs)


def handle(body: bytes, hdrs: dict | None = None) -> Response:
    hdrs = hdrs or {}
    try:
        model = json.loads(body)["model"]
    except (ValueError, KeyError):
        raise HTTPException(400, "body must be JSON with a model")
    rule = call_model.POLICY["models"].get(model)
    if not rule or rule["tier"] not in TEE_TIERS:
        raise HTTPException(403, f"{model}: not a TEE-tier model in policy; sidecar will not carry customer data to it")
    k = key()
    att = attest.verify_model(model, k)
    if not att["verified"]:
        return JSONResponse({"error": "attestation failed; nothing was sent", "checks": att["checks"]}, status_code=412)
    pinned = hdrs.get("x-model-pub-key")
    if pinned and pinned not in att["signing_addresses"]:  # encryption must target a hardware-bound key
        return JSONResponse({"error": "pinned model key is not an attested key for this model; nothing was sent"},
                            status_code=412)
    req = urllib.request.Request(attest.BASE + "/chat/completions", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {k}")
    req.add_header("Content-Type", "application/json")
    req.add_header("x-no-aliasing", "true")  # the gateway may not silently swap the model
    for name, value in hdrs.items():
        req.add_header(name, value)
    for attempt in range(3):  # a reset connection or 5xx is retried; a 4xx is returned as is
        try:
            with urllib.request.urlopen(req, timeout=420) as r:
                resp_bytes = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return Response(e.read(), status_code=e.code, media_type="application/json")
        except OSError as e:  # connection reset, timeout, DNS (URLError is an OSError too)
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            return JSONResponse({"error": f"upstream unreachable after 3 tries: {e}"}, status_code=502)
    chat_id = json.loads(resp_bytes).get("id", "")
    sig = attest.verify_signature(chat_id, model, k, body, resp_bytes)
    if not sig["ok"]:
        return JSONResponse({"error": "response signature invalid; response dropped", "checks": sig["checks"]}, status_code=502)
    record = {"ts": int(time.time()), "chat_id": chat_id, "model": model, "tier": rule["tier"],
              "attestation_jti": att["jti"], "tcb_status": att["tcb_status"], "gpu_ok": att["gpu_ok"],
              "attestation_checks": att["checks"], "signature_checks": sig["checks"],
              "signing_address": sig["signing_address"], "signed_text": sig["signed_text"],
              "request_hash_matches": sig["request_hash_matches"], "response_hash_matches": sig["response_hash_matches"]}
    with PROOFS.open("a") as f:
        f.write(json.dumps(record) + "\n")
    return Response(resp_bytes, media_type="application/json", headers={
        "X-Attestation-Verified": "true", "X-Attestation-Jti": str(att["jti"]), "X-Signature-Valid": "true",
        "X-Chat-Id": chat_id, "X-Signing-Address": sig["signing_address"],
        # passed through so the caller can re-verify the signature itself (signed-tool gate)
        "X-Signed-Text": sig["signed_text"], "X-Signature": sig["signature"]})
