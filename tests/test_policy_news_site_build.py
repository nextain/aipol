from __future__ import annotations

import importlib.util
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("policy_news_site_build", ROOT / "bots" / "policy_news" / "build.py")
assert SPEC and SPEC.loader
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


RECORD = {
    "id": "official-1", "country": "EU", "published": "2026-07-01",
    "title_ko": "공식 정책 자료", "summary_ko": "요약", "policy_use": "분석",
    "human_review": "검토 완료", "relevance": "숙의 참고", "caveat": "범위 제한",
    "review_status": "사람 검토 완료", "source_url": "https://example.eu/official",
    "source_name": "Official source",
}


def test_global_page_builder_keeps_aipol_brand_and_metadata() -> None:
    html = build.build_html([RECORD])
    assert '<meta property="og:site_name" content="AIPOL">' in html
    assert "KAPS Human + AI Collaboration Policy Lab" in html
    assert '<link rel="canonical" href="https://aipol.kaps.or.kr/global/">' in html
    assert '<meta property="og:url" content="https://aipol.kaps.or.kr/global/">' in html
    assert "/assets/aipol-logo.png" in html
    assert "AIPOL 시사점" in html
    assert "POLICY LAB Open Source" not in html
    assert "policylab.nextain.io" not in html


def test_global_rss_builder_keeps_current_origin_and_brand() -> None:
    root = ET.fromstring(build.build_rss([RECORD]))
    channel = root.find("channel")
    assert channel is not None
    assert channel.findtext("title") == "AIPOL 해외 AI 정책개발 동향"
    assert channel.findtext("link") == "https://aipol.kaps.or.kr/global/"
    assert "KAPS Human + AI Collaboration Policy Lab" in (channel.findtext("description") or "")
    assert "AIPOL 시사점" in (channel.find("item").findtext("description") or "")
