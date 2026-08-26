from __future__ import annotations

import importlib.util
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_live_aipol.py"
SPEC = importlib.util.spec_from_file_location("verify_live_aipol", SCRIPT)
assert SPEC and SPEC.loader
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def _page(url: str, *, forbidden: str = "") -> str:
    return f'''<html><head><title>AIPOL page</title><link rel="canonical" href="{url}">
    <meta property="og:url" content="{url}"><meta property="og:site_name" content="AIPOL">
    <meta property="og:title" content="AIPOL page"><meta property="og:description" content="AIPOL page">
    <meta property="og:image" content="https://aipol.kaps.or.kr/assets/og-aipol.png"></head><body>{forbidden}</body></html>'''


def _rss(*, forbidden: str = "") -> str:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "AIPOL 해외 AI 정책개발 동향"
    ET.SubElement(channel, "link").text = "https://aipol.kaps.or.kr/global/"
    ET.SubElement(channel, "description").text = (
        f"KAPS Human + AI Collaboration Policy Lab 공식 자료 {forbidden}"
    )
    return ET.tostring(rss, encoding="unicode")


def _session_redirect(*, forbidden: str = "") -> str:
    return f'''<html><head><title>AIPOL session redirect</title>
    <meta name="robots" content="noindex,nofollow,noarchive">
    <script defer src="/cases/pension/experiment/redirect.js"></script></head>
    <body><a href="https://session.aipol.kaps.or.kr/cases/pension/experiment/">continue</a>{forbidden}</body></html>'''


def test_live_smoke_checks_all_routes(monkeypatch) -> None:
    visited: list[str] = []
    def fetch(url: str):
        visited.append(url)
        if url.endswith(smoke.SESSION_REDIRECT_ROUTE):
            return url, _session_redirect()
        return url, _rss() if url.endswith("rss.xml") else _page(url)

    monkeypatch.setattr(smoke, "fetch", fetch)
    smoke.verify("https://aipol.kaps.or.kr", attempts=1, delay_seconds=0)
    assert visited == [f"https://aipol.kaps.or.kr{route}" for route in smoke.ROUTES]


def test_dev_smoke_fetches_dev_but_keeps_production_canonical(monkeypatch) -> None:
    visited: list[str] = []
    def fetch(url: str):
        visited.append(url)
        canonical = url.replace("aipol-dev.example", "aipol.kaps.or.kr")
        if url.endswith(smoke.SESSION_REDIRECT_ROUTE):
            return url, _session_redirect()
        return url, _rss() if url.endswith("rss.xml") else _page(canonical)

    monkeypatch.setattr(smoke, "fetch", fetch)
    smoke.verify("https://aipol-dev.example", attempts=1, delay_seconds=0)
    assert visited[0] == "https://aipol-dev.example/"


def test_live_smoke_fails_on_stale_origin(monkeypatch) -> None:
    def fetch(url: str):
        if url.endswith("rss.xml"):
            return url, _rss(forbidden="aipol.nextain.io")
        if url.endswith(smoke.SESSION_REDIRECT_ROUTE):
            return url, _session_redirect(forbidden="aipol.nextain.io")
        return url, _page(url, forbidden="aipol.nextain.io")

    monkeypatch.setattr(
        smoke,
        "fetch",
        fetch,
    )
    with pytest.raises(RuntimeError, match="forbidden copy"):
        smoke.verify("https://aipol.kaps.or.kr", attempts=1, delay_seconds=0)


def test_live_smoke_fails_on_stale_rss_origin(monkeypatch) -> None:
    def fetch(url: str):
        if url.endswith("rss.xml"):
            return url, _rss().replace("aipol.kaps.or.kr", "policylab.nextain.io")
        if url.endswith(smoke.SESSION_REDIRECT_ROUTE):
            return url, _session_redirect()
        return url, _page(url)

    monkeypatch.setattr(smoke, "fetch", fetch)
    with pytest.raises(RuntimeError, match="RSS canonical channel link mismatch"):
        smoke.verify("https://aipol.kaps.or.kr", attempts=1, delay_seconds=0)


def test_live_smoke_rejects_non_https_origin() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        smoke.verify("http://aipol.kaps.or.kr", attempts=1, delay_seconds=0)


def test_live_smoke_rejects_broken_session_redirect(monkeypatch) -> None:
    def fetch(url: str):
        if url.endswith("rss.xml"):
            return url, _rss()
        if url.endswith(smoke.SESSION_REDIRECT_ROUTE):
            return url, "<html><head><title>redirect</title></head></html>"
        return url, _page(url)

    monkeypatch.setattr(smoke, "fetch", fetch)
    with pytest.raises(RuntimeError, match="missing CSP-compatible redirect script"):
        smoke.verify("https://aipol.kaps.or.kr", attempts=1, delay_seconds=0)
