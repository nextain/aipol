from __future__ import annotations

import base64
import sys
from pathlib import Path

EVENT_TOOL = Path(__file__).resolve().parents[1] / "event-tool"
sys.path.insert(0, str(EVENT_TOOL))

import admin_auth  # noqa: E402


def test_scrypt_password_round_trip_and_plaintext_boundary() -> None:
    encoded = admin_auth.hash_password("correct-horse-battery-staple", salt=b"0123456789abcdef")
    assert admin_auth.password_is_hashed(encoded)
    assert admin_auth.verify_password("correct-horse-battery-staple", encoded)
    assert not admin_auth.verify_password("wrong-password-value", encoded)
    assert not admin_auth.verify_password("development-password", "development-password")
    assert admin_auth.verify_password("development-password", "development-password", allow_plaintext=True)


def test_totp_matches_rfc6238_sha1_vector_truncated_to_six_digits() -> None:
    secret = base64.b32encode(b"12345678901234567890").decode("ascii")
    assert admin_auth.totp(secret, at_epoch=59) == "287082"
    assert admin_auth.verify_totp(secret, "287082", at_epoch=59)
    assert admin_auth.matching_totp_counter(secret, "287082", at_epoch=59) == 1
    assert admin_auth.verify_totp(secret, admin_auth.totp(secret, at_epoch=29), at_epoch=59)
    assert admin_auth.matching_totp_counter(secret, admin_auth.totp(secret, at_epoch=29), at_epoch=59) == 0
    assert not admin_auth.verify_totp(secret, "000000", at_epoch=59)
