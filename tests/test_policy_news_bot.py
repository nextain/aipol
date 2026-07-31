"""Contracts for the official-source policy news bot and generated feed."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content" / "global-ai-policy"
BOT = ROOT / "bots" / "policy_news"
SITE = ROOT / "site" / "global"
REQUIRED = {
    "id",
    "published",
    "source_name",
    "source_url",
    "country",
    "title_ko",
    "summary_ko",
    "policy_use",
    "human_review",
    "relevance",
    "caveat",
    "review_status",
}


def records() -> list[dict[str, str]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(CONTENT.glob("*.json"))]


def test_content_contract_and_unique_sources() -> None:
    items = records()
    assert items
    assert all(set(item) == REQUIRED for item in items)
    assert len({item["id"] for item in items}) == len(items)
    assert len({item["source_url"] for item in items}) == len(items)
    for item in items:
        assert item["source_url"].startswith("https://")
        assert all(item[key].strip() for key in REQUIRED)
        assert any(label in item["review_status"] for label in ("요약", "초안", "검토"))


def test_discovery_sources_are_allowlisted_official_https_hosts() -> None:
    config = json.loads((BOT / "sources.json").read_text(encoding="utf-8"))
    assert config["feeds"]
    assert config["ai_terms"] and config["relevance_terms"]
    for feed in config["feeds"]:
        parsed = urlparse(feed["url"])
        assert parsed.scheme == "https"
        assert parsed.hostname in feed["allowed_hosts"]
        assert all(host and "/" not in host for host in feed["allowed_hosts"])


def test_generated_rss_matches_content() -> None:
    root = ET.parse(SITE / "rss.xml").getroot()
    entries = root.findall("./channel/item")
    assert len(entries) == len(records())
    assert len({entry.findtext("guid") for entry in entries}) == len(entries)
    assert all(entry.findtext("link", "").startswith("https://") for entry in entries)


def test_generated_html_marks_ai_editorial_boundary() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    normalized = " ".join(html.split())
    assert "현재 발행분과 자동화 준비 상태를 구분" in normalized
    assert "현재 공개된 8건은 Codex" in normalized
    assert "solar-open2" in normalized
    assert "비공개 초안 1건" in normalized
    assert "nvidia/nemotron-3-ultra-550b-a55b:free" in normalized
    assert "정기 자동발행은 아직 가동하지 않았습니다" in normalized
    for item in records():
        assert item["title_ko"] in html
        assert item["source_url"] in html


def test_builder_is_deterministic() -> None:
    sys.path.insert(0, str(BOT))
    import build

    items = build.items()
    assert build.build_html(items) == build.build_html(items)
    assert build.build_rss(items).decode("utf-8") == (SITE / "rss.xml").read_text(encoding="utf-8")


def test_discovery_workflow_has_no_model_or_cloud_credentials() -> None:
    workflow = (ROOT / ".github" / "workflows" / "policy-news-bot.yml").read_text(encoding="utf-8")
    lowered = workflow.lower()
    assert "--write-queue" in workflow
    assert "id-token" not in lowered
    assert "google-github-actions" not in lowered
    assert "vertex" not in lowered
    assert "gcp" not in lowered
    assert "site/global" not in workflow


def test_solar_adapter_is_review_only_and_bounded() -> None:
    sys.path.insert(0, str(BOT))
    import solar_adapter

    packet = {
        "source_name": "Official Agency",
        "source_url": "https://example.gov/policy-ai",
        "published": "2026-07-21",
        "country": "Test",
        "title": "Official item",
        "source_text": "AI is used to support a public consultation analysis.",
    }
    payload = solar_adapter.build_payload(packet, "solar-open2")
    assert payload["model"] == "solar-open2"
    assert payload["max_tokens"] == 16384
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert solar_adapter.ENDPOINT == "https://api.upstage.ai/v1/chat/completions"
    assert "UPSTAGE_API_KEY" not in json.dumps(payload)
    assert "신뢰할 수 없는 데이터" in payload["messages"][0]["content"]
    assert solar_adapter.FIELD_CHAR_LIMITS["summary_ko"] == 900


def test_solar_adapter_reads_key_alias_without_shell_evaluation(tmp_path) -> None:
    sys.path.insert(0, str(BOT))
    import solar_adapter

    env_file = tmp_path / "llm-key.env"
    env_file.write_text(
        "IGNORED=$(touch should-not-run)\nUPSTAGE_KEY='test-private-key'\n",
        encoding="utf-8",
    )
    assert solar_adapter.api_key_from_env_file(env_file) == "test-private-key"
    assert not (tmp_path / "should-not-run").exists()


def test_nemotron_review_is_independent_strict_and_keyless() -> None:
    sys.path.insert(0, str(BOT))
    import nemotron_review

    packet = {
        "source_name": "Official Agency",
        "source_url": "https://example.gov/policy-ai",
        "published": "2026-07-21",
        "country": "Test",
        "title": "Official item",
        "source_text": "AI supports consultation analysis. A human analyst approves the result.",
    }
    draft = {
        "title_ko": "공식 정책 AI 사례",
        "summary_ko": "AI가 의견수렴 분석을 지원한다.",
        "policy_use": "의견수렴 분석",
        "human_review": "사람 분석가가 결과를 승인한다.",
        "relevance": "정책개발 지원 사례",
        "caveat": "정책 결정을 자동화하지 않는다.",
    }
    payload = nemotron_review.build_payload(packet, draft)
    assert payload["model"].endswith(":free")
    assert payload["temperature"] == 0
    assert "BLOCK" in payload["messages"][0]["content"]
    assert "OPENROUTER_API_KEY" not in json.dumps(payload)
    assert "translation_fidelity" in nemotron_review.ALLOWED_COVERAGE


def test_nemotron_review_extracts_json_after_nonpublic_reasoning_prefix() -> None:
    sys.path.insert(0, str(BOT))
    import nemotron_review

    content = (
        "<think>internal provider preamble</think>\n"
        '{"verdict":"PASS","issues":[],"coverage":['
        '"names_and_institutions","dates_and_numbers","translation_fidelity",'
        '"unsupported_claims","material_omissions","human_review_claims","limitations"],'
        '"summary":"원문과 일치"}'
    )
    parsed = nemotron_review.parse_review_content(content)
    assert parsed["verdict"] == "PASS"
    assert parsed["issues"] == []


def test_public_site_does_not_link_to_private_repository() -> None:
    public_html = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "site").rglob("*.html"))
    assert "github.com/nextain/policy-lab" not in public_html
