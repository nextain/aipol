"""Fail a deployment when live AIPOL metadata or bounded public copy regresses."""

from __future__ import annotations

import argparse
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree as ET


HTML_ROUTES = (
    "/",
    "/events/",
    "/cases/pension/experiment/",
    "/cases/pension/experiment/terms/",
    "/cases/pension/experiment/privacy/",
    "/status/",
)
RSS_ROUTE = "/global/rss.xml"
ROUTES = (*HTML_ROUTES, RSS_ROUTE)
SITE_NAME = "AIPOL"
CANONICAL_ORIGIN = "https://aipol.kaps.or.kr"
FORBIDDEN = (
    "aipol.nextain.io",
    "policylab.nextain.io",
)


class _Head(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title = ""
        self.canonical = ""
        self.og: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self.in_title = True
        elif tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href", "")
        elif tag == "meta" and values.get("property", "").startswith("og:"):
            self.og[values["property"]] = values.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data


def fetch(url: str, timeout: float = 10) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "AIPOL-live-smoke/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.geturl(), response.read().decode("utf-8")


def _forbidden_copy(route: str, body: str, failures: list[str]) -> None:
    for marker in FORBIDDEN:
        if marker.casefold() in body.casefold():
            failures.append(f"{route}: forbidden copy {marker!r}")


def _verify_html(route: str, body: str, failures: list[str]) -> None:
    parsed = _Head()
    parsed.feed(body)
    expected = urljoin(f"{CANONICAL_ORIGIN}/", route.lstrip("/"))
    if not parsed.title.strip():
        failures.append(f"{route}: missing title")
    if parsed.canonical != expected:
        failures.append(f"{route}: canonical {parsed.canonical!r} != {expected!r}")
    if parsed.og.get("og:url") != expected:
        failures.append(f"{route}: og:url mismatch")
    if parsed.og.get("og:site_name") != SITE_NAME:
        failures.append(f"{route}: official AIPOL/KAPS og:site_name mismatch")
    if not parsed.og.get("og:title") or not parsed.og.get("og:description"):
        failures.append(f"{route}: incomplete OG title/description")
    if not parsed.og.get("og:image", "").startswith(f"{CANONICAL_ORIGIN}/assets/"):
        failures.append(f"{route}: OG image is not on the canonical origin")
    _forbidden_copy(route, body, failures)


def _verify_rss(route: str, body: str, failures: list[str]) -> None:
    try:
        channel = ET.fromstring(body).find("channel")
    except ET.ParseError:
        channel = None
    if channel is None:
        failures.append(f"{route}: invalid RSS channel")
        return
    if not (channel.findtext("title") or "").startswith("AIPOL"):
        failures.append(f"{route}: RSS title mismatch")
    if channel.findtext("link") != f"{CANONICAL_ORIGIN}/global/":
        failures.append(f"{route}: RSS canonical channel link mismatch")
    if not (channel.findtext("description") or "").strip():
        failures.append(f"{route}: missing RSS description")
    _forbidden_copy(route, body, failures)


def verify(origin: str, attempts: int = 6, delay_seconds: float = 5) -> None:
    split = urlsplit(origin)
    if split.scheme != "https" or not split.netloc or split.username or split.password or split.query:
        raise ValueError("live origin must be a credential-free HTTPS origin")
    origin = f"https://{split.netloc}"
    failures: list[str] = []
    for attempt in range(attempts):
        failures = []
        for route in ROUTES:
            expected = urljoin(f"{origin}/", route.lstrip("/"))
            try:
                final_url, body = fetch(expected)
                if urlsplit(final_url).netloc != split.netloc:
                    failures.append(f"{route}: redirected outside {split.netloc}")
                if route == RSS_ROUTE:
                    _verify_rss(route, body, failures)
                else:
                    _verify_html(route, body, failures)
            except Exception as exc:  # deployment propagation/network failures are retried
                failures.append(f"{route}: {type(exc).__name__}")
        if not failures:
            return
        if attempt + 1 < attempts:
            time.sleep(delay_seconds)
    raise RuntimeError("live AIPOL smoke failed: " + "; ".join(failures))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument("--delay-seconds", type=float, default=5)
    args = parser.parse_args()
    verify(args.origin, max(1, args.attempts), max(0, args.delay_seconds))
    print(f"live AIPOL metadata verified: {args.origin}")


if __name__ == "__main__":
    main()
