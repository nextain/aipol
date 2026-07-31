"""개인별 투표 원장 (RFC-0002) — 분포 delta ≠ 개인 전이.

codex 리뷰 결함#7: 기존 ``mind_change`` 는 세그먼트 *분포* delta 만 본다(여론측정 아님,
운영 점검용으로 유지). 그러나 "분포는 11:1 불변인데 개인 6명이 입장 이동"(v6 관찰)을
표현하려면 **개인별 1차→2차→최종 선택 전이**가 필요하다.

participant_id 는 **익명 식별자**(세그먼트+일련번호 등)만 — 실인간 도입 시 F-SEC01 PII 금지
대비. 불변식: 한 (participant, round) 쌍은 한 번만 기록(중복 차단), 라운드 순서 보존.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .guards import GuardViolation


@dataclass
class BallotLedger:
    """개인별 투표 궤적. round 이름 순서대로 각 participant 의 선택을 보존."""

    rounds: list[str] = field(default_factory=list)  # 라운드 이름 순서
    # participant_id -> {round_name: option_key}
    _ballots: dict = field(default_factory=dict)
    # participant_id -> segment_key (집계 분리용)
    _segment: dict = field(default_factory=dict)

    def record(
        self, participant_id: str, segment_key: str, round_name: str, option_key: str
    ) -> None:
        """한 개인의 한 라운드 선택을 기록. 같은 (개인, 라운드) 재기록은 거부."""
        if not participant_id:
            raise GuardViolation("ledger: participant_id 필수 (익명 식별자)")
        if round_name not in self.rounds:
            self.rounds.append(round_name)
        seat = self._ballots.setdefault(participant_id, {})
        if round_name in seat:
            raise GuardViolation(
                f"ledger 불변식 위반: {participant_id} 의 {round_name} 중복 기록"
            )
        seat[round_name] = option_key
        prev = self._segment.get(participant_id)
        if prev is not None and prev != segment_key:
            raise GuardViolation(
                f"ledger: {participant_id} 세그먼트 변경 {prev}→{segment_key} 불가"
            )
        self._segment[participant_id] = segment_key

    def transitions(self, from_round: str, to_round: str) -> dict:
        """두 라운드 사이 개인 전이 행렬 {(from_opt, to_opt): 인원수}.

        분포 delta 와 달리 *누가 어디로 옮겼는지* 를 보존한다 (대각선=유지).
        """
        matrix: dict = {}
        for seat in self._ballots.values():
            a = seat.get(from_round)
            b = seat.get(to_round)
            if a is None or b is None:
                continue
            matrix[(a, b)] = matrix.get((a, b), 0) + 1
        return matrix

    def movers(self, from_round: str, to_round: str) -> list[str]:
        """선택을 *바꾼* 개인 id 목록 (대각선 제외)."""
        out = []
        for pid, seat in self._ballots.items():
            a, b = seat.get(from_round), seat.get(to_round)
            if a is not None and b is not None and a != b:
                out.append(pid)
        return out

    def distribution(self, round_name: str) -> dict:
        """한 라운드의 선택지별 분포 {option_key: count}."""
        out: dict = {}
        for seat in self._ballots.values():
            opt = seat.get(round_name)
            if opt is not None:
                out[opt] = out.get(opt, 0) + 1
        return out

    def distribution_delta(self, from_round: str, to_round: str) -> dict:
        """분포 변화 {option_key: delta} — 개인 전이와 *구분해* 보고."""
        a = self.distribution(from_round)
        b = self.distribution(to_round)
        opts = set(a) | set(b)
        return {o: b.get(o, 0) - a.get(o, 0) for o in opts}

    def to_dict(self) -> dict:
        return {
            "rounds": list(self.rounds),
            "ballots": {p: dict(s) for p, s in self._ballots.items()},
            "segment": dict(self._segment),
        }
