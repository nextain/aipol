import json
import re
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "event-tool" / "web"
PROCESS_PAGE = WEB / "aipol-process-review.html"
PROCESS_SCRIPT = WEB / "aipol-process-review.js"
MIGRATION_PAGE = ROOT / "site" / "cases" / "pension" / "experiment" / "index.html"
PROVENANCE = MIGRATION_PAGE.parent / "provenance.json"
SERVICE_REVIEW_URL = "https://session.aipol.kaps.or.kr/aipol-process-review.html"


def test_process_review_is_noindex_read_only_and_in_the_real_service() -> None:
    document = BeautifulSoup(PROCESS_PAGE.read_text(encoding="utf-8"), "html.parser")
    assert document.select_one('meta[name="robots"]')["content"] == "noindex,nofollow,noarchive"
    assert "읽기 전용 · 데이터 저장 없음" in document.get_text(" ", strip=True)
    assert document.find("a", href="/aipol-admin.html")
    assert document.find("script", src="/aipol-process-review.js")
    assert document.find("link", href="/aipol.css")


def test_process_review_matches_the_approved_ten_step_v4_contract() -> None:
    text = PROCESS_SCRIPT.read_text(encoding="utf-8")
    assert len(re.findall(r'^\s*\["(?:10|[1-9])",', text, flags=re.MULTILINE)) == 10
    for marker in (
        "A·B·C안 설명과 1차 숙의",
        "1차 결과 기반 5대 쟁점",
        "전문가 설명과 2차 숙의",
        "3개 AI 협의 D안 생성",
        "3차 투표와 D안 별도 평가",
        "최종 결과와 전문가 논평",
    ):
        assert marker in text
    assert "개인 연금액 계산 정보는 수집하지 않습니다" in text
    assert "D안은 네 번째 선택지가 아니라" in text
    assert "개인 연금 시뮬레이션" not in text


def test_legacy_static_route_only_migrates_to_the_same_service_review() -> None:
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
