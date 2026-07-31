"""[1] 다차원 응답 스키마 (RFC-0003 §1).

기존 3지선다(``VoteOption``/단일 ``opt_key``)를 폐기하고, **3개 안 각각에 대해
(수용/조건부/거부) + 조건 텍스트**를 받는다. 이것이 [2] AI 숙의의 유일한 반영 재료이며,
[4] 재의견 수집의 이동 측정 단위다.

계약(RFC-0003 §6):
- *다차원 응답 강제* — 한 시민은 모든 안에 대해 stance를 내야 한다(누락 거부).
- *조건 텍스트 필수* — 조건부 수용은 조건 텍스트가 있어야 한다(빈약하면 [2]가 창작으로 흐름).
이 둘을 dataclass 생성 시점에 fail-fast로 강제한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Stance(str, Enum):
    """한 안에 대한 시민의 수용도 (1차원 점수가 아니라 3단계)."""

    ACCEPT = "accept"            # 수용
    CONDITIONAL = "conditional"  # 조건부 수용 (조건 텍스트 필수)
    REJECT = "reject"            # 완전거부

    @property
    def label(self) -> str:
        return {"accept": "수용", "conditional": "조건부 수용", "reject": "완전거부"}[self.value]


@dataclass(frozen=True)
class ProposalResponse:
    """한 시민의 한 안에 대한 응답.

    text: 조건부=조건("이러면 받아들이겠다"), 거부=사유, 수용=선택적 코멘트.
    조건부인데 text 가 비면 ``ValueError`` (계약: 조건 텍스트 필수).
    """

    proposal_id: str
    stance: Stance
    text: str = ""

    def __post_init__(self) -> None:
        if self.stance == Stance.CONDITIONAL and not self.text.strip():
            raise ValueError(
                f"{self.proposal_id}: 조건부 수용인데 조건 텍스트가 없음 "
                "(RFC-0003 §6 '조건 텍스트 필수')"
            )


@dataclass
class CitizenResponse:
    """한 시민(페르소나)의 전체 응답 — 모든 안에 대해 각각.

    ``proposals`` 는 이 케이스가 묻는 안 id 전체. 빠진 안이 있으면 ``ValueError``
    (계약: 다차원 응답 강제 — 모든 안에 stance).
    """

    pid: str
    segment: str
    model: str
    responses: dict[str, ProposalResponse]  # proposal_id → 응답
    proposals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.proposals:
            missing = [p for p in self.proposals if p not in self.responses]
            if missing:
                raise ValueError(
                    f"{self.pid}: 응답 누락 {missing} "
                    "(RFC-0003 §6 '다차원 응답 강제' — 모든 안에 stance 필요)"
                )

    def stance(self, proposal_id: str) -> Stance | None:
        r = self.responses.get(proposal_id)
        return r.stance if r else None

    def conditions(self) -> list[ProposalResponse]:
        """조건부 수용 응답만 — [2] 합성의 핵심 재료."""
        return [r for r in self.responses.values() if r.stance == Stance.CONDITIONAL]


@dataclass
class ResponseLedger:
    """다차원 응답 집계 (``BallotLedger`` 대체).

    round_id → pid → CitizenResponse. [4] 이동 측정은 두 round 의 stance 비교로 한다.
    """

    rounds: dict[str, dict[str, CitizenResponse]] = field(default_factory=dict)

    def record(self, round_id: str, cr: CitizenResponse) -> None:
        self.rounds.setdefault(round_id, {})[cr.pid] = cr

    def stance_dist(self, round_id: str, proposal_id: str) -> dict[str, int]:
        """한 round·한 안의 (수용/조건부/거부) 분포."""
        out = {s.value: 0 for s in Stance}
        for cr in self.rounds.get(round_id, {}).values():
            st = cr.stance(proposal_id)
            if st is not None:
                out[st.value] += 1
        return out

    def transitions(self, r_from: str, r_to: str, proposal_id: str) -> dict[tuple[str, str], int]:
        """두 round 사이 한 안의 stance 전이 행렬 {(from,to): n}.

        [4] 핵심 — 단 이 전환율 *자체*는 순응으로도 오른다(RFC §4). 차분·placebo·반사실과
        함께 해석해야 한다. 이 메서드는 raw 전이만 제공한다.
        """
        a = self.rounds.get(r_from, {})
        b = self.rounds.get(r_to, {})
        out: dict[tuple[str, str], int] = {}
        for pid in a.keys() & b.keys():
            sa, sb = a[pid].stance(proposal_id), b[pid].stance(proposal_id)
            if sa is not None and sb is not None:
                out[(sa.value, sb.value)] = out.get((sa.value, sb.value), 0) + 1
        return out

    def moved(self, r_from: str, r_to: str, proposal_id: str) -> list[str]:
        """stance 가 바뀐 시민 pid 목록 (한 안)."""
        a = self.rounds.get(r_from, {})
        b = self.rounds.get(r_to, {})
        return [
            pid for pid in a.keys() & b.keys()
            if a[pid].stance(proposal_id) != b[pid].stance(proposal_id)
        ]
