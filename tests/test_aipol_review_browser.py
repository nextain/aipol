"""교수 검토 전용 화면의 모바일·격리 브라우저 계약."""
from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import Route, sync_playwright


ROOT = Path(__file__).parents[1]
WEB = ROOT / "event-tool" / "web"
EXPERIMENT_ID = "experiment-review-browser"
STAGES = [
    ("intro", "실험 안내"),
    ("expert-options", "전문가 A/B/C안"),
    ("m1-result", "M1 단순 투표 결과"),
    ("personal-impact", "개인 조건별 영향"),
    ("m2-result", "M2 구조화 평가 결과"),
    ("t6-analysis", "T6 변수별 특성"),
    ("d", "A/B/C와 M2로 만든 D안"),
    ("expert-audience", "전문가·선정 청중 의견"),
    ("d-prime", "의견을 반영한 D′안"),
    ("m3-result", "A/B/C/D′ 최종 평가"),
    ("closing", "마무리"),
]


def _catalog() -> dict:
    return json.loads(
        (ROOT / "event-tool" / "review-catalogs" / "pension-professor-review-v1.json")
        .read_text("utf-8")
    )


def test_professor_review_scrubs_token_navigates_resets_and_never_mutates():
    catalog = _catalog()
    requests: list[tuple[str, str]] = []
    console_errors: list[str] = []

    def route_request(route: Route) -> None:
        request = route.request
        requests.append((request.method, request.url))
        path = request.url.split("https://aipol.example", 1)[-1].split("?", 1)[0]
        if path == "/api/aipol/review/exchange":
            route.fulfill(
                status=204,
                headers={"Set-Cookie": "aipol_review_session=session-fixture; Secure; HttpOnly; SameSite=Strict"},
                body="",
            )
            return
        if path == f"/api/aipol/review/{EXPERIMENT_ID}/catalog":
            stage = request.url.split("stage=", 1)[-1] if "stage=" in request.url else "intro"
            route.fulfill(
                status=200,
                content_type="application/json",
                headers={"Cache-Control": "no-store"},
                body=json.dumps({
                    "catalog": {key: value for key, value in catalog.items() if key != "source_contract"},
                    "current_stage_id": stage, "snapshot_hash": "f" * 64,
                    "expires_at": "2026-08-10T09:00:00+09:00", "scope": "national-pension-only",
                }),
            )
            return
        asset = {
            "/aipol-review.html": ("text/html", WEB / "aipol-review.html"),
            "/aipol-review.js": ("text/javascript", WEB / "aipol-review.js"),
            "/aipol-review.css": ("text/css", WEB / "aipol-review.css"),
        }.get(path)
        if asset:
            content_type, filename = asset
            route.fulfill(status=200, content_type=content_type, body=filename.read_text("utf-8"))
            return
        route.fulfill(status=404, body="not found")

    with sync_playwright() as runtime:
        engines = os.environ.get("AIPOL_REVIEW_BROWSER_ENGINES", "chromium").split(",")
        for engine in engines:
            browser = getattr(runtime, engine.strip()).launch(headless=True)
            for width in (320, 390, 430):
                review_token = f"review-browser-{engine}-{width}." + "x" * 43
                context = browser.new_context(viewport={"width": width, "height": 844})
                context.route("https://aipol.example/**", route_request)
                page = context.new_page()
                page.on(
                    "console",
                    lambda message: console_errors.append(message.text)
                    if message.type == "error" else None,
                )
                page.goto(
                    f"https://aipol.example/aipol-review.html?experiment={EXPERIMENT_ID}"
                    f"#review_token={review_token}"
                )
                page.locator("#review-content").filter(has_text="실험 안내").wait_for()
                assert page.evaluate("location.hash") == ""
                assert review_token not in page.url
                assert page.locator("#review-disclosure").get_attribute("hidden") is None
                assert "합성 예시" in page.locator("#review-disclosure").inner_text()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                assert page.evaluate("localStorage.length") == 0
                assert page.evaluate("sessionStorage.length") == 0

                for stage_id, title in STAGES[1:]:
                    page.locator("#review-next").click()
                    page.locator("#review-content").filter(has_text=title).wait_for()
                    if stage_id == "expert-options":
                        assert "초기 100조원 + 이후 매년 GDP 0.25%" in page.locator("#review-content").inner_text()
                    if stage_id == "personal-impact":
                        rendered = page.locator("#review-content").inner_text()
                        assert "현재 나이" in rendered and "83.5세 기준 예상 생애 총수급액" in rendered
                    if stage_id == "m3-result":
                        rendered = page.locator("#review-content").inner_text()
                        assert "A/B/C/D′" in rendered and "M1→M2→M3 선택 변화" in rendered
                page.locator("#review-reset").click()
                page.locator("#review-content").filter(has_text="실험 안내").wait_for()
                context.close()
            browser.close()

    assert not console_errors
    forbidden = ("/participants", "/measurements/", "/exposures/", "/withdraw", "/api/admin/")
    assert not [url for method, url in requests if method != "GET" and any(item in url for item in forbidden)]
    assert sum(1 for method, url in requests if method == "POST" and url.endswith("/review/exchange")) == 3 * len(engines)


def test_professor_review_retries_transient_exchange_and_catalog_once():
    catalog = _catalog()
    attempts = {"exchange": 0, "expert-options": 0}

    def route_request(route: Route) -> None:
        request = route.request
        path = request.url.split("https://aipol.example", 1)[-1].split("?", 1)[0]
        if path == "/api/aipol/review/exchange":
            attempts["exchange"] += 1
            if attempts["exchange"] == 1:
                route.fulfill(status=503, body="temporarily unavailable")
            else:
                route.fulfill(status=204, body="")
            return
        if path == f"/api/aipol/review/{EXPERIMENT_ID}/catalog":
            stage = request.url.split("stage=", 1)[-1] if "stage=" in request.url else "intro"
            if stage == "expert-options":
                attempts["expert-options"] += 1
                if attempts["expert-options"] == 1:
                    route.fulfill(status=503, body="temporarily unavailable")
                    return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "catalog": {key: value for key, value in catalog.items() if key != "source_contract"},
                    "current_stage_id": stage,
                    "snapshot_hash": "f" * 64,
                    "expires_at": "2026-08-10T09:00:00+09:00",
                    "scope": "national-pension-only",
                }),
            )
            return
        asset = {
            "/aipol-review.html": ("text/html", WEB / "aipol-review.html"),
            "/aipol-review.js": ("text/javascript", WEB / "aipol-review.js"),
            "/aipol-review.css": ("text/css", WEB / "aipol-review.css"),
        }.get(path)
        if asset:
            content_type, filename = asset
            route.fulfill(status=200, content_type=content_type, body=filename.read_text("utf-8"))
            return
        route.fulfill(status=404, body="not found")

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.route("https://aipol.example/**", route_request)
        page = context.new_page()
        page.goto(
            f"https://aipol.example/aipol-review.html?experiment={EXPERIMENT_ID}"
            "#review_token=retry-seat." + "x" * 43
        )
        page.locator("#review-status").filter(has_text="지연").wait_for()
        page.locator("#review-retry").click()
        page.locator("#review-content").filter(has_text="실험 안내").wait_for()
        page.locator("#review-next").click()
        page.locator("#review-status").filter(has_text="지연").wait_for()
        page.locator("#review-retry").click()
        page.locator("#review-content").filter(has_text="전문가 A/B/C안").wait_for()
        assert page.locator(".table-scroll[role=region]").first.get_attribute("aria-label")
        assert page.locator("table caption").first.inner_text() == "정책안 비교"
        context.close()
        browser.close()

    assert attempts == {"exchange": 2, "expert-options": 2}
