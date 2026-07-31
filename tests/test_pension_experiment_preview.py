from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "cases" / "pension" / "experiment" / "index.html"
SOURCE = ROOT / "integrations" / "kaps-pension-experiment" / "vendor" / "src"


def soup() -> BeautifulSoup:
    return BeautifulSoup(PAGE.read_text(encoding="utf-8"), "html.parser")


def source_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.tsx"))


def test_review_build_is_noindex_and_keeps_portal_navigation() -> None:
    document = soup()
    assert document.select_one('meta[name="robots"]')["content"] == "noindex,nofollow,noarchive"
    assert document.select_one('meta[name="aipol-source-commit"]')["content"] == (
        "fcbae3c0dab18476e2274f9e4ff91dadeb2db944"
    )
    assert document.find("a", href="/cases/pension/")
    assert document.find("a", href="/")
    assert document.title.string == "연금개혁-AI 숙의민주주의 정책실험 | AIPOL"
    assert document.find("img", src="/assets/aipol-logo.png", alt="AIPOL")
    assert document.find("link", rel="stylesheet", href="/assets/site.css")
    assert document.find("script", src="/assets/site.js")
    assert not document.select(".ipol-project-partners")
    assert document.find("meta", property="og:title", content="연금개혁-AI 숙의민주주의 정책실험 | AIPOL")
    assert document.find("meta", property="og:image", content="https://aipol.kaps.or.kr/assets/og-aipol.png")
    assert document.find("meta", attrs={"name": "twitter:card", "content": "summary_large_image"})


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


def test_built_app_uses_the_scoped_pension_route() -> None:
    document = soup()
    script = document.find("script", src=True)
    assert script and script["src"].startswith("/cases/pension/experiment/assets/")
    canonical = document.select_one('link[rel="canonical"]')
    assert canonical and canonical["href"] == "https://aipol.kaps.or.kr/cases/pension/experiment/"


def test_adapter_keeps_profile_edit_available_on_mobile() -> None:
    adapter = (PAGE.parent / "integration-shell.js").read_text(encoding="utf-8")
    assert "ipol-profile-edit" in adapter
    assert "사전 프로필 정보 변경" in adapter
    assert "ResizeObserver" in adapter
