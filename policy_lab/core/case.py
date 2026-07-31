"""케이스 정의 (RFC-0002) — 한 차례 숙의의 *콘텐츠*.

도메인 plugin이 ``build_case()`` 로 제공한다. runner/handler 는 이 계약에만 의존하므로
연금을 직접 참조하지 않는다(도메인 중립). 진행안의 ②전문가 1·2안, ⑨수정안 합성 입력,
⑪3지선다 선택지가 여기에 데이터로 담긴다 — instance 하드코딩을 제거한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .levers import PolicyOption


@dataclass(frozen=True)
class VoteOption:
    """투표 선택지 하나. ⑪ 3지선다 = [전문가1안, 전문가2안, AI수정안].

    ``option`` 은 그 선택지가 가리키는 정책안(추적성). ``key`` 는 집계 라벨.
    """

    key: str
    label: str
    option: Optional[PolicyOption] = None  # 가리키는 정책안 (있으면)


@dataclass
class CaseDefinition:
    """한 숙의 케이스의 콘텐츠 (도메인 plugin 소유).

    Attributes:
        version: 케이스 버전 (데이터 추적, codex 2차).
        source: 공개 상태와 버전을 확인할 수 있는 콘텐츠 출처 식별자.
        expert_options: ②전문가 1·2안 (레버 조합 PolicyOption).
        vote_options: ⑪투표 선택지 생성기. context(앞 단계 산출, AI수정안 등)를 받아
            동적으로 [전문가1, 전문가2, AI수정안] 리스트를 만든다.
        synthesis_inputs: ⑨수정안 합성에 넣을 입력 키 (예: audience_choice·expert_opinion·criteria).
    """

    version: str
    source: str
    expert_options: list[PolicyOption]
    vote_options: Callable[[dict], list[VoteOption]]
    synthesis_inputs: list[str] = field(default_factory=list)

    def validate_case(self, domain) -> "CaseDefinition":
        """각 PolicyOption 의 레버값이 도메인 화이트리스트·유효 조합인지 검증.

        codex 2차: 단순 dataclass 가 아니라 검증 계약을 포함해야 한다.
        위반 시 ``GuardViolation`` 으로 fail-fast (잘못된 케이스로 숙의 시작 차단).
        """
        from .guards import GuardViolation

        levers = {lv.key: lv for lv in domain.levers()}
        errors: list[str] = []

        if not self.version or not self.source:
            errors.append("version·source 미기재 (데이터 추적 불가)")
        if len(self.expert_options) < 2:
            errors.append(f"전문가안이 2개 미만: {len(self.expert_options)}")

        for opt in self.expert_options:
            if not opt.lever_values:
                errors.append(f"{opt.name}: 레버값 비어 있음")
            for lk, val in opt.lever_values.items():
                lever = levers.get(lk)
                if lever is None:
                    errors.append(f"{opt.name}: 미정의 레버 {lk!r}")
                elif not lever.allows(val):
                    errors.append(f"{opt.name}: {lk}={val!r} 화이트리스트 밖")

        if errors:
            raise GuardViolation("케이스 검증 실패:\n  - " + "\n  - ".join(errors))
        return self
