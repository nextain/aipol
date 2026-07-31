"""Fail-closed Ed25519 JWS verification for calculator completion receipts."""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import time
from typing import Any

from policy_lab.domains.pension.experiment import ExperimentError


_CANONICAL_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


def _decode_segment(
    value: object,
    label: str,
    *,
    maximum: int = 8192,
    canonical_jws: bool = True,
) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ExperimentError(f"receipt {label} 형식이 올바르지 않습니다")
    if canonical_jws and not _CANONICAL_BASE64URL.fullmatch(value):
        raise ExperimentError(f"receipt {label} must be unpadded canonical base64url")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ExperimentError(f"receipt {label} base64url 형식이 올바르지 않습니다") from exc
    if canonical_jws:
        encoded = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(encoded, value):
            raise ExperimentError(f"receipt {label} is not canonical base64url")
    return decoded


def _json_segment(value: object, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(_decode_segment(value, label))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExperimentError(f"receipt {label} JSON 형식이 올바르지 않습니다") from exc
    if not isinstance(parsed, dict):
        raise ExperimentError(f"receipt {label}는 JSON 객체여야 합니다")
    return parsed


class Ed25519JwsReceiptVerifier:
    """Verify flattened JWS JSON serialization using one pinned Ed25519 key."""

    def __init__(
        self,
        public_key_b64: str,
        key_id: str,
        *,
        max_ttl_seconds: int = 600,
        expected_issuer: str = "",
        expected_audience: str = "",
    ) -> None:
        if not key_id.strip():
            raise RuntimeError("AIPOL_RECEIPT_KEY_ID is required")
        try:
            raw_key = _decode_segment(
                public_key_b64, "public key", maximum=128, canonical_jws=False
            )
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            self._public_key = Ed25519PublicKey.from_public_bytes(raw_key)
        except (ImportError, ValueError, ExperimentError) as exc:
            raise RuntimeError("AIPOL receipt Ed25519 public key is invalid") from exc
        self.key_id = key_id.strip()
        self.max_ttl_seconds = min(3600, max(30, int(max_ttl_seconds)))
        self.expected_issuer = expected_issuer.strip()
        self.expected_audience = expected_audience.strip()
        self.verifier_id = f"ed25519-jws:{self.key_id}"

    def verify(self, receipt: dict, contract: dict, context: dict) -> str:
        if contract.get("receipt_format") != "flattened_jws_json" or contract.get("signature_algorithm") != "EdDSA":
            raise ExperimentError("receipt 계약의 서명 형식 또는 알고리즘이 지원되지 않습니다")
        if not isinstance(receipt, dict) or set(receipt) != {"protected", "payload", "signature"}:
            raise ExperimentError("receipt JWS는 protected, payload, signature만 포함해야 합니다")
        protected_raw = receipt.get("protected")
        payload_raw = receipt.get("payload")
        signature = _decode_segment(receipt.get("signature"), "signature", maximum=256)
        protected = _json_segment(protected_raw, "protected")
        payload = _json_segment(payload_raw, "payload")
        if set(protected) != {"alg", "kid", "typ"}:
            raise ExperimentError("receipt protected header fields do not match the contract")
        if protected.get("alg") != "EdDSA" or protected.get("typ") != "JWT":
            raise ExperimentError("receipt JWS는 alg=EdDSA, typ=JWT여야 합니다")
        contract_key = str(contract.get("public_key_id") or "")
        if protected.get("kid") != self.key_id or contract_key != self.key_id:
            raise ExperimentError("receipt 서명 키가 동결 계약과 일치하지 않습니다")
        if self.expected_issuer and contract.get("issuer") != self.expected_issuer:
            raise ExperimentError("receipt issuer is not allowed by deployment configuration")
        if self.expected_audience and contract.get("audience") != self.expected_audience:
            raise ExperimentError("receipt audience is not allowed by deployment configuration")
        try:
            signing_input = f"{protected_raw}.{payload_raw}".encode("ascii")
            self._public_key.verify(signature, signing_input)
        except Exception as exc:
            raise ExperimentError("receipt 서명이 유효하지 않습니다") from exc

        now = int(time.time())
        try:
            issued_at, expires_at = int(payload["iat"]), int(payload["exp"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExperimentError("receipt iat/exp가 필요합니다") from exc
        ttl = expires_at - issued_at
        if issued_at > now or expires_at <= now or ttl <= 0 or ttl > self.max_ttl_seconds:
            raise ExperimentError("receipt 발급·만료 시간이 허용 범위를 벗어났습니다")
        audience = payload.get("aud")
        expected_audience = str(contract.get("audience") or "")
        audiences = audience if isinstance(audience, list) else [audience]
        if expected_audience not in audiences:
            raise ExperimentError("receipt audience가 동결 계약과 일치하지 않습니다")
        if payload.get("iss") != contract.get("issuer"):
            raise ExperimentError("receipt issuer가 동결 계약과 일치하지 않습니다")

        required_context = (
            "experiment_id", "experiment_version", "session_id", "participant_pseudonym",
            "artifact_id", "artifact_hash", "contract_hash",
        )
        if any(payload.get(key) != context.get(key) for key in required_context):
            raise ExperimentError("receipt 참가자·실험·계약 binding이 현재 요청과 일치하지 않습니다")
        receipt_id = payload.get("jti")
        if not isinstance(receipt_id, str) or not 8 <= len(receipt_id) <= 256:
            raise ExperimentError("receipt jti가 필요합니다")
        return receipt_id


def verifier_from_environment() -> Ed25519JwsReceiptVerifier | None:
    mode = os.environ.get("AIPOL_RECEIPT_VERIFIER_MODE", "disabled").strip().lower()
    if mode in {"", "disabled"}:
        return None
    if mode != "ed25519_jws":
        raise RuntimeError("AIPOL_RECEIPT_VERIFIER_MODE must be disabled or ed25519_jws")
    public_key = os.environ.get("AIPOL_RECEIPT_ED25519_PUBLIC_KEY_B64", "").strip()
    key_id = os.environ.get("AIPOL_RECEIPT_KEY_ID", "").strip()
    if not public_key or not key_id:
        raise RuntimeError("ed25519_jws receipt verification requires public key and key id")
    return Ed25519JwsReceiptVerifier(
        public_key,
        key_id,
        max_ttl_seconds=int(os.environ.get("AIPOL_RECEIPT_MAX_TTL_SECONDS", "600")),
        expected_issuer=os.environ.get("AIPOL_RECEIPT_EXPECTED_ISSUER", ""),
        expected_audience=os.environ.get("AIPOL_RECEIPT_EXPECTED_AUDIENCE", ""),
    )
