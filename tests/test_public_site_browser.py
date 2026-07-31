"""Browser-level checks for the public static site.

The module skips cleanly when Playwright or a Chromium-family browser is not
installed. Set ``POLICY_LAB_SCREENSHOT_DIR`` to retain visual-review images.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import pytest


playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
ROUTES = (
    "/",
    "/project/",
    "/method/",
    "/platform/",
    "/cases/",
    "/cases/pension/",
    "/cases/pension/experiment/",
    "/cases/pension/experiment/terms/",
    "/cases/pension/experiment/privacy/",
    "/events/",
    "/participate/",
    "/global/",
    "/trust/",
    "/open-source/",
    "/status/",
    "/en/",
    "/en/project/",
    "/en/method/",
    "/en/platform/",
    "/en/cases/",
    "/en/cases/pension/",
    "/en/events/",
    "/en/participate/",
    "/en/global/",
    "/en/trust/",
    "/en/open-source/",
    "/en/status/",
)


def _browser_executable() -> str | None:
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser", "msedge"):
        if path := shutil.which(name):
            return path
    if sys.platform == "win32":
        for candidate in (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ):
            if candidate.exists():
                return str(candidate)
    return None


@pytest.fixture(scope="module")
def site_url():
    if external_url := os.getenv("POLICY_LAB_SITE_URL"):
        yield external_url.rstrip("/")
        return

    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--bind",
            "127.0.0.1",
            "--directory",
            str(SITE),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.05)
    else:
        process.terminate()
        pytest.fail("Static-site preview server did not start")

    yield base_url
    process.terminate()
    process.wait(timeout=5)


@pytest.fixture(scope="module")
def browser():
    executable = _browser_executable()
    if not executable:
        pytest.skip("No Chromium-family browser is installed")
    with playwright.sync_playwright() as runtime:
        instance = runtime.chromium.launch(
            executable_path=executable,
            headless=True,
            args=["--no-sandbox"],
        )
        yield instance
        instance.close()


def _context(browser, **kwargs):
    context = browser.new_context(**kwargs)
    context.route(
        "https://www.googletagmanager.com/**",
        lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
    )
    context.route(
        re.compile(r"https://[^/]*google-analytics\.com/.*"),
        lambda route: route.fulfill(status=204, body=""),
    )
    return context


def test_routes_render_without_browser_errors(browser, site_url):
    context = _context(browser, viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("requestfailed", lambda request: errors.append(f"request failed: {request.url}"))

    for route in ROUTES:
        response = page.goto(f"{site_url}{route}", wait_until="networkidle")
        assert response is not None and response.ok, route
        assert page.locator("h1").count() == 1, route

    assert errors == []
    context.close()


@pytest.mark.parametrize("width,height", [(360, 800), (390, 844), (1440, 1000)])
def test_pages_do_not_overflow_horizontally(browser, site_url, width, height):
    context = _context(browser, viewport={"width": width, "height": height})
    page = context.new_page()
    for route in ROUTES:
        page.goto(f"{site_url}{route}", wait_until="networkidle")
        dimensions = page.evaluate(
            "({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})"
        )
        assert dimensions["scroll"] <= dimensions["client"], (route, width, dimensions)
    context.close()


def test_mobile_menu_keyboard_contract(browser, site_url):
    context = _context(browser, viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto(site_url, wait_until="networkidle")
    toggle = page.locator("[data-nav-toggle]")
    toggle.click()
    assert toggle.get_attribute("aria-expanded") == "true"
    assert page.locator("#site-nav").get_attribute("data-open") == "true"
    page.keyboard.press("Escape")
    assert toggle.get_attribute("aria-expanded") == "false"
    assert toggle.evaluate("element => element === document.activeElement")
    context.close()


def test_core_content_survives_without_javascript(browser, site_url):
    context = _context(browser, java_script_enabled=False)
    page = context.new_page()
    page.goto(site_url, wait_until="load")
    assert page.locator("h1").is_visible()
    assert page.locator("nav a").count() >= 5
    context.close()


@pytest.mark.parametrize("width,height", [(390, 844), (1440, 1000)])
def test_pension_case_starts_in_first_home_view(browser, site_url, width, height):
    context = _context(browser, viewport={"width": width, "height": height})
    page = context.new_page()
    page.goto(site_url, wait_until="networkidle")
    entry = page.locator(".hero-case")
    assert entry.is_visible()
    box = entry.bounding_box()
    assert box is not None and box["y"] < height
    context.close()


def test_capture_review_screenshots(browser, site_url):
    screenshot_dir = os.getenv("POLICY_LAB_SCREENSHOT_DIR")
    if not screenshot_dir:
        pytest.skip("POLICY_LAB_SCREENSHOT_DIR is not set")
    destination = Path(screenshot_dir)
    destination.mkdir(parents=True, exist_ok=True)

    for name, route, viewport in (
        ("home-desktop", "/", {"width": 1440, "height": 1000}),
        ("home-mobile", "/", {"width": 390, "height": 844}),
        ("pension-mobile", "/cases/pension/", {"width": 390, "height": 844}),
    ):
        context = _context(browser, viewport=viewport)
        page = context.new_page()
        page.goto(f"{site_url}{route}", wait_until="networkidle")
        page.screenshot(path=str(destination / f"{name}.png"), full_page=True)
        context.close()
