"""e2ee.py - client-side end-to-end encryption to an attested NEAR AI model key.

Protocol (docs.near.ai/cloud/guides/e2ee-chat-completions): the model's Ed25519 key, taken only
from a verified attestation report, is converted to X25519. Each message uses a fresh ephemeral
X25519 key, HKDF-SHA256 (info "ed25519_encryption") and XChaCha20-Poly1305.
Wire format, hex: [ephemeral pubkey 32][nonce 24][ciphertext + tag].
"""
from __future__ import annotations

import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.bindings import (crypto_aead_xchacha20poly1305_ietf_decrypt, crypto_aead_xchacha20poly1305_ietf_encrypt,
                           crypto_sign_ed25519_pk_to_curve25519, crypto_sign_ed25519_sk_to_curve25519)
from nacl.signing import SigningKey


def _kdf(shared: bytes) -> bytes:
    return HKDF(hashes.SHA256(), 32, None, b"ed25519_encryption").derive(shared)


class Session:
    """One client key pair, encrypting to one attested model key."""

    def __init__(self, model_ed25519_hex: str):
        self.model_ed_hex = model_ed25519_hex
        self.model_x = crypto_sign_ed25519_pk_to_curve25519(bytes.fromhex(model_ed25519_hex))
        sk = SigningKey.generate()
        self.client_pub_hex = bytes(sk.verify_key).hex()
        self.client_x_secret = crypto_sign_ed25519_sk_to_curve25519(bytes(sk) + bytes(sk.verify_key))

    def encrypt(self, text: str) -> str:
        eph = X25519PrivateKey.generate()
        key = _kdf(eph.exchange(X25519PublicKey.from_public_bytes(self.model_x)))
        nonce = secrets.token_bytes(24)
        ct = crypto_aead_xchacha20poly1305_ietf_encrypt(text.encode(), None, nonce, key)
        return (eph.public_key().public_bytes_raw() + nonce + ct).hex()

    def decrypt(self, hex_data: str) -> str:
        data = bytes.fromhex(hex_data)
        key = _kdf(X25519PrivateKey.from_private_bytes(self.client_x_secret).exchange(
            X25519PublicKey.from_public_bytes(data[:32])))
        return crypto_aead_xchacha20poly1305_ietf_decrypt(data[56:], None, data[32:56], key).decode()

    def headers(self, all_fields: bool = False) -> dict:
        h = {"X-Signing-Algo": "ed25519", "X-Client-Pub-Key": self.client_pub_hex,
             "X-Model-Pub-Key": self.model_ed_hex, "X-Encryption-Version": "2", "x-no-aliasing": "true"}
        if all_fields:
            h["X-Encrypt-All-Fields"] = "true"
        return h
