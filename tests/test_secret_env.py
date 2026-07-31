from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest


EVENT_TOOL = Path(__file__).resolve().parents[1] / "event-tool"
sys.path.insert(0, str(EVENT_TOOL))

import secret_env  # noqa: E402


def test_plain_value_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMPLE_JSON", '{"mode":"plain"}')
    monkeypatch.setenv(
        "SAMPLE_JSON_B64",
        base64.b64encode(b'{"mode":"encoded"}').decode("ascii"),
    )
    assert secret_env.text("SAMPLE_JSON") == '{"mode":"plain"}'


def test_base64_value_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAMPLE_JSON", raising=False)
    monkeypatch.setenv(
        "SAMPLE_JSON_B64",
        base64.b64encode('{"역할":"운영"}'.encode("utf-8")).decode("ascii"),
    )
    assert secret_env.text("SAMPLE_JSON") == '{"역할":"운영"}'


def test_invalid_base64_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAMPLE_JSON", raising=False)
    monkeypatch.setenv("SAMPLE_JSON_B64", "not-base64!")
    with pytest.raises(ValueError, match="valid base64"):
        secret_env.text("SAMPLE_JSON")
