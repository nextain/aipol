from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).parents[1]
WEB = ROOT / "event-tool" / "web"
SITE = ROOT / "site"
BASELINE = json.loads(
    (ROOT / "tests" / "fixtures" / "aipol_portal_preservation_baseline.json").read_text("utf-8")
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_public_sha256(path: Path) -> str:
    content = path.read_text("utf-8").replace("aipol.kaps.or.kr", "policylab.nextain.io")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalized_source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _site_path(route: str) -> Path:
    if route == "/":
        return SITE / "index.html"
    return SITE / route.lstrip("/") / "index.html"


def test_existing_participant_application_is_byte_preserved() -> None:
    for relative, expected in BASELINE["core_sha256"].items():
        assert _sha256(ROOT / relative) == expected, relative


def test_public_portal_matches_the_approved_branding_revision() -> None:
    for relative, expected in BASELINE["public_portal_normalized_sha256"].items():
        assert _normalized_public_sha256(ROOT / relative) == expected, relative


def test_professor_scenario_source_is_an_immutable_two_ballot_vendor_baseline() -> None:
    for relative, expected in BASELINE["professor_source_sha256"].items():
        assert _normalized_source_sha256(ROOT / relative) == expected, relative
    app = (ROOT / "integrations" / "kaps-pension-experiment" / "vendor" / "src" / "App.tsx").read_text("utf-8")
    report = (
        ROOT
        / "integrations"
        / "kaps-pension-experiment"
        / "vendor"
        / "src"
        / "components"
        / "ResultDashboard.tsx"
    ).read_text("utf-8")
    assert "시뮬레이션·1차 투표" in app
    assert "최종 투표·결과 대시보드" in app
    assert "1·2차 투표 결과 보고서" in report
    assert "3차 투표" not in app + report


def test_existing_event_tool_surfaces_and_static_portal_routes_remain_present() -> None:
    server = (ROOT / "event-tool" / "server.py").read_text("utf-8")
    assert 'app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")' in server
    for route in ("/api/citizen/current", "/api/citizen/submit", "/api/admin/events"):
        assert route in server
    assert (WEB / "index.html").exists() and (WEB / "admin.html").exists()
    for route in BASELINE["public_site_routes"]:
        assert _site_path(route).exists(), route


def test_general_and_aipol_operator_surfaces_link_both_directions() -> None:
    general = BeautifulSoup((WEB / "admin.html").read_text("utf-8"), "html.parser")
    aipol = BeautifulSoup((WEB / "aipol-admin.html").read_text("utf-8"), "html.parser")
    assert general.find("a", href="/aipol-admin.html", string="AIPOL 통합 운영")
    assert aipol.find(
        "a", href="/admin.html", string=lambda value: value and "일반 행사 도구" in value
    )
    for page in (general, aipol):
        robots = page.find("meta", attrs={"name": "robots"})
        assert robots and {"noindex", "nofollow"} <= set(robots["content"].split(","))


def test_aipol_participant_surface_has_portal_return_and_role_attribution() -> None:
    page = BeautifulSoup((WEB / "aipol.html").read_text("utf-8"), "html.parser")
    assert page.find("a", href="/", string="일반 행사 참여")
    assert page.find("link", rel="icon", href="/favicon.svg")
    robots = page.find("meta", attrs={"name": "robots"})
    assert robots and {"noindex", "nofollow"} <= set(robots["content"].split(","))
    footer = page.find("footer", class_="service-footer")
    assert footer and "주관: 한국정책학회(KAPS)" in footer.get_text(" ", strip=True)
    assert "기술 협력: Nextain" in footer.get_text(" ", strip=True)
    assert (WEB / "favicon.svg").exists()


def test_pension_case_discovers_the_two_ballot_scenario_and_built_app_returns_to_portal() -> None:
    case = BeautifulSoup((SITE / "cases" / "pension" / "index.html").read_text("utf-8"), "html.parser")
    experiment_path = SITE / "cases" / "pension" / "experiment" / "index.html"
    experiment = BeautifulSoup(experiment_path.read_text("utf-8"), "html.parser")
    assert case.find(
        "a", href="/cases/pension/experiment/", string=lambda value: value and "시나리오 검토 시작" in value
    )
    assert case.find(id="scenario-review")
    assert experiment.find("a", href="/cases/pension/", string="프로젝트 소개")
    assert experiment.find("a", href="/", attrs={"aria-label": "AIPOL 홈"})
    assert not experiment.find("img", alt="한국정책학회")
    assert not experiment.find("img", alt="Nextain")
    assert experiment.find("meta", attrs={"name": "aipol-source-commit"})["content"] == (
        "fcbae3c0dab18476e2274f9e4ff91dadeb2db944"
    )
    assert experiment.find("script", src=lambda value: value and value.startswith("/cases/pension/experiment/assets/"))
    provenance = json.loads((experiment_path.parent / "provenance.json").read_text("utf-8"))
    assert provenance["measurement_flow"].endswith("second final vote")


def test_public_portal_uses_nextain_aipol_origin_and_records_kaps_transition() -> None:
    for path in SITE.rglob("*"):
        if path.is_file() and path.suffix in {".html", ".xml", ".txt", ".md"}:
            assert "policylab.nextain.io" not in path.read_text("utf-8"), path
    contract = (ROOT / "docs" / "aipol-execution-contract.md").read_text("utf-8")
    assert "https://aipol.kaps.or.kr" in contract
    assert "https://aipol.kaps.or.kr" in contract
