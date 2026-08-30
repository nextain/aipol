"""Bounded collector that turns allow-listed official feeds and APIs into SourcePackets."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml, application/rss+xml, application/xml, application/json, text/html, text/plain"})
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


def _entry_link(entry: ET.Element | dict[str, object], feed_url: str) -> str:
    if isinstance(entry, dict):
        return urllib.parse.urljoin(feed_url, str(entry.get("html_url") or entry.get("url") or ""))
    if not entry.tag.endswith("}entry"):
        return urllib.parse.urljoin(feed_url, (entry.findtext("link") or "").strip())
    link_node = entry.find("a:link[@rel='alternate']", ATOM)
    if link_node is None:
        link_node = entry.find("a:link", ATOM)
    return urllib.parse.urljoin(feed_url, link_node.attrib.get("href", "")) if link_node is not None else ""


def _entry_datetime(entry: ET.Element | dict[str, object]) -> datetime | None:
    if isinstance(entry, dict):
        raw = str(entry.get("publication_date") or entry.get("published_at") or "").strip()
    elif entry.tag.endswith("}entry"):
        raw = (
            entry.findtext("a:published", default="", namespaces=ATOM)
            or entry.findtext("a:updated", default="", namespaces=ATOM)
            or ""
        ).strip()
    else:
        raw = (entry.findtext("pubDate") or entry.findtext("date") or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw) if "," in raw else datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _feed_items(root: ET.Element) -> list[ET.Element]:
    atom_entries = root.findall("a:entry", ATOM)
    return atom_entries or root.findall("./channel/item")


def _entry_text(entry: ET.Element | dict[str, object]) -> tuple[str, str]:
    if isinstance(entry, dict):
        return (str(entry.get("title") or "").strip(), str(entry.get("abstract") or entry.get("description") or "").strip())
    if entry.tag.endswith("}entry"):
        return (
            (entry.findtext("a:title", default="", namespaces=ATOM) or "").strip(),
            (entry.findtext("a:summary", default="", namespaces=ATOM) or "").strip(),
        )
    return ((entry.findtext("title") or "").strip(), (entry.findtext("description") or "").strip())


def collect(
    *,
    max_items: int = 3,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    fetcher: Callable[..., tuple[bytes, str, str]] = bounded_fetch,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    config_path: Path = CONFIG,
    accept_packet: Callable[[SourcePacket], bool] = lambda _packet: True,
    published_from: datetime | None = None,
    published_before: datetime | None = None,
    diagnostics: dict[str, object] | None = None,
) -> list[SourcePacket]:
    if not 1 <= max_items <= 3:
        raise ValueError("collector max_items must be between 1 and 3")
    for name, value in (("published_from", published_from), ("published_before", published_before)):
        if value is not None and value.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")
    if published_from and published_before and published_from >= published_before:
        raise ValueError("published_from must be earlier than published_before")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    ai_terms = tuple(term.lower() for term in config["ai_terms"])
    relevance_terms = tuple(term.lower() for term in config["relevance_terms"])
    packets: list[SourcePacket] = []
    seen: set[str] = set()
    article_attempts = 0

    feed_entries: list[tuple[dict[str, object], list[ET.Element | dict[str, object]], dict[str, object]]] = []
    feed_diagnostics: list[dict[str, object]] = []
    for feed in config["feeds"]:
        allowed_hosts = {host.lower() for host in feed["allowed_hosts"]}
        report: dict[str, object] = {
            "name": feed["name"], "country": feed.get("country", "International"),
            "status": "ok", "entries": 0, "in_window": 0, "keyword_matches": 0, "selected": 0,
        }
        feed_diagnostics.append(report)
        try:
            feed_body, _, content_type = fetcher(feed["url"], allowed_hosts=allowed_hosts, max_bytes=MAX_FEED_BYTES, timeout=timeout)
            if feed.get("format") == "json" or content_type == "application/json":
                payload = json.loads(feed_body.decode("utf-8"))
                entries = payload.get("results", []) if isinstance(payload, dict) else []
                if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
                    raise CollectionError("official JSON feed has an invalid results collection")
            else:
                root = ET.fromstring(feed_body)
                entries = _feed_items(root)
            if not entries:
                raise CollectionError("official feed contains no usable entries")
        except (CollectionError, ET.ParseError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            report["status"] = "failed"
            report["error_type"] = type(exc).__name__
            continue
        report["entries"] = len(entries)
        feed_entries.append((feed, entries, report))

    if diagnostics is not None:
        diagnostics.update({
            "feeds": feed_diagnostics,
            "feed_successes": len(feed_entries),
            "feed_failures": len(feed_diagnostics) - len(feed_entries),
        })
    if not feed_entries:
        raise CollectionError("all configured official feeds failed")

    # Take one candidate from each feed per round. A busy source therefore
    # cannot consume the whole daily allowance before other official sources
    # are considered.
    round_index = 0
    while len(packets) < max_items and article_attempts < MAX_ARTICLE_ATTEMPTS:
        found_entry = False
        for feed, entries, report in feed_entries:
            if round_index >= len(entries):
                continue
            found_entry = True
            entry = entries[round_index]
            entry_datetime = _entry_datetime(entry)
            if published_from is not None and (entry_datetime is None or entry_datetime < published_from):
                continue
            if published_before is not None and (entry_datetime is None or entry_datetime >= published_before):
                continue
            report["in_window"] = int(report["in_window"]) + 1
            allowed_hosts = {host.lower() for host in feed["allowed_hosts"]}
            title, summary = _entry_text(entry)
            original_searchable = f"{title} {summary}"
            searchable = original_searchable.lower()
            ai_match = any(term in searchable for term in ai_terms) or re.search(r"\bAI\b", original_searchable, flags=re.IGNORECASE)
            if not ai_match or not any(term in searchable for term in relevance_terms):
                continue
            report["keyword_matches"] = int(report["keyword_matches"]) + 1
            url = _entry_link(entry, feed["url"])
            if not url or url in seen or _host(url) not in allowed_hosts:
                continue
            published = entry_datetime.date().isoformat() if entry_datetime else ""
            try:
                article_attempts += 1
                article_body, final_url, content_type = fetcher(url, allowed_hosts=allowed_hosts, max_bytes=MAX_ARTICLE_BYTES, timeout=timeout)
                source_text = visible_text(article_body, content_type)
            except (CollectionError, ValueError):
                # The configured Atom feed is itself an official source. If a
                # linked article is transiently unavailable from the job's
                # network, retain the bounded official feed summary instead of
                # silently losing the candidate. Very short summaries still
                # fail closed.
                source_text = re.sub(r"\s+", " ", summary).strip()
                if len(source_text) < 80:
                    continue
                final_url = url
            try:
                packet = SourcePacket.from_dict({
                    "source_name": feed["name"],
                    "source_url": final_url,
                    "published": published,
                    "country": feed.get("country", "International"),
                    "title": title,
                    "source_text": source_text,
                    "fetched_at": clock().astimezone(timezone.utc).isoformat(),
                })
            except ValueError:
                continue
            seen.add(final_url)
            if accept_packet(packet):
                packets.append(packet)
                report["selected"] = int(report["selected"]) + 1
                if len(packets) >= max_items or article_attempts >= MAX_ARTICLE_ATTEMPTS:
                    break
        if not found_entry:
            break
        round_index += 1
    return packets
