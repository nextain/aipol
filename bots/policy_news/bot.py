"""Discover official AI-policy items for Codex-assisted editorial review.

The bot writes a candidate queue only. Codex currently researches and drafts the
Korean editorial records; the static/RSS builder reads reviewed content files.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "content" / "global-ai-policy"
CONFIG = Path(__file__).with_name("sources.json")
USER_AGENT = "PolicyLabPolicyNewsBot/0.2"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def existing_urls() -> set[str]:
    urls: set[str] = set()
    for path in CONTENT.glob("*.json"):
        urls.add(json.loads(path.read_text(encoding="utf-8"))["source_url"])
    return urls


def discover() -> list[dict[str, str]]:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    ai_terms = tuple(term.lower() for term in config["ai_terms"])
    terms = tuple(term.lower() for term in config["relevance_terms"])
    seen = existing_urls()
    candidates: list[dict[str, str]] = []
    atom = {"a": "http://www.w3.org/2005/Atom"}

    for feed in config["feeds"]:
        root = ET.fromstring(fetch(feed["url"]))
        for entry in root.findall("a:entry", atom):
            title = (entry.findtext("a:title", default="", namespaces=atom) or "").strip()
            summary = (entry.findtext("a:summary", default="", namespaces=atom) or "").strip()
            link_node = entry.find("a:link[@rel='alternate']", atom)
            if link_node is None:
                link_node = entry.find("a:link", atom)
            url = link_node.attrib.get("href", "") if link_node is not None else ""
            url = urllib.parse.urljoin(feed["url"], url)
            host = urllib.parse.urlparse(url).hostname or ""
            if host not in feed["allowed_hosts"] or url in seen:
                continue
            searchable = f"{title} {summary}".lower()
            if not any(term in searchable for term in ai_terms):
                continue
            if not any(term in searchable for term in terms):
                continue
            updated = entry.findtext("a:updated", default="", namespaces=atom)[:10]
            candidates.append({"title": title, "url": url, "published": updated, "source": feed["name"]})
            seen.add(url)
    return candidates


def write_queue(candidates: list[dict[str, str]]) -> tuple[Path, int]:
    inbox = CONTENT / "_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / "candidates.json"
    existing: list[dict[str, str]] = []
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8")).get("candidates", [])
    known = {item["url"] for item in existing}
    additions = [item for item in candidates if item["url"] not in known]
    payload = {
        "discovered_on": date.today().isoformat(),
        "editor": "Codex + human review",
        "candidates": existing + additions,
    }
    if not additions:
        return path, 0
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, len(additions)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-items", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-queue", action="store_true")
    args = parser.parse_args()
    candidates = discover()[: max(0, args.max_items)]
    if args.dry_run or not args.write_queue:
        print(json.dumps(candidates, ensure_ascii=False, indent=2))
        return 0
    if not candidates:
        print("No new official-source candidates.")
        return 0
    path, added = write_queue(candidates)
    print(f"{path.relative_to(ROOT)}: {added} added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
