from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


def _master_key() -> bytes:
    raw = get_settings().aes_master_key
    try:
        key = base64.b64decode(raw)
    except Exception as exc:
        raise RuntimeError("AES_MASTER_KEY must be base64-encoded") from exc
    if len(key) != 32:
        raise RuntimeError("AES_MASTER_KEY must decode to exactly 32 bytes")
    return key


def encrypt(plaintext: str) -> str:
    """AES-256-GCM encrypt → base64(nonce|ct|tag). Used for broker keys at rest."""
    aes = AESGCM(_master_key())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str) -> str:
    blob = base64.b64decode(token)
    nonce, ct = blob[:12], blob[12:]
    aes = AESGCM(_master_key())
    return aes.decrypt(nonce, ct, None).decode("utf-8")
