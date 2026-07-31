"""운영 관리자 비밀번호와 TOTP 다중 인증 검증."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time


PASSWORD_SCHEME = "scrypt-v1"
SCRYPT_N = 1 << 15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 16:
        raise ValueError("password must contain at least 16 characters")
    actual_salt = salt or secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=actual_salt, n=SCRYPT_N,
                            r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES, maxmem=64 * 1024 * 1024)
    return "$".join((PASSWORD_SCHEME, str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
                     base64.urlsafe_b64encode(actual_salt).decode("ascii").rstrip("="),
                     base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")))


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def password_is_hashed(value: str) -> bool:
    return value.startswith(f"{PASSWORD_SCHEME}$")


def verify_password(password: str, encoded: str, *, allow_plaintext: bool = False) -> bool:
    if not password_is_hashed(encoded):
        return allow_plaintext and secrets.compare_digest(password, encoded)
    try:
        scheme, n, r, p, salt, expected = encoded.split("$", 5)
        params = int(n), int(r), int(p)
        if scheme != PASSWORD_SCHEME or params != (SCRYPT_N, SCRYPT_R, SCRYPT_P):
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=_b64decode(salt),
                                n=params[0], r=params[1], p=params[2], dklen=KEY_BYTES,
                                maxmem=64 * 1024 * 1024)
        return secrets.compare_digest(actual, _b64decode(expected))
    except (ValueError, TypeError):
        return False


def normalize_totp_secret(value: str) -> str:
    normalized = "".join(value.split()).upper().rstrip("=")
    try:
        decoded = base64.b32decode(normalized + "=" * (-len(normalized) % 8), casefold=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("TOTP secret must be valid base32") from exc
    if len(decoded) < 20:
        raise ValueError("TOTP secret must contain at least 160 bits")
    return normalized


def totp(secret: str, *, at_epoch: int | None = None, step_seconds: int = 30) -> str:
    normalized = normalize_totp_secret(secret)
    key = base64.b32decode(normalized + "=" * (-len(normalized) % 8))
    counter = int(time.time() if at_epoch is None else at_epoch) // step_seconds
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % 1_000_000:06d}"


def matching_totp_counter(
    secret: str, code: str, *, at_epoch: int | None = None, window: int = 1,
    step_seconds: int = 30,
) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    now = int(time.time() if at_epoch is None else at_epoch)
    current = now // step_seconds
    for offset in range(-window, window + 1):
        counter = current + offset
        if counter >= 0 and secrets.compare_digest(
            totp(secret, at_epoch=counter * step_seconds, step_seconds=step_seconds), code
        ):
            return counter
    return None


def verify_totp(secret: str, code: str, *, at_epoch: int | None = None, window: int = 1) -> bool:
    return matching_totp_counter(secret, code, at_epoch=at_epoch, window=window) is not None
