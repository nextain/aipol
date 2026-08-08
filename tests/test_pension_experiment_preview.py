from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "cases" / "pension" / "experiment" / "index.html"
SOURCE = ROOT / "integrations" / "kaps-pension-experiment" / "vendor" / "src"
BUILD_SCRIPT = ROOT / "scripts" / "build_pension_experiment.mjs"
SERVICE_URL = "https://session.aipol.kaps.or.kr/aipol.html"


def soup() -> BeautifulSoup:
    return BeautifulSoup(PAGE.read_text(encoding="utf-8"), "html.parser")


def source_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.tsx"))


def test_official_route_is_noindex_canonical_handoff_and_keeps_portal_navigation() -> None:
    document = soup()
    assert document.select_one('meta[name="robots"]')["content"] == "noindex,nofollow,noarchive"
    assert document.find("a", href="/cases/pension/")
    assert document.find("a", href="/")
    assert document.title.string == "연금개혁-AI 숙의민주주의 정책실험 | AIPOL"
    assert document.find("img", src="/assets/aipol-logo.png", alt="AIPOL")
    assert document.find("link", rel="stylesheet", href="/assets/site.css")
    assert document.find("script", src="/assets/site.js")
    assert not document.find("meta", attrs={"http-equiv": "refresh"})
    assert document.find("link", rel="canonical", href="https://aipol.kaps.or.kr/cases/pension/experiment/")
    assert document.find("meta", property="og:url")["content"] == "https://aipol.kaps.or.kr/cases/pension/experiment/"
    assert document.find("script", src="/cases/pension/experiment/entry.js")
    entry = (PAGE.parent / "entry.js").read_text("utf-8")
    assert SERVICE_URL in entry
    assert 'params.get("review")' in entry and 'params.get("experiment")' in entry


def test_experiment_legal_pages_are_built_and_linked() -> None:
    experiment = PAGE.parent
    source = (ROOT / "integrations" / "kaps-pension-experiment" / "adapter" / "integration-shell.js").read_text(encoding="utf-8")
    assert '"/cases/pension/experiment/terms/"' in source
    assert '"/cases/pension/experiment/privacy/"' in source
    for slug in ("terms", "privacy"):
        page = BeautifulSoup((experiment / slug / "index.html").read_text(encoding="utf-8"), "html.parser")
        assert page.title and page.find("meta", property="og:title")
        assert page.find("meta", property="og:description")
        assert page.find("meta", property="og:image")
        assert page.find("link", rel="canonical")
        assert page.find("script", src="/assets/site.js")

    privacy = (experiment / "privacy" / "index.html").read_text(encoding="utf-8")
    assert "Google Analytics 4" in privacy
    assert "G-HJDJKV750X" in privacy


def test_professor_scenario_preserves_two_ballots_not_three() -> None:
    text = source_text()
    assert "1. 사전조사" in text
    assert "2. 시뮬레이션·1차 투표" in text
    assert "3. AI 진단·소그룹 토론" in text
    assert "4. 최종 투표·결과 대시보드" in text
    assert "1차·2차 투표 통합 분석 보고서" in text
    assert "3차 투표" not in text
    assert "M3" not in text


def test_vendor_build_script_keeps_scoped_route_and_source_provenance() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert '"--base=/cases/pension/experiment/"' in script
    assert 'source_commit: "fcbae3c0dab18476e2274f9e4ff91dadeb2db944"' in script
    assert 'source_scope: "top-level scenario app; personal-pension-simulator subproject excluded"' in script
    assert 'integration_route: "/cases/pension/experiment/"' in script


def test_adapter_keeps_profile_edit_available_on_mobile() -> None:
    adapter = (PAGE.parent / "integration-shell.js").read_text(encoding="utf-8")
    assert "ipol-profile-edit" in adapter
    assert "사전 프로필 정보 변경" in adapter
    assert "ResizeObserver" in adapter
