"""Solar draft -> Nemotron adversarial review pipeline.

The pipeline fails closed: a missing key, provider failure, malformed response,
or any review issue blocks publication and leaves a review artifact in inbox.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import nemotron_review
import solar_adapter


ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "content" / "global-ai-policy"
INBOX = CONTENT / "_inbox"


def safe_id(packet: dict[str, str]) -> str:
    supplied = packet.get("id", "").strip()
    if supplied and re.fullmatch(r"[a-z0-9][a-z0-9-]{5,119}", supplied):
        return supplied
    published = packet.get("published") or date.today().isoformat()
    title = re.sub(r"[^a-z0-9]+", "-", packet.get("title", "policy-ai").lower()).strip("-")
    digest = hashlib.sha256(packet.get("source_url", "").encode("utf-8")).hexdigest()[:10]
    return f"{published}-{title[:58] or 'policy-ai'}-{digest}"


def process(packet: dict[str, str], upstage_key: str, openrouter_key: str) -> tuple[dict, dict | None]:
    draft = solar_adapter.draft(packet, os.getenv("UPSTAGE_MODEL", solar_adapter.DEFAULT_MODEL), upstage_key)
    adversarial = nemotron_review.review(packet, draft, openrouter_key)
    evidence = {
        "id": safe_id(packet),
        "source_url": packet["source_url"],
        "solar_model": draft["model"],
        "adversarial_review": adversarial,
        "publication_allowed": adversarial["verdict"] == "PASS",
    }
    if adversarial["verdict"] != "PASS":
        return evidence, None
    record = {
        "id": evidence["id"],
        "published": packet["published"],
        "source_name": packet["source_name"],
        "source_url": packet["source_url"],
        "country": packet["country"],
        **{key: draft[key] for key in sorted(solar_adapter.OUTPUT_FIELDS)},
        "review_status": "Solar Open2 초안 · Nemotron 3 Ultra 원문 대조 적대 검토 통과",
    }
    return evidence, record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_packet", type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    upstage_key = solar_adapter.resolve_api_key()
    openrouter_key = nemotron_review.api_key()
    if not upstage_key or not openrouter_key:
        print("UPSTAGE_KEY and OPENROUTER_API_KEY are required; publication blocked", file=sys.stderr)
        return 2
    packet = json.loads(args.source_packet.read_text(encoding="utf-8"))
    evidence, record = process(packet, upstage_key, openrouter_key)
    INBOX.mkdir(parents=True, exist_ok=True)
    evidence_path = INBOX / f"{evidence['id']}.review.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if record is None:
        print(f"BLOCKED: {evidence_path.relative_to(ROOT)}")
        return 1
    if not args.publish:
        print(f"PASS (review-only): {evidence_path.relative_to(ROOT)}")
        return 0
    output = CONTENT / f"{record['id']}.json"
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PUBLISHED CONTENT RECORD: {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
