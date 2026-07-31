from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).parents[1]
EVENT_TOOL = ROOT / "event-tool"
sys.path.insert(0, str(EVENT_TOOL))

from aipol_receipt import Ed25519JwsReceiptVerifier, verifier_from_environment  # noqa: E402
from policy_lab.domains.pension.experiment import ExperimentError  # noqa: E402


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _receipt(
    private_key: Ed25519PrivateKey,
    payload: dict,
    *,
    kid: str = "calculator-key-1",
    protected_header: dict | None = None,
) -> dict:
    protected = _b64(json.dumps(
        protected_header or {"alg": "EdDSA", "typ": "JWT", "kid": kid},
        separators=(",", ":"), sort_keys=True,
    ).encode())
    encoded_payload = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = private_key.sign(f"{protected}.{encoded_payload}".encode("ascii"))
    return {"protected": protected, "payload": encoded_payload, "signature": _b64(signature)}


@pytest.fixture()
def receipt_material():
    private_key = Ed25519PrivateKey.generate()
    public_raw = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    verifier = Ed25519JwsReceiptVerifier(_b64(public_raw), "calculator-key-1")
    contract = {
        "issuer": "https://calculator.example", "audience": "aipol-event-tool",
        "public_key_id": "calculator-key-1",
        "receipt_format": "flattened_jws_json", "signature_algorithm": "EdDSA",
    }
    context = {
        "experiment_id": "xp-1", "experiment_version": "v1", "session_id": "session-1",
        "participant_pseudonym": "participant-1", "artifact_id": "calculator-v1",
        "artifact_hash": "a" * 64, "contract_hash": "b" * 64,
    }
    now = int(time.time())
    payload = {
        "jti": "receipt-unique-0001", "iss": contract["issuer"], "aud": contract["audience"],
        "iat": now - 1, "exp": now + 60, **context,
    }
    return private_key, verifier, contract, context, payload


def test_ed25519_jws_receipt_binds_signature_audience_expiry_participant_and_contract(receipt_material):
    private_key, verifier, contract, context, payload = receipt_material
    assert verifier.verify(_receipt(private_key, payload), contract, context) == payload["jti"]

    cases = [
        ({**payload, "aud": "wrong-audience"}, "audience"),
        ({**payload, "exp": int(time.time()) - 1}, "발급·만료"),
        ({**payload, "participant_pseudonym": "other-participant"}, "binding"),
        ({**payload, "contract_hash": "0" * 64}, "binding"),
    ]
    for changed, message in cases:
        with pytest.raises(ExperimentError, match=message):
            verifier.verify(_receipt(private_key, changed), contract, context)

    tampered = _receipt(private_key, payload)
    tampered["signature"] = _b64(b"0" * 64)
    with pytest.raises(ExperimentError, match="서명"):
        verifier.verify(tampered, contract, context)


def test_receipt_time_window_rejects_future_issue_reversed_window_and_excess_ttl(receipt_material):
    private_key, verifier, contract, context, payload = receipt_material
    now = int(time.time())
    invalid_windows = (
        {**payload, "iat": now + 30, "exp": now + 60},
        {**payload, "iat": now + 30, "exp": now + 20},
        {**payload, "iat": now - 1, "exp": now + verifier.max_ttl_seconds + 1},
    )
    for changed in invalid_windows:
        with pytest.raises(ExperimentError, match="발급·만료"):
            verifier.verify(_receipt(private_key, changed), contract, context)

    boundary = {
        **payload,
        "iat": now,
        "exp": now + verifier.max_ttl_seconds,
        "jti": "receipt-boundary-0002",
    }
    assert verifier.verify(_receipt(private_key, boundary), contract, context) == boundary["jti"]


def test_receipt_rejects_extra_flattened_members_and_unsupported_protected_headers(receipt_material):
    private_key, verifier, contract, context, payload = receipt_material
    valid = _receipt(private_key, payload)
    with pytest.raises(ExperimentError, match="protected, payload, signature"):
        verifier.verify({**valid, "header": {"kid": "calculator-key-1"}}, contract, context)

    for extra in (
        {"crit": ["exp"]},
        {"b64": False},
        {"unexpected": "value"},
    ):
        protected = {"alg": "EdDSA", "typ": "JWT", "kid": "calculator-key-1", **extra}
        with pytest.raises(ExperimentError, match="protected header fields"):
            verifier.verify(
                _receipt(private_key, payload, protected_header=protected), contract, context
            )


def test_receipt_rejects_padded_or_noncanonical_base64url_segments(receipt_material):
    private_key, verifier, contract, context, payload = receipt_material
    protected = base64.urlsafe_b64encode(json.dumps(
        {"alg": "EdDSA", "typ": "JWT", "kid": "calculator-key-1"},
        separators=(",", ":"), sort_keys=True,
    ).encode()).decode("ascii")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(
        payload, separators=(",", ":"), sort_keys=True,
    ).encode()).decode("ascii")
    signature = base64.urlsafe_b64encode(
        private_key.sign(f"{protected}.{encoded_payload}".encode("ascii"))
    ).decode("ascii")
    with pytest.raises(ExperimentError, match="unpadded canonical base64url"):
        verifier.verify(
            {"protected": protected, "payload": encoded_payload, "signature": signature},
            contract,
            context,
        )


def test_receipt_environment_wiring_is_explicit_and_fail_closed(monkeypatch):
    monkeypatch.delenv("AIPOL_RECEIPT_VERIFIER_MODE", raising=False)
    assert verifier_from_environment() is None
    monkeypatch.setenv("AIPOL_RECEIPT_VERIFIER_MODE", "ed25519_jws")
    monkeypatch.delenv("AIPOL_RECEIPT_ED25519_PUBLIC_KEY_B64", raising=False)
    monkeypatch.delenv("AIPOL_RECEIPT_KEY_ID", raising=False)
    with pytest.raises(RuntimeError, match="requires public key"):
        verifier_from_environment()
