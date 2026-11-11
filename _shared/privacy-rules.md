# privacy-rules.md - who may see what

Tiers (from the NEAR AI hackpack):
- `confidential` - NEAR's own GPUs in a TEE. Hidden from everyone, NEAR included. May see customer names and raw transactions.
- `attested-3p` - a third-party TEE with its own proof. Failover only; raw data only if `allow_raw: true`.
- `unverified` - TEE status not confirmed (Jev, embeddings, rerank until a mentor confirms). Pseudonymous features only: account ids, amounts, counts. No names.
- `incognito` - provider servers; only the gateway is in a TEE. NEVER send customer data.

Rules:
1. `_tools/call_model.py` refuses any call that breaks these rules. Do not bypass it.
2. Only the model call is private. Files on this laptop sit outside the TEE: keep `samples/` synthetic.
