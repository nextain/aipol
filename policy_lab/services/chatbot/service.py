"""Approved-only retrieval and citation-enforced answer assembly."""
from __future__ import annotations

import re
from collections.abc import Iterable

from .models import (
    Citation,
    Claim,
    ClaimGenerator,
    ChatAnswer,
    GeneratedAnswer,
    KnowledgeChunk,
    KnowledgeStatus,
)
from .security import injection_signals


ABSTENTION_TEXT = "승인된 근거에서 충분한 답을 찾지 못했습니다. 담당자에게 확인해 주세요."
CONTRADICTION_TEXT = "승인된 근거가 서로 상충하여 확정적으로 답할 수 없습니다. 담당자에게 확인해 주세요."
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_NEGATION = re.compile(
    r"(?:하지\s*않습니다|할\s*수\s*없습니다|아닙니다|없습니다|금지(?:됩니다|합니다)?|"
    r"\b(?:not|never|no|cannot|can't|doesn't|isn't|aren't)\b)", re.IGNORECASE,
)
_STRUCTURED_VALUE_PATTERNS = {
    "date": re.compile(r"\b\d{4}[-./]\d{1,2}(?:[-./]\d{1,2})?\b"),
    "percent": re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:%|퍼센트|percent)(?!\w)", re.IGNORECASE),
    "money": re.compile(
        r"\b\d[\d,]*(?:\.\d+)?\s*(?:만\s*원|억\s*원|조\s*원|원|달러|dollars?)\b",
        re.IGNORECASE,
    ),
    "age": re.compile(r"\b\d[\d,]*(?:\.\d+)?\s*(?:세|years?)\b", re.IGNORECASE),
    "year": re.compile(r"\b\d{4}\s*년\b"),
}
_POLICY_VALUE_GROUPS = (
    tuple(re.compile(value, re.IGNORECASE) for value in (
        r"인상(?:합니다|됩니다|한다|된다)?", r"인하(?:합니다|됩니다|한다|된다)?",
        r"유지(?:합니다|됩니다|한다|된다)?", r"\bincreas(?:e|es|ed|ing)\b",
        r"\bdecreas(?:e|es|ed|ing)\b", r"\bmaintain(?:s|ed|ing)?\b",
    )),
    tuple(re.compile(value, re.IGNORECASE) for value in (
        r"도입(?:합니다|됩니다|한다|된다)?", r"폐지(?:합니다|됩니다|한다|된다)?",
        r"유지(?:합니다|됩니다|한다|된다)?", r"\badopt(?:s|ed|ing)?\b",
        r"\babolish(?:es|ed|ing)?\b", r"\bmaintain(?:s|ed|ing)?\b",
    )),
    tuple(re.compile(value, re.IGNORECASE) for value in (
        r"확대(?:합니다|됩니다|한다|된다)?", r"축소(?:합니다|됩니다|한다|된다)?",
        r"유지(?:합니다|됩니다|한다|된다)?", r"\bexpand(?:s|ed|ing)?\b",
        r"\breduc(?:e|es|ed|ing)\b", r"\bmaintain(?:s|ed|ing)?\b",
    )),
    tuple(re.compile(value, re.IGNORECASE) for value in (
        r"연장(?:합니다|됩니다|한다|된다)?", r"단축(?:합니다|됩니다|한다|된다)?",
        r"유지(?:합니다|됩니다|한다|된다)?", r"\bextend(?:s|ed|ing)?\b",
        r"\bshorten(?:s|ed|ing)?\b", r"\bmaintain(?:s|ed|ing)?\b",
    )),
)


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN.findall(text)}


def _proposition(text: str) -> tuple[set[str], bool]:
    negated = bool(_NEGATION.search(text))
    neutral = _NEGATION.sub(" ", text)
    return _tokens(neutral), negated


def _frame_overlap(left: str, right: str) -> float:
    for pattern in _STRUCTURED_VALUE_PATTERNS.values():
        left, right = pattern.sub(" ", left), pattern.sub(" ", right)
    for group in _POLICY_VALUE_GROUPS:
        for pattern in group:
            left, right = pattern.sub(" ", left), pattern.sub(" ", right)
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _has_structured_value_conflict(left: str, right: str) -> bool:
    if _frame_overlap(left, right) < 0.7:
        return False
    for pattern in _STRUCTURED_VALUE_PATTERNS.values():
        left_values = {"".join(match.group(0).lower().split()) for match in pattern.finditer(left)}
        right_values = {"".join(match.group(0).lower().split()) for match in pattern.finditer(right)}
        # Singleton comparisons avoid treating multi-option/scenario lists as
        # contradictions merely because the lists contain different examples.
        if len(left_values) == len(right_values) == 1 and left_values != right_values:
            return True
    for group in _POLICY_VALUE_GROUPS:
        left_values = {index for index, pattern in enumerate(group) if pattern.search(left)}
        right_values = {index for index, pattern in enumerate(group) if pattern.search(right)}
        if len(left_values) == len(right_values) == 1 and left_values != right_values:
            return True
    return False


def _has_contradictory_evidence(evidence: tuple[KnowledgeChunk, ...]) -> bool:
    propositions = [_proposition(chunk.text) for chunk in evidence]
    for index, (left, left_negated) in enumerate(propositions):
        if not left:
            continue
        for right, right_negated in propositions[index + 1:]:
            if left_negated == right_negated or not right:
                continue
            overlap = len(left & right) / max(1, min(len(left), len(right)))
            if overlap >= 0.7:
                return True
    for index, left in enumerate(evidence):
        for right in evidence[index + 1:]:
            if _has_structured_value_conflict(left.text, right.text):
                return True
    return False


class KnowledgeRepository:
    """Small storage port; production adapters may back it with a database/index."""

    def __init__(self, chunks: Iterable[KnowledgeChunk] = ()) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def put(self, chunk: KnowledgeChunk) -> None:
        self._chunks[chunk.chunk_id] = chunk

    def get(self, chunk_id: str) -> KnowledgeChunk | None:
        return self._chunks.get(chunk_id)

    def approved(self) -> tuple[KnowledgeChunk, ...]:
        return tuple(
            chunk
            for chunk in self._chunks.values()
            if chunk.status is KnowledgeStatus.APPROVED
        )


class GroundedChatbot:
    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        generator: ClaimGenerator | None = None,
        minimum_score: float = 0.2,
        maximum_chunks: int = 4,
        minimum_claim_support: float = 0.2,
    ) -> None:
        if not 0 < minimum_score <= 1 or not 0 < minimum_claim_support <= 1:
            raise ValueError("score thresholds must be in (0, 1]")
        if maximum_chunks < 1:
            raise ValueError("maximum_chunks must be positive")
        self.repository = repository
        self.generator = generator
        self.minimum_score = minimum_score
        self.maximum_chunks = maximum_chunks
        self.minimum_claim_support = minimum_claim_support

    def retrieve(self, query: str) -> tuple[KnowledgeChunk, ...]:
        query_tokens = _tokens(query)
        if not query_tokens:
            return ()
        ranked: list[tuple[float, str, KnowledgeChunk]] = []
        for chunk in self.repository.approved():
            # Approval is editorial status, not permission to execute embedded commands.
            if injection_signals(chunk.text):
                continue
            overlap = len(query_tokens & _tokens(f"{chunk.title} {chunk.text}"))
            score = overlap / len(query_tokens)
            if score >= self.minimum_score:
                ranked.append((score, chunk.chunk_id, chunk))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in ranked[: self.maximum_chunks])

    def ask(self, query: str) -> ChatAnswer:
        if not query.strip():
            return self._abstain("empty_query")
        evidence = self.retrieve(query)
        if not evidence:
            return self._abstain("insufficient_approved_evidence")
        if _has_contradictory_evidence(evidence):
            return self._abstain("contradictory_approved_evidence")
        generated = (
            self.generator.generate(query, evidence)
            if self.generator
            else self._extractive_answer(evidence)
        )
        return self._assemble(generated, evidence)

    def _extractive_answer(
        self, evidence: tuple[KnowledgeChunk, ...]
    ) -> GeneratedAnswer:
        claims: list[Claim] = []
        for chunk in evidence:
            sentence = re.split(r"(?<=[.!?。])\s+|\n+", chunk.text.strip())[0].strip()
            if sentence:
                claims.append(Claim(sentence, (chunk.chunk_id,), (sentence,)))
        return GeneratedAnswer(tuple(claims))

    def _assemble(
        self, generated: GeneratedAnswer, evidence: tuple[KnowledgeChunk, ...]
    ) -> ChatAnswer:
        allowed = {chunk.chunk_id: chunk for chunk in evidence}
        if not generated.claims:
            return self._abstain("generator_abstained")
        ordered_ids: list[str] = []
        for claim in generated.claims:
            if not claim.text.strip() or not claim.citation_chunk_ids or not claim.evidence_quotes:
                return self._abstain("uncited_claim_rejected")
            if any(chunk_id not in allowed for chunk_id in claim.citation_chunk_ids):
                return self._abstain("unknown_citation_rejected")
            cited_texts = tuple(allowed[chunk_id].text for chunk_id in claim.citation_chunk_ids)
            if any(not quote.strip() or not any(quote.strip() in text for text in cited_texts)
                   for quote in claim.evidence_quotes):
                return self._abstain("invalid_evidence_quote_rejected")
            # Public release is extractive-only: the displayed claim itself must
            # be an exact evidence quote. Lexical overlap cannot establish entailment.
            if claim.text.strip() not in {quote.strip() for quote in claim.evidence_quotes}:
                return self._abstain("non_extractive_claim_rejected")
            if any(claim.text.strip() not in text for text in cited_texts):
                return self._abstain("misattributed_citation_rejected")
            for chunk_id in claim.citation_chunk_ids:
                if chunk_id not in ordered_ids:
                    ordered_ids.append(chunk_id)
        number = {chunk_id: index + 1 for index, chunk_id in enumerate(ordered_ids)}
        rendered = " ".join(
            f"{claim.text.rstrip()} "
            + "".join(f"[{number[cid]}]" for cid in claim.citation_chunk_ids)
            for claim in generated.claims
        )
        citations = tuple(
            Citation(
                number=number[chunk_id],
                chunk_id=chunk_id,
                source_id=allowed[chunk_id].source_id,
                title=allowed[chunk_id].title,
                source_url=allowed[chunk_id].source_url,
                content_hash=allowed[chunk_id].content_hash,
            )
            for chunk_id in ordered_ids
        )
        return ChatAnswer(rendered, generated.claims, citations)

    @staticmethod
    def _abstain(reason: str) -> ChatAnswer:
        text = CONTRADICTION_TEXT if reason == "contradictory_approved_evidence" else ABSTENTION_TEXT
        return ChatAnswer(text, abstained=True, reason=reason)
