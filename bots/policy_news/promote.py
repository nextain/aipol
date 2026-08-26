"""Convert one sanitized, human-approved run record into public content.

The command only prepares a Git change. It cannot approve, publish, deploy, or
read the private source container, so the human and repository review gates
remain separate.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PUBLIC_FIELDS = ("title_ko", "summary_ko", "policy_use", "human_review", "relevance", "caveat")


def public_item(record: dict[str, object]) -> dict[str, str]:
    if record.get("state") != "human_approved":
        raise ValueError("only a human_approved record may enter the public repository")
    source = record.get("source")
    draft = record.get("draft")
    review = record.get("review")
    if not isinstance(source, dict) or not isinstance(draft, dict) or not isinstance(review, dict):
        raise ValueError("approved record is missing sanitized source, draft, or review fields")
    if review.get("verdict") != "PASS":
        raise ValueError("human approval cannot promote a non-PASS AI review")
    run_id = str(record.get("run_id", ""))
    if not re.fullmatch(r"[a-f0-9]{24}", run_id):
        raise ValueError("run_id must be the deterministic 24-character hex identifier")
    item = {
        "id": f"{source.get('published', '')}-{run_id}",
        "published": str(source.get("published", "")),
        "source_name": str(source.get("source_name", "")),
        "source_url": str(source.get("source_url", "")),
        "country": str(source.get("country", "International")),
        **{field: str(draft.get(field, "")) for field in PUBLIC_FIELDS},
        "review_status": "AI 4단계 검토·사람 승인·Git 공개 검토",
    }
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["published"]):
        raise ValueError("published must use YYYY-MM-DD")
    if not item["source_url"].startswith("https://") or any(not item[field].strip() for field in item):
        raise ValueError("public record fields must be non-empty and source_url must be HTTPS")
    return item


def write_public_item(record_path: Path, output_dir: Path) -> Path:
    item = public_item(json.loads(record_path.read_text(encoding="utf-8")))
    output = output_dir / f"{item['id']}.json"
    if output.exists():
        raise FileExistsError(f"public item already exists: {output.name}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path, help="sanitized policy-news run record JSON")
    parser.add_argument("--output-dir", type=Path, default=Path("content/global-ai-policy"))
    args = parser.parse_args()
    print(write_public_item(args.record, args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
