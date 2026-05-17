"""Tokens firmados (HMAC SHA-256) para magic links — sin DB.

El token codifica {email, exp} en base64 url-safe + una firma HMAC.
Es validable stateless: cualquier instancia que tenga JWT_SECRET puede
firmar/verificar.

Formato del token: base64url(payload).hex(signature)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _get_secret() -> bytes:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("Falta JWT_SECRET en env vars / Streamlit secrets")
    return secret.encode("utf-8")


def sign_token(email: str, ttl_seconds: int = 900) -> str:
    """Genera un token con email + expiry. Default TTL: 15 min."""
    payload = {"email": email.lower().strip(), "exp": int(time.time()) + ttl_seconds}
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64encode(payload_bytes)
    sig = hmac.new(_get_secret(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_token(token: str) -> dict[str, Any] | None:
    """Devuelve el payload si el token es valido y no expiro. None si invalido."""
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_get_secret(), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(_b64decode(payload_b64))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload
