"""Fernet (AES-128-CBC + HMAC-SHA256) encryption for stored API keys.

Generate a key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Set in .env:
    ENCRYPTION_KEY=<generated key>
"""
import os
from cryptography.fernet import Fernet


def get_fernet() -> Fernet:
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        # Generate a throwaway key for dev (keys won't survive restart)
        key = Fernet.generate_key().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_api_key(plaintext: str) -> bytes:
    if not plaintext:
        return b""
    return get_fernet().encrypt(plaintext.encode())


def decrypt_api_key(ciphertext: bytes | None) -> str:
    if not ciphertext:
        return ""
    try:
        return get_fernet().decrypt(ciphertext).decode()
    except Exception:
        return ""
