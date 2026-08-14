"""AIPOL public metadata and brand regression contract.

These checks deliberately parse the generated HTML instead of relying on a
browser.  Social crawlers commonly read the server response without running
JavaScript, so every required value must be present in the static document.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).parents[1]
SITE = ROOT / "site"
CANONICAL_ORIGIN = "https://aipol.kaps.or.kr"
SITE_NAME = "AIPOL"
HOME_TITLE = "AIPOL — AI를 활용한 정책개발 오픈소스 R&D"
PENSION_TITLE = "연금개혁-AI 숙의민주주의 정책실험 | AIPOL"
OFFICIAL_EVENT_NAME = (
    "KAPS Human + AI Collaboration Policy Lab: 연금개혁-AI 숙의민주주의 정책실험"
)
OG_IMAGE_ALT = (
    "AIPOL — KAPS Human + AI Collaboration Policy Lab, "
    "연금개혁-AI 숙의민주주의 정책실험"
)
PRIVATE_ROUTE_PARTS = {"admin", "internal", "operator", "private"}


def _normalize(value: str) -> str:
    return " ".join(value.split())


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_lang = ""
        self.in_title = False
        self.title_count = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.meta_by_name: dict[str, str] = {}
        self.meta_by_property: dict[str, str] = {}
        self.meta_name_counts: dict[str, int] = {}
        self.meta_property_counts: dict[str, int] = {}
        self.links: list[dict[str, str]] = []

    @property
    def title(self) -> str:
        return _normalize("".join(self.title_parts))

    @property
    def text(self) -> str:
        return _normalize(" ".join(self.text_parts))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "html":
            self.html_lang = values.get("lang", "")
        elif tag == "title":
            self.in_title = True
            self.title_count += 1
        elif tag == "meta":
            if name := values.get("name", "").lower():
                self.meta_by_name[name] = values.get("content", "")
                self.meta_name_counts[name] = self.meta_name_counts.get(name, 0) + 1
            if prop := values.get("property", "").lower():
                self.meta_by_property[prop] = values.get("content", "")
                self.meta_property_counts[prop] = self.meta_property_counts.get(prop, 0) + 1
        elif tag == "link":
            self.links.append(values)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self.in_title:
            self.title_parts.append(data)


def _pages() -> list[Path]:
    experiment = SITE / "cases" / "pension" / "experiment"
    results = SITE / "cases" / "pension" / "report" / "results" / "index.html"
    return sorted(
        path for path in SITE.rglob("*.html") if experiment not in path.parents and path != results
    )


def _parse(path: Path) -> MetadataParser:
    parser = MetadataParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser


def _route_for(path: Path) -> str:
    relative = path.relative_to(SITE).as_posix()
    if relative == "index.html":
        return "/"
    assert relative.endswith("/index.html"), path
    return f"/{relative.removesuffix('index.html')}"


def _rel_tokens(link: dict[str, str]) -> set[str]:
    return set(link.get("rel", "").lower().split())


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"not a PNG: {path}"
    assert data[12:16] == b"IHDR", f"missing PNG IHDR: {path}"
    return struct.unpack(">II", data[16:24])


def test_korean_entry_points_use_approved_exact_metadata() -> None:
    expected = {
        SITE / "index.html": HOME_TITLE,
        SITE / "cases" / "pension" / "index.html": PENSION_TITLE,
    }
    for path, title in expected.items():
        parsed = _parse(path)
        assert parsed.html_lang == "ko", path
        assert parsed.title == title, path
        assert parsed.meta_by_name["description"], path
        assert parsed.meta_by_property["og:site_name"] == SITE_NAME, path


def test_every_public_page_has_consistent_static_social_metadata() -> None:
    assert _pages(), "site has no generated HTML pages"
    for path in _pages():
        parsed = _parse(path)
        route = _route_for(path)
        canonical = f"{CANONICAL_ORIGIN}{route}"

        assert parsed.html_lang == ("en" if route.startswith("/en/") else "ko"), path
        assert parsed.title_count == 1, path
        assert parsed.title and "Starter Project" not in parsed.title, path
        assert parsed.meta_by_name.get("description"), path
        assert parsed.meta_by_property.get("og:type") == "website", path
        assert parsed.meta_by_property.get("og:site_name") == SITE_NAME, path
        assert _normalize(parsed.meta_by_property.get("og:title", "")) == parsed.title, path
        assert parsed.meta_by_property.get("og:description") == parsed.meta_by_name["description"], path
        assert parsed.meta_by_name.get("twitter:card") == "summary_large_image", path
        assert _normalize(parsed.meta_by_name.get("twitter:title", "")) == parsed.title, path
        assert parsed.meta_by_name.get("twitter:description") == parsed.meta_by_name["description"], path

        for key in ("description", "twitter:card", "twitter:title", "twitter:description", "twitter:image"):
            assert parsed.meta_name_counts.get(key) == 1, (path, key)
        for key in (
            "og:type",
            "og:site_name",
            "og:title",
            "og:description",
            "og:url",
            "og:image",
        ):
            assert parsed.meta_property_counts.get(key) == 1, (path, key)

        canonical_links = [
            link.get("href", "") for link in parsed.links if "canonical" in _rel_tokens(link)
        ]
        assert canonical_links == [canonical], (path, canonical_links, canonical)
        assert parsed.meta_by_property.get("og:url") == canonical, path


def test_social_image_uses_the_aipol_share_card_on_the_new_origin() -> None:
    image_paths: set[str] = set()
    for path in _pages():
        parsed = _parse(path)
        image_url = parsed.meta_by_property.get("og:image", "")
        twitter_image = parsed.meta_by_name.get("twitter:image", "")
        split = urlsplit(image_url)

        assert split.scheme == "https" and split.netloc == "aipol.kaps.or.kr", path
        assert split.path == "/assets/og-aipol.png", path
        assert twitter_image == image_url, path
        assert parsed.meta_by_property.get("og:image:width") == "1200", path
        assert parsed.meta_by_property.get("og:image:height") == "630", path
        image_paths.add(split.path)

    assert len(image_paths) == 1, f"pages disagree on the share card: {sorted(image_paths)}"
    image = SITE / image_paths.pop().lstrip("/")
    assert image.exists() and image.stat().st_size > 0, image
    assert _png_dimensions(image) == (1200, 630), image


def test_favicon_and_apple_touch_assets_are_declared_and_valid() -> None:
    favicon_svg = SITE / "assets" / "favicon.svg"
    favicon_ico = SITE / "assets" / "favicon.ico"
    apple_touch = SITE / "assets" / "apple-touch-icon.png"

    assert favicon_svg.exists() and favicon_svg.stat().st_size > 0, favicon_svg
    assert favicon_ico.exists() and favicon_ico.stat().st_size > 0, favicon_ico
    assert apple_touch.exists() and apple_touch.stat().st_size > 0, apple_touch
    assert re.search(r"<svg\b", favicon_svg.read_text(encoding="utf-8"), re.IGNORECASE)
    assert _png_dimensions(apple_touch) == (180, 180)

    ico = favicon_ico.read_bytes()
    reserved, image_type, count = struct.unpack("<HHH", ico[:6])
    assert (reserved, image_type) == (0, 1), "favicon.ico is not a valid ICO container"
    assert len(ico) >= 6 + count * 16, "favicon.ico directory is truncated"
    sizes = {
        (ico[6 + index * 16] or 256, ico[7 + index * 16] or 256)
        for index in range(count)
    }
    assert {(16, 16), (32, 32), (48, 48)} <= sizes

    for path in _pages():
        links = _parse(path).links
        icon_hrefs = {
            link.get("href", "")
            for link in links
            if "icon" in _rel_tokens(link) or "shortcut" in _rel_tokens(link)
        }
        apple_hrefs = {
            link.get("href", "") for link in links if "apple-touch-icon" in _rel_tokens(link)
        }
        assert "/assets/favicon.svg" in icon_hrefs, path
        assert icon_hrefs <= {"/assets/favicon.svg", "/assets/favicon.ico"}, path
        assert apple_hrefs <= {"/assets/apple-touch-icon.png"}, path


def test_official_kaps_event_name_is_verbatim_on_primary_routes() -> None:
    events = _parse(SITE / "events" / "index.html").text
    home = _parse(SITE / "index.html").text
    pension = _parse(SITE / "cases" / "pension" / "index.html").text
    assert "KAPS Human + AI Collaboration Policy Lab" in events
    assert "한국정책학회" in home and "한국정책학회" in pension


def test_placeholder_and_openai_branding_cannot_leak_into_metadata() -> None:
    forbidden = ("starter project", "openai", "open ai policy", "policylab.nextain.io")
    for path in _pages():
        parsed = _parse(path)
        metadata = "\n".join(
            [parsed.title, *parsed.meta_by_name.values(), *parsed.meta_by_property.values()]
        ).casefold()
        for marker in forbidden:
            assert marker not in metadata, (path, marker)


def test_sitemap_uses_current_origin_and_excludes_private_routes() -> None:
    sitemap = SITE / "sitemap.xml"
    root = ET.parse(sitemap).getroot()
    locations = [node.text or "" for node in root.findall("{*}url/{*}loc")]
    assert locations
    assert f"{CANONICAL_ORIGIN}/cases/pension/experiment/" not in locations
    assert f"{CANONICAL_ORIGIN}/cases/pension/process-report/" in locations
    assert f"{CANONICAL_ORIGIN}/cases/pension/experiment/terms/" in locations
    assert f"{CANONICAL_ORIGIN}/cases/pension/experiment/privacy/" in locations
    for location in locations:
        split = urlsplit(location)
        assert f"{split.scheme}://{split.netloc}" == CANONICAL_ORIGIN, location
        assert not (set(Path(split.path).parts) & PRIVATE_ROUTE_PARTS), location

    for path in _pages():
        route_parts = set(Path(_route_for(path)).parts)
        if not route_parts & PRIVATE_ROUTE_PARTS:
            continue
        robots = _parse(path).meta_by_name.get("robots", "").casefold()
        assert "noindex" in robots and "nofollow" in robots, path
        assert f"{CANONICAL_ORIGIN}{_route_for(path)}" not in locations, path


def test_global_admin_is_excluded_from_all_public_discovery_files() -> None:
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    sitemap = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    llms = (SITE / "llms.txt").read_text(encoding="utf-8")

    assert "Disallow: /global/admin/" in robots
    assert "Disallow: /api/global-admin/" in robots
    assert "/global/admin/" not in sitemap
    assert "/api/global-admin/" not in sitemap
    assert "https://aipol.kaps.or.kr/global/admin/" not in llms
    assert "https://aipol.kaps.or.kr/api/global-admin/" not in llms
    assert "Human approval does not itself publish an item" in llms


def test_korean_descriptions_and_titles_do_not_duplicate_brand_suffix() -> None:
    for path in _pages():
        parsed = _parse(path)
        assert "AIPOL — AIPOL" not in parsed.title, path
        if not _route_for(path).startswith("/en/"):
            assert re.search(r"[\uac00-\ud7a3]", parsed.meta_by_name["description"]), path


def test_event_page_is_rehearsal_only_and_uses_confirmed_schedule() -> None:
    events_path = SITE / "events" / "index.html"
    parsed = _parse(events_path)
    source = events_path.read_text(encoding="utf-8")
    assert "2026년 8월 12일 14:30–16:10" in parsed.text
    assert "광주 국립아시아문화전당 국제회의실 B2F · 1분과" in parsed.text
    assert "모바일 투표 2회 예정" in parsed.text
    assert "1차 모바일 투표" in parsed.text and "2차 모바일 투표" in parsed.text
    assert "3차 모바일 투표" not in parsed.text
    pension_source = (SITE / "cases" / "pension" / "index.html").read_text(encoding="utf-8")
    assert 'href="/cases/pension/experiment/' not in pension_source
    assert 'href="/cases/pension/process-report/"' in pension_source
    assert "session.policylab.nextain.io" not in source
    assert "행사 전 안내" in parsed.text


def test_pension_process_report_is_public_static_and_pre_event_scoped() -> None:
    report_path = SITE / "cases" / "pension" / "process-report" / "index.html"
    source = report_path.read_text(encoding="utf-8")
    parsed = _parse(report_path)
    assert "AI 정책개발 프로세스 사전 검증 보고서" in parsed.text
    assert "현장 적용 전 사전 검증" in parsed.text
    assert "1차 100명, 2차 250명" in parsed.text
    assert "25명 검증" not in parsed.text
    assert "실제 시민 참여" not in parsed.text
    assert 'href="/cases/pension/"' in source
    assert 'rel="canonical" href="https://aipol.kaps.or.kr/cases/pension/process-report/"' in source
    assert "<style" not in source
    assert 'src="/assets/site.js"' in source
    assert "cdn.jsdelivr.net" not in source
    assert source.count('class="report-diagram"') == 3


def test_public_copy_scopes_observed_change_and_keeps_logo_approval_gate() -> None:
    home = _parse(SITE / "index.html").text
    rehearsal_path = SITE / "cases" / "pension" / "experiment"
    rehearsal = _parse(rehearsal_path / "index.html").text
    integration_shell = (rehearsal_path / "integration-shell.js").read_text(encoding="utf-8")
    assert "대한민국 최초" not in home
    assert "연금개혁-AI 숙의민주주의 정책실험" in rehearsal
    assert "1·2차 국민숙의 시나리오" in integration_shell
    assert "M1→M2" not in rehearsal + integration_shell
    assert "M2→M3" not in rehearsal + integration_shell
    assert "두 차례 현장 모바일 투표" in _parse(SITE / "status" / "index.html").text
    assert (SITE / "assets" / "partners" / "kaps-logo.svg").exists()
    assert (SITE / "assets" / "partners" / "nextain-logo-light.png").exists()
    provenance = (SITE / "cases" / "pension" / "experiment" / "provenance.json").read_text(
        encoding="utf-8"
    )
    assert "first vote -> AI diagnosis and small-group discussion -> second final vote" in provenance
    assert "fcbae3c0dab18476e2274f9e4ff91dadeb2db944" in provenance


def test_pension_experiment_uses_local_csp_compatible_fonts() -> None:
    experiment = SITE / "cases" / "pension" / "experiment"
    html = (experiment / "index.html").read_text(encoding="utf-8")
    css_href = re.search(r'href="(/cases/pension/experiment/assets/[^"]+\.css)"', html)
    assert css_href is not None
    css = (SITE / css_href.group(1).lstrip("/")).read_text(encoding="utf-8")
    source = (
        ROOT / "integrations" / "kaps-pension-experiment" / "vendor" / "src" / "index.css"
    ).read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in css
    assert "fonts.googleapis.com" not in source
    assert '"Apple SD Gothic Neo"' in css
    assert '"Malgun Gothic"' in css


def test_public_deployment_requires_dev_same_sha_and_browser_gate_before_prod() -> None:
    workflow = (ROOT / ".github" / "workflows" / "deploy-azure-public-site.yml").read_text(
        encoding="utf-8"
    )
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    browser_test = (ROOT / "tests" / "test_public_site_browser.py").read_text(encoding="utf-8")
    deploy_runbook = (ROOT / "deploy" / "azure" / "README.md").read_text(encoding="utf-8")
    assert "environment: aipol-dev" in workflow
    assert "environment: aipol-prod" in workflow
    assert workflow.count("ref: ${{ github.sha }}") == 3
    assert "- deploy-dev" in workflow
    assert "if: ${{ inputs.target == 'prod' }}" in workflow
    assert "python -m playwright install --with-deps chromium webkit" in workflow
    assert "AIPOL_REVIEW_BROWSER_ENGINES: chromium,webkit" in workflow
    assert 'python -m pip install -e ".[test]"' in workflow
    assert "tests/test_public_site_browser.py" in workflow
    assert "tests/test_aipol_review_browser.py" in workflow
    assert "tests/test_aipol_event_tool.py" in workflow
    assert "tests/test_aipol_admin_browser.py" in workflow
    assert "tests/test_aipol_uc_contract.py" in workflow
    assert "tests/test_aipol_portal_preservation.py" in workflow
    assert 'python scripts/verify_live_aipol.py --origin "$LIVE_ORIGIN"' in workflow
    assert '"playwright>=1.58,<2"' in pyproject
    assert 'pytest.importorskip("playwright.sync_api")' in browser_test
    assert "python -m playwright install --with-deps chromium" in deploy_runbook
