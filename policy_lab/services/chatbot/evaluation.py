"""Deterministic release-gate evaluation for retrieval and grounding."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .service import GroundedChatbot


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "evaluation.json"


@dataclass(frozen=True)
class EvaluationThresholds:
    retrieval_recall: float = 1.0
    citation_validity: float = 1.0
    abstention_accuracy: float = 1.0


FIXED_THRESHOLDS = EvaluationThresholds()


@dataclass(frozen=True)
class EvaluationResult:
    retrieval_recall: float
    citation_validity: float
    abstention_accuracy: float

    def passes(self, thresholds: EvaluationThresholds = FIXED_THRESHOLDS) -> bool:
        return (
            self.retrieval_recall >= thresholds.retrieval_recall
            and self.citation_validity >= thresholds.citation_validity
            and self.abstention_accuracy >= thresholds.abstention_accuracy
        )


def evaluate(
    chatbot: GroundedChatbot, fixture_path: Path = FIXTURE_PATH
) -> EvaluationResult:
    fixtures = json.loads(fixture_path.read_text(encoding="utf-8"))
    retrieval_hits = citation_hits = abstention_hits = 0
    retrieval_total = citation_total = abstention_total = 0
    for item in fixtures:
        answer = chatbot.ask(item["query"])
        if item["expected_abstention"]:
            abstention_total += 1
            abstention_hits += int(answer.abstained)
            continue
        expected = set(item["expected_chunk_ids"])
        retrieval_total += 1
        citation_total += 1
        retrieval_hits += int(expected <= {c.chunk_id for c in chatbot.retrieve(item["query"])})
        citation_hits += int(expected <= {c.chunk_id for c in answer.citations})
    return EvaluationResult(
        retrieval_hits / retrieval_total if retrieval_total else 1.0,
        citation_hits / citation_total if citation_total else 1.0,
        abstention_hits / abstention_total if abstention_total else 1.0,
    )

