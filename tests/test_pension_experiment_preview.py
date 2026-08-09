import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "event-tool" / "web"
PROCESS_PAGE = WEB / "aipol-process-review.html"
PARTICIPANT_SCRIPT = WEB / "aipol.js"
MIGRATION_PAGE = ROOT / "site" / "cases" / "pension" / "experiment" / "index.html"
PROVENANCE = MIGRATION_PAGE.parent / "provenance.json"
SERVICE_REVIEW_URL = "https://session.aipol.kaps.or.kr/cases/pension/experiment/?review=process&dataset=pension-v4-20260808-r1"


def test_process_review_is_a_parameterized_state_in_the_real_service() -> None:
    document = BeautifulSoup((WEB / "aipol.html").read_text(encoding="utf-8"), "html.parser")
    assert document.select_one('meta[name="robots"]')["content"] == "noindex,nofollow,noarchive"
    assert document.find(id="state-review")
    assert "합성 이벤트 DB · 읽기 전용" in document.get_text(" ", strip=True)
    assert document.find("script", src="/aipol.js")
    assert document.find("link", href="/aipol.css")
    script = PARTICIPANT_SCRIPT.read_text(encoding="utf-8")
    assert 'params.get("review")' in script
    assert 'params.get("dataset")' in script
    assert "/api/aipol/process-reviews/" in script


def test_process_review_renderer_contains_the_approved_v4_contract_markers() -> None:
    text = PARTICIPANT_SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "D안 승인 입력 흐름",
        "3개 AI 협의",
        "사람 검수·최종 승인",
        "격리된 읽기 전용 합성 이벤트",
        "10단계 프로세스 계약",
    ):
        assert marker in text or marker in (WEB / "aipol.html").read_text(encoding="utf-8")


def test_old_review_route_only_redirects_to_the_parameterized_service_review() -> None:
    document = BeautifulSoup(PROCESS_PAGE.read_text(encoding="utf-8"), "html.parser")
    refresh = document.select_one('meta[http-equiv="refresh"]')
    assert refresh and "/cases/pension/experiment/?review=process&dataset=pension-v4-20260808-r1" in refresh["content"]
    assert document.find("a", href="/cases/pension/experiment/?review=process&dataset=pension-v4-20260808-r1")


def test_legacy_public_route_only_migrates_to_the_same_service_review() -> None:
    html = MIGRATION_PAGE.read_text(encoding="utf-8")
    document = BeautifulSoup(html, "html.parser")
    assert document.select_one('meta[name="robots"]')["content"] == "noindex,nofollow,noarchive"
    assert document.select_one('meta[http-equiv="refresh"]') is None
    assert document.find("a", href=SERVICE_REVIEW_URL, string=lambda value: value and "프로세스 리뷰" in value)
    assert "aipol-pension-design-review.vercel.app" not in html
    assert not document.find("script", src=re.compile(r"/cases/pension/experiment/assets/"))


def test_provenance_marks_the_old_review_as_quarantined() -> None:
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert provenance["contract_version"] == "4.0"
    assert provenance["active_service_route"] == SERVICE_REVIEW_URL
    assert provenance["quarantine_commit"] == "15bf0c7"
    assert provenance["legacy_review_status"].startswith("quarantined")
    assert "M3 ABC plus separate D acceptability" in provenance["measurement_flow"]
