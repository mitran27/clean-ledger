# privacy-rules.md - who may see what

Tiers (from the NEAR AI hackpack):
- `confidential` - NEAR's own GPUs in a TEE. Prompt and output hidden from everyone, NEAR included. May see RAW report text.
- `attested-3p` - a third-party TEE with its own proof. Failover only; may see RAW text only if policy says `allow_raw: true`.
- `unverified` - TEE status not confirmed (e.g. Jev, embeddings, rerank until a mentor confirms). REDACTED text only.
- `incognito` - provider servers; only the gateway is in a TEE. NEVER send report content.

Rules:
1. `_tools/call_model.py` refuses any call that breaks these rules. Do not bypass it.
2. "Redacted" means the file came from `stages/02_redact/output/`.
3. Only the model call is private. Files on this laptop are outside the TEE: keep `samples/` fake.
