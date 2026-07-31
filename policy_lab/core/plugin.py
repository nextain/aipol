"""도메인 플러그인 인터페이스 (RFC §8).

도메인(연금·기후·주거 …)은 레버·근거·영향모델·세그먼트·프롬프트를 제공한다.
프로토콜·방어장치·오케스트레이터는 도메인과 무관하게 공유된다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .case import CaseDefinition
from .deliberation import DeliberationProtocol, Segment
from .evidence import EvidenceStore
from .impact import ImpactModel
from .levers import FixedVariable, Lever
from .prompts import Prompt
from .protocols import standard_deliberation


class DomainPlugin(ABC):
    """한 정책 도메인을 캡슐화한 플러그인."""

    key: str = "abstract"
    label: str = "Abstract domain"

    @abstractmethod
    def levers(self) -> list[Lever]:
        """변화 변수 레버."""

    @abstractmethod
    def fixed_variables(self) -> list[FixedVariable]:
        """고정 전제 변수."""

    @abstractmethod
    def evidence(self) -> EvidenceStore:
        """출처·버전 고정 근거 베이스."""

    @abstractmethod
    def impact_model(self) -> ImpactModel:
        """A축 결정론 영향 모델."""

    @abstractmethod
    def segments(self) -> list[Segment]:
        """청중 세그먼트 정의."""

    @abstractmethod
    def prompts(self) -> dict[str, Prompt]:
        """단계별 프롬프트 (key -> Prompt)."""

    @abstractmethod
    def build_case(self) -> CaseDefinition:
        """이 도메인의 숙의 케이스 콘텐츠 (RFC-0002).

        ②전문가 1·2안, ⑨수정안 합성 입력, ⑪3지선다 선택지를 데이터로 제공한다.
        runner/handler 는 이 케이스에만 의존하므로 instance 하드코딩이 사라진다.
        """

    def protocol(self) -> DeliberationProtocol:
        """숙의 프로토콜. 기본 = 표준 12단계. 도메인이 override 가능.

        기본 구현은 ``audience_query`` 단계의 화이트리스트를 도메인 레버로 채운다.
        """
        proto = standard_deliberation()
        lever_keys = tuple(lv.key for lv in self.levers())
        for st in proto.stages:
            if st.type.value == "audience_query":
                st.whitelist_lever_keys = lever_keys
        return proto
