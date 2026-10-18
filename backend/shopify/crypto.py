"""Encrypt Shopify tokens before they are written to the database (Fernet: AES-128-CBC + HMAC)."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


class TokenKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise TokenKeyMissing("TOKEN_ENCRYPTION_KEY is not set. Generate one with: "
                              "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    return Fernet(key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError("stored token could not be decrypted (wrong TOKEN_ENCRYPTION_KEY?)") from e
