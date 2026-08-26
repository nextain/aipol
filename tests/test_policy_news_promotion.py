from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bots" / "policy_news"))

from promote import public_item, write_public_item  # noqa: E402


def approved_record() -> dict[str, object]:
    return {
        "run_id": "a" * 24,
        "state": "human_approved",
        "source": {
            "published": "2026-08-26", "source_name": "Official Agency",
            "source_url": "https://official.example/item", "country": "Testland",
        },
        "draft": {
            "title_ko": "제목", "summary_ko": "요약", "policy_use": "활용",
            "human_review": "검토", "relevance": "시사점", "caveat": "한계",
        },
        "review": {"verdict": "PASS"},
    }


def test_only_human_approved_pass_record_becomes_public_content(tmp_path: Path) -> None:
    record = approved_record()
    source = tmp_path / "record.json"
    source.write_text(json.dumps(record), encoding="utf-8")
    output = write_public_item(source, tmp_path / "content")
    item = json.loads(output.read_text(encoding="utf-8"))
    assert item["id"] == f"2026-08-26-{'a' * 24}"
    assert item["review_status"] == "AI 4단계 검토·사람 승인·Git 공개 검토"
    with pytest.raises(FileExistsError):
        write_public_item(source, tmp_path / "content")


@pytest.mark.parametrize("state,verdict", [("kb_compiled", "PASS"), ("human_approved", "BLOCK")])
def test_unapproved_or_blocked_record_cannot_be_promoted(state: str, verdict: str) -> None:
    record = approved_record()
    record["state"] = state
    record["review"] = {"verdict": verdict}
    with pytest.raises(ValueError):
        public_item(record)
