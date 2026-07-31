"""운영 환경에서 JSON 비밀값을 안전하게 읽는 보조 함수."""

from __future__ import annotations

import base64
import binascii
import os


def text(name: str) -> str:
    """평문 환경 변수를 우선하고, 없으면 ``<NAME>_B64``를 엄격히 복호화한다."""

    raw = os.environ.get(name, "").strip()
    if raw:
        return raw
    encoded_name = f"{name}_B64"
    encoded = os.environ.get(encoded_name, "").strip()
    if not encoded:
        return ""
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError(f"{encoded_name} must be valid base64-encoded UTF-8") from exc
    if not decoded.strip():
        raise ValueError(f"{encoded_name} must not decode to an empty value")
    return decoded.strip()
