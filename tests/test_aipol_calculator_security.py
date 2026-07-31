from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
EVENT_TOOL = ROOT / "event-tool"


@pytest.fixture(scope="module")
def store():
    sys.path.insert(0, str(EVENT_TOOL))
    try:
        return importlib.import_module("aipol_store")
    finally:
        sys.path.remove(str(EVENT_TOOL))


def test_calculator_csp_accepts_only_byte_exact_canonical_headers(store):
    assert store._canonical_calculator_csp(store.CALCULATOR_CSP_NONE) == store.CALCULATOR_CSP_NONE
    assert store._canonical_calculator_csp(store.CALCULATOR_CSP_SELF) == store.CALCULATOR_CSP_SELF
    attacks = (
        "default-src 'self'",
        store.CALCULATOR_CSP_NONE.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'"),
        store.CALCULATOR_CSP_NONE.replace("script-src 'self'", "script-src 'self' 'unsafe-eval'"),
        store.CALCULATOR_CSP_NONE.replace("script-src 'self'", "script-src https://cdn.example"),
        store.CALCULATOR_CSP_NONE.replace("connect-src 'none'", "connect-src *"),
        store.CALCULATOR_CSP_NONE.replace("object-src 'none'", "object-src 'self'"),
        store.CALCULATOR_CSP_NONE + "; worker-src blob:",
        store.CALCULATOR_CSP_NONE.replace("; ", ";", 1),
    )
    for value in attacks:
        with pytest.raises(Exception):
            store._canonical_calculator_csp(value)


def test_calculator_launch_url_is_clean_and_exact_origin(store):
    origin = "https://calculator.example"
    assert store._clean_calculator_launch_url(f"{origin}/scenario/run", origin) == f"{origin}/scenario/run"
    attacks = (
        "https://user:password@calculator.example/scenario/run",
        "https://calculator.example/scenario/run?token=secret",
        "https://calculator.example/scenario/run#access_token=secret",
        "https://calculator.example/api%2Dkey/secret",
        "https://calculator.example:443/scenario/run",
        "https://evil.example/scenario/run",
        "https://calculator.example\\@evil.example/scenario/run",
    )
    for value in attacks:
        with pytest.raises(Exception):
            store._clean_calculator_launch_url(value, origin)

