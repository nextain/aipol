"""Bounded collector that turns allow-listed official Atom feeds into SourcePackets."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from contracts import SourcePacket


CONFIG = Path(__file__).with_name("sources.json")
USER_AGENT = "AIPOLPolicyNewsCollector/1.0 (+https://aipol.kaps.or.kr)"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
MAX_FEED_BYTES = 1_000_000
MAX_ARTICLE_BYTES = 300_000
MAX_SOURCE_CHARS = 24_000
MAX_ARTICLE_ATTEMPTS = 9
DEFAULT_TIMEOUT_SECONDS = 20


class CollectionError(RuntimeError):
    pass


def _host(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CollectionError("collector URLs must be absolute HTTPS URLs without credentials")
    return parsed.hostname.lower()


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urllib.parse.urljoin(req.full_url, newurl)
        if _host(target) not in self.allowed_hosts:
            raise CollectionError("redirect target is not allow-listed")
        return super().redirect_request(req, fp, code, msg, headers, target)


def bounded_fetch(url: str, *, allowed_hosts: set[str], max_bytes: int, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[bytes, str, str]:
    if _host(url) not in allowed_hosts:
        raise CollectionError("URL host is not allow-listed")
    opener = urllib.request.build_opener(_AllowlistRedirectHandler(allowed_hosts))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/xml, text/html, text/plain"})
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            if _host(final_url) not in allowed_hosts:
                raise CollectionError("final response host is not allow-listed")
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                raise CollectionError("response exceeds configured byte limit")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise CollectionError("response exceeds configured byte limit")
            content_type = response.headers.get_content_type()
            return body, final_url, content_type
    except CollectionError:
        raise
    except Exception as exc:
        raise CollectionError(f"bounded fetch failed: {type(exc).__name__}") from exc


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[no-untyped-def]
        if tag.lower() in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "nav", "footer"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def visible_text(body: bytes, content_type: str) -> str:
    decoded = body.decode("utf-8", errors="replace")
    if content_type in {"text/html", "application/xhtml+xml"} or "<html" in decoded[:1000].lower():
        parser = _VisibleTextParser()
        parser.feed(decoded)
        text = "\n".join(parser.parts)
    else:
        text = re.sub(r"<[^>]+>", " ", decoded)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise CollectionError("official source contains no usable text")
    return text[:MAX_SOURCE_CHARS]


def _entry_link(entry: ET.Element, feed_url: str) -> str:
    link_node = entry.find("a:link[@rel='alternate']", ATOM)
    if link_node is None:
        link_node = entry.find("a:link", ATOM)
    return urllib.parse.urljoin(feed_url, link_node.attrib.get("href", "")) if link_node is not None else ""


def collect(
    *,
    max_items: int = 3,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    fetcher: Callable[..., tuple[bytes, str, str]] = bounded_fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    config_path: Path = CONFIG,
) -> list[SourcePacket]:
    if not 1 <= max_items <= 3:
        raise ValueError("collector max_items must be between 1 and 3")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    ai_terms = tuple(term.lower() for term in config["ai_terms"])
    relevance_terms = tuple(term.lower() for term in config["relevance_terms"])
    packets: list[SourcePacket] = []
    seen: set[str] = set()
    article_attempts = 0

    for feed in config["feeds"]:
        if len(packets) >= max_items or article_attempts >= MAX_ARTICLE_ATTEMPTS:
            break
        allowed_hosts = {host.lower() for host in feed["allowed_hosts"]}
        feed_body, _, _ = fetcher(feed["url"], allowed_hosts=allowed_hosts, max_bytes=MAX_FEED_BYTES, timeout=timeout)
        try:
            root = ET.fromstring(feed_body)
        except ET.ParseError as exc:
            raise CollectionError("official feed is malformed XML") from exc
        for entry in root.findall("a:entry", ATOM):
            if len(packets) >= max_items or article_attempts >= MAX_ARTICLE_ATTEMPTS:
                break
            title = (entry.findtext("a:title", default="", namespaces=ATOM) or "").strip()
            summary = (entry.findtext("a:summary", default="", namespaces=ATOM) or "").strip()
            original_searchable = f"{title} {summary}"
            searchable = original_searchable.lower()
            ai_match = any(term in searchable for term in ai_terms) or re.search(r"\bAI\b", original_searchable, flags=re.IGNORECASE)
            if not ai_match or not any(term in searchable for term in relevance_terms):
                continue
            url = _entry_link(entry, feed["url"])
            if not url or url in seen or _host(url) not in allowed_hosts:
                continue
            published = (entry.findtext("a:published", default="", namespaces=ATOM) or entry.findtext("a:updated", default="", namespaces=ATOM) or "")[:10]
            try:
                article_attempts += 1
                article_body, final_url, content_type = fetcher(url, allowed_hosts=allowed_hosts, max_bytes=MAX_ARTICLE_BYTES, timeout=timeout)
                source_text = visible_text(article_body, content_type)
                packet = SourcePacket.from_dict({
                    "source_name": feed["name"],
                    "source_url": final_url,
                    "published": published,
                    "country": feed.get("country", "International"),
                    "title": title,
                    "source_text": source_text,
                    "fetched_at": clock().astimezone(timezone.utc).isoformat(),
                })
            except (CollectionError, ValueError):
                # A single oversized, malformed or moved article does not abort
                # the bounded run; it is skipped without a provider call.
                continue
            packets.append(packet)
            seen.add(final_url)
    return packets
