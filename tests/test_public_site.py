"""대외 정적 사이트의 링크·검색 비노출·프라이버시 계약."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).parents[1]
SITE = ROOT / "site"


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, dict[str, str]]] = []
        self.ids: list[str] = []
        self.h1_count = 0
        self.robots = ""
        self.inline_styles = 0
        self.inline_scripts = 0
        self.forms = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("id"):
            self.ids.append(values["id"])
        if tag == "h1":
            self.h1_count += 1
        if tag == "a" and values.get("href"):
            self.links.append((values["href"], values))
        if tag == "meta" and values.get("name", "").lower() == "robots":
            self.robots = values.get("content", "").lower()
        if values.get("style"):
            self.inline_styles += 1
        if tag == "script" and not values.get("src"):
            self.inline_scripts += 1
        if tag == "form":
            self.forms += 1


def pages() -> list[Path]:
    # The professor-provided pension experiment is a compiled React SPA.
    # Its semantic structure exists after hydration and is covered separately.
    experiment = SITE / "cases" / "pension" / "experiment"
    return sorted(path for path in SITE.rglob("*.html") if experiment not in path.parents)


def parse(path: Path) -> PageParser:
    parser = PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def local_target(href: str) -> Path | None:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or href.startswith(("mailto:", "tel:")):
        return None
    path = parsed.path
    if not path or path.startswith("#"):
        return None
    target = SITE / path.lstrip("/")
    if path.endswith("/"):
        target /= "index.html"
    return target


def test_every_public_page_has_accessible_structure_and_is_indexable() -> None:
    assert len(pages()) >= 8
    for path in pages():
        parser = parse(path)
        assert parser.h1_count == 1, path
        assert "index" in parser.robots
        assert "follow" in parser.robots
        assert "noindex" not in parser.robots
        assert len(parser.ids) == len(set(parser.ids)), path
        assert parser.inline_styles == 0, path
        assert parser.inline_scripts == 0, path
        assert parser.forms == 0, path
        source = path.read_text(encoding="utf-8")
        assert 'class="skip-link"' in source
        assert "data-nav-toggle" in source
        assert "data-nav" in source


def test_internal_links_and_external_link_safety() -> None:
    for path in pages():
        for href, attrs in parse(path).links:
            target = local_target(href)
            if target is not None:
                assert target.exists(), f"{path}: missing {href} -> {target}"
            if href.startswith(("http://", "https://")):
                assert "noopener" in attrs.get("rel", "").split(), f"{path}: {href}"


def test_search_exposure_and_privacy_contract() -> None:
    robots_text = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert robots_text == (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /cases/pension/experiment/\n"
        "Allow: /cases/pension/experiment/terms/\n"
        "Allow: /cases/pension/experiment/privacy/\n"
        "Disallow: /admin/\n\n"
        "Sitemap: https://aipol.kaps.or.kr/sitemap.xml\n"
    )
    sitemap = SITE / "sitemap.xml"
    assert sitemap.exists()
    assert ET.parse(sitemap).getroot().tag.endswith("urlset")
    assert "Sitemap: https://aipol.kaps.or.kr/sitemap.xml" in robots_text
    config = json.loads((SITE / "staticwebapp.config.json").read_text(encoding="utf-8"))
    headers = {key.lower(): value for key, value in config["globalHeaders"].items()}
    assert "x-robots-tag" not in headers
    assert "frame-ancestors 'none'" in headers["content-security-policy"]
    assert "https://www.googletagmanager.com" in headers["content-security-policy"]
    assert "https://www.google-analytics.com" in headers["content-security-policy"]
    assert "https://*.google-analytics.com" in headers["content-security-policy"]
    redirects = {
        route["route"]: route["redirect"]
        for route in config["routes"]
        if "redirect" in route
    }
    assert redirects["/README.md"] == "/"
    experiment_route = next(
        route for route in config["routes"] if route["route"] == "/cases/pension/experiment/"
    )
    assert "noindex" in experiment_route["headers"]["X-Robots-Tag"]
    assert "nofollow" in experiment_route["headers"]["X-Robots-Tag"]
    admin_route = next(route for route in config["routes"] if route["route"] == "/admin/*")
    assert "noindex" in admin_route["headers"]["X-Robots-Tag"]

    text_suffixes = {".css", ".html", ".js", ".json", ".svg", ".txt", ".xml"}
    combined = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in SITE.rglob("*.*")
        if path.is_file()
        and path.suffix in text_suffixes
        and (SITE / "cases" / "pension" / "experiment") not in path.parents
    )
    forbidden = ("facebook.com/tr", "hotjar", "mailto:")
    for marker in forbidden:
        assert marker not in combined


def test_assets_are_local_and_no_third_party_imports() -> None:
    css = (SITE / "assets/site.css").read_text(encoding="utf-8")
    js = (SITE / "assets/site.js").read_text(encoding="utf-8")
    assert "@import" not in css
    assert "url(http" not in css
    assert "fetch(" not in js
    assert "XMLHttpRequest" not in js


def test_ga4_is_loaded_once_from_the_shared_script() -> None:
    js = (SITE / "assets" / "site.js").read_text(encoding="utf-8")
    assert js.count('"G-HJDJKV750X"') == 1
    assert "https://www.googletagmanager.com/gtag/js?id=" in js
    assert 'window.gtag("config", analyticsMeasurementId)' in js
    for path in SITE.rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        assert '/assets/site.js' in source, path


def test_logo_derived_favicon_assets_are_published() -> None:
    favicon_svg = (SITE / "assets" / "favicon.svg").read_text(encoding="utf-8")
    assert "#075c96" in favicon_svg
    assert "#a9ed58" in favicon_svg
    assert (SITE / "assets" / "favicon.ico").read_bytes().startswith(b"\x00\x00\x01\x00")
    assert (SITE / "assets" / "apple-touch-icon.png").read_bytes().startswith(b"\x89PNG")
    for path in pages():
        assert 'href="/assets/favicon.svg"' in path.read_text(encoding="utf-8"), path


def test_global_watch_is_visible_and_linked_from_home() -> None:
    home = (SITE / "index.html").read_text(encoding="utf-8")
    global_page = (SITE / "global" / "index.html").read_text(encoding="utf-8")
    assert "<h2>해외동향</h2>" in home
    assert 'href="/global/">해외동향</a>' in home
    assert "한국어 요약 보기" in home
    assert "<h1>해외동향</h1>" in global_page


def test_bilingual_metadata_and_machine_discovery_files() -> None:
    assert (SITE / "llms.txt").exists()
    llms = (SITE / "llms.txt").read_text(encoding="utf-8")
    assert "no-index soft launch" not in llms
    assert "Survey, experiment-input, and administration interfaces are excluded." in llms
    assert (SITE / "assets" / "og-policy-lab.png").exists()
    for route in ("", "project", "method", "cases", "events", "participate", "global"):
        ko = SITE / route / "index.html" if route else SITE / "index.html"
        en = SITE / "en" / route / "index.html" if route else SITE / "en" / "index.html"
        assert ko.exists() and en.exists()
        for path in (ko, en):
            source = path.read_text(encoding="utf-8")
            assert 'property="og:title"' in source
            assert 'property="og:image"' in source
            assert 'name="twitter:card"' in source
            assert 'hreflang="ko"' in source
            assert 'hreflang="en"' in source


def test_home_first_view_links_case_and_makers() -> None:
    home = (SITE / "index.html").read_text(encoding="utf-8")
    english = (SITE / "en" / "index.html").read_text(encoding="utf-8")
    assert 'class="hero-case"' in home
    assert 'href="/cases/pension/"' in home
    assert 'href="https://about.nextain.io/ko"' in home
    assert 'href="https://about.nextain.io/en"' in english
    assert "https://naia.nextain.io" in home
    assert "https://kaps.or.kr/" in home
    normalized_home = " ".join(home.split())
    assert "Open source AI policy R&amp;D Project, AIPOL" in normalized_home
    assert "AIPOL(아이폴)" not in normalized_home
    assert "<strong>공동운영</strong> AI 에이전트 <a href=\"https://naia.nextain.io\" rel=\"noopener\">Naia</a>를 만드는 <a href=\"https://about.nextain.io/ko\" rel=\"noopener\">넥스테인</a>과 <a href=\"https://kaps.or.kr/\" rel=\"noopener\">한국정책학회</a>가 함께 운영합니다." in normalized_home
    assert 'class="hero-case-chip"' not in home
    assert 'class="footer-partners"' in home


def test_event_page_has_responsive_poster_and_mobile_navigation_icon() -> None:
    events = (SITE / "events" / "index.html").read_text(encoding="utf-8")
    english = (SITE / "en" / "events" / "index.html").read_text(encoding="utf-8")
    css = (SITE / "assets" / "site.css").read_text(encoding="utf-8")
    script = (SITE / "assets" / "site.js").read_text(encoding="utf-8")
    assert 'class="event-poster"' in events
    assert 'class="event-poster"' in english
    assert "AIPOL(아이폴)" in events
    assert ".nav-toggle::before" in css
    assert "body.nav-open .nav-toggle::after" in css
    assert "font-size: 0" in css
    assert '"메뉴 닫기"' in script


def test_unpublished_pension_material_is_not_published() -> None:
    case = (SITE / "cases" / "pension" / "index.html").read_text(encoding="utf-8")
    english = (SITE / "en" / "cases" / "pension" / "index.html").read_text(encoding="utf-8")
    assert not any(path.is_file() for path in (SITE / "cases" / "pension" / "report").rglob("*"))
    assert not any(path.is_file() for path in (SITE / "en" / "cases" / "pension" / "report").rglob("*"))
    assert 'href="/cases/pension/report/"' not in case
    assert 'href="/en/cases/pension/report/"' not in english
    assert "미공개 정책안" in case
    assert "Unpublished policy proposals" in english
    assert "pension.nextain.io" not in "\n".join(path.read_text(encoding="utf-8") for path in SITE.rglob("*.html"))
    public_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in SITE.rglob("*") if path.is_file() and path.suffix in {".html", ".json", ".txt", ".xml"}
    )
    for marker in (
        "부분적립형 확정급여" + "(양재진 안)",
        "2026~2027년 2년간 " + "100조원",
        "70년 후 " + "적립배율",
    ):
        assert marker not in public_text


def test_removed_future_scenario_is_not_advertised() -> None:
    routes = (
        SITE / "index.html",
        SITE / "project" / "index.html",
        SITE / "method" / "index.html",
        SITE / "cases" / "index.html",
        SITE / "cases" / "pension" / "index.html",
        SITE / "events" / "index.html",
        SITE / "en" / "index.html",
        SITE / "en" / "project" / "index.html",
        SITE / "en" / "method" / "index.html",
        SITE / "en" / "cases" / "index.html",
        SITE / "en" / "cases" / "pension" / "index.html",
        SITE / "en" / "events" / "index.html",
    )
    forbidden = ("AI 미래 시나리오", "2045년 가능성 탐색", "AI future scenarios", "Exploring 2045")
    for path in routes:
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, (path, marker)
