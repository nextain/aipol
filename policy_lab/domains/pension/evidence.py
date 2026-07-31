"""연금 근거 앵커 — codex 웹검증 교정 숫자 (spec.md §2).

Provenance: 보건복지부 연금개혁 Q&A·재정계산, 국가법령정보센터.
원문 교차검증: ``tmp/codex-review-out.md`` PART 1.
"""
from __future__ import annotations

import re

from policy_lab.core.evidence import Evidence, EvidenceStore

_ANCHORS = [
    Evidence(
        key="보험료율",
        statement="보험료율 2026년 9.5%에서 매년 0.5%p 인상해 2033년 13% 도달.",
        source="보건복지부 연금개혁",
        as_of="2025 합의 법률",
        value="13%(2033)",
    ),
    Evidence(
        key="소득대체율",
        statement="명목소득대체율 2025년 41.5% → 2026년 43%로 일시 인상.",
        source="보건복지부",
        as_of="2026",
        value="43%(2026)",
    ),
    Evidence(
        key="기금소진",
        statement="5차 재정추계 기준 적립금 소진 2055년(4차 2057년보다 2년 빠름). 2023년 추계 가정.",
        source="국민연금 재정추계전문위원회 5차",
        as_of="2023",
        value="2055",
    ),
    Evidence(
        key="개혁효과기준선",
        statement="정부 개혁효과 기준선은 최신 현행 기준 2056년(5차 자체 현행값 2055와 혼동 주의).",
        source="보건복지부",
        as_of="2025",
        value="2056",
    ),
    Evidence(
        key="자동조정장치",
        statement="자동조정장치는 2025 합의 법률에 미도입·제외('도입 연기'는 해석, 향후 도입 미확정).",
        source="국민연금법 개정",
        as_of="2025",
        value=None,
    ),
    Evidence(
        key="지급보장",
        statement="지급보장은 국민연금법 제3조의2로 명확화(별도 적립금·무제한 재정조달 규정 아님).",
        source="국민연금법 제3조의2",
        as_of="2025",
        value=None,
    ),
]

# 흔한 환각을 잡는 검증 규칙 (라이브 생성물 ↔ 앵커 충돌 검출).
_FORBIDDEN_PATTERNS = [
    (r"자동조정장치[^.\n]{0,20}(도입|시행|적용)", "자동조정장치는 미도입(앵커 위반)"),
    (r"소진[^.\n]{0,6}205[0-4]\b", "기금소진 연도가 앵커(2055)와 다름"),
    (r"보험료율[^.\n]{0,8}1[45]%", "보험료율 상한이 앵커(13%)와 다름"),
]


def _rule(text: str) -> list[str]:
    hits: list[str] = []
    for pat, msg in _FORBIDDEN_PATTERNS:
        if re.search(pat, text):
            hits.append(msg)
    return hits


def pension_evidence() -> EvidenceStore:
    store = EvidenceStore(_ANCHORS)
    store.add_rule(_rule)
    return store
