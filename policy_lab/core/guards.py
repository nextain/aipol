"""방어장치 — red-team 약점을 프레임워크가 *강제*로 막는 가드 (RFC §6).

이 모듈이 policy-lab의 학술적 기여 포인트다. 진행안이 약점을 연출 의도로
명문화했다면, 여기서는 그 약점을 코드로 차단한다.
의존성 없음(독립 모듈) — 순환 import을 피한다.
"""
from __future__ import annotations

import re
from enum import Enum


class GuardViolation(Exception):
    """방어장치 위반. 라이브 운영 중 fail-fast 시킨다."""


# 범위·정성·불확실성을 나타내는 토큰. 하나라도 있으면 "단일 정밀 숫자"가 아님.
_RANGE_TOKENS = (
    "~", "-", "–", "—", "±", "/",
    "부터", "까지", "이상", "이하", "내외", "안팎", "약", "방향",
    "범위", "정도", "수준", "가량", "에서", "전후", "초과", "미만",
)

# 숫자(쉼표·소수점 포함) + 선택적 한글/퍼센트 단위 하나로만 구성된 문자열.
_SINGLE_NUMBER = re.compile(r"^[\d,.]+\s*[%년조원세배명p]?$")


def reject_single_number(text: str) -> None:
    """단일 정밀 숫자를 권위로 제시하는 것을 차단.

    범위/정성 표현(``~``, ``±``, "약", "방향" 등)이 있으면 통과.
    순수 단일 숫자(+단위)면 ``GuardViolation``.
    """
    if not text:
        return
    t = text.strip()
    if not t:
        return
    if any(tok in t for tok in _RANGE_TOKENS):
        return
    if _SINGLE_NUMBER.match(t):
        raise GuardViolation(
            f"단일 정밀 숫자를 권위로 제시할 수 없음: {text!r}. "
            "방향성·불확실성 밴드로 표현하세요."
        )


def assert_ab_separation(
    impact_model_ids: set[str], deliberation_model_ids: set[str]
) -> None:
    """A(영향 모델)와 B(공론 LLM)가 같은 모델을 공유하면 거부.

    폐루프 오류 증폭 방어 — A·B는 다른 모델·데이터·프레이밍을 써야 한다.
    """
    shared = {m for m in impact_model_ids & deliberation_model_ids if m}
    if shared:
        raise GuardViolation(
            f"A/B 분리 위반: 영향 모델(A)과 공론 루프(B)가 같은 모델 공유 {sorted(shared)}"
        )


def assert_within_whitelist(lever, value) -> None:
    """청중 변수 질문이 도메인 화이트리스트 범위 안인지 (인젝션 방어)."""
    if not lever.allows(value):
        raise GuardViolation(
            f"화이트리스트 위반: {lever.key}={value!r} 는 허용 범위 밖"
        )


class HumanGate:
    """AI 산출물(쟁점정리 등)을 전문가 승인 전에는 청중에 노출 금지.

    프레이밍 권력 방어 — ``release()`` 는 ``approve()`` 없이는 실패한다.
    """

    def __init__(self, content: object) -> None:
        self.content = content
        self._approved_by: str | None = None

    @property
    def approved(self) -> bool:
        return self._approved_by is not None

    @property
    def approved_by(self) -> str | None:
        return self._approved_by

    def approve(self, expert: str) -> "HumanGate":
        if not expert:
            raise GuardViolation("human_gate: 승인자(전문가)를 명시해야 함")
        self._approved_by = expert
        return self

    def release(self) -> object:
        if not self.approved:
            raise GuardViolation(
                "human_gate: 전문가 승인 없이 청중 노출 불가 (프레이밍 권력 방어)"
            )
        return self.content


class MeasurementPurpose(str, Enum):
    """리허설/실험 인스턴스가 무엇을 측정하는지 — 목적 단위 (AI 리뷰 06: codex '목적 혼재')."""

    OPERATIONAL = "operational"                  # 운영 점검(인코딩·형식·게이트 흐름)
    FRAMING_SENSITIVITY = "framing_sensitivity"  # 프레이밍 민감도
    OPINION_MEASUREMENT = "opinion_measurement"  # 여론 측정 — 리허설에서 금지


def assert_declared_purpose(purposes) -> None:
    """리허설 인스턴스는 목적을 명시 선언해야 하며, 여론 측정을 목적으로 둘 수 없다.

    목적 단위 혼재(운영/여론/민감도)가 결과를 여론조사처럼 읽히게 만드는 것을 막는다.
    AI 페르소나 ≠ 실제 청중이므로 ``OPINION_MEASUREMENT``는 금지.
    """
    purposes = list(purposes or [])
    if not purposes:
        raise GuardViolation(
            "목적 단위 미선언 — 인스턴스는 무엇을 측정/비측정하는지 선언해야 함"
        )
    if MeasurementPurpose.OPINION_MEASUREMENT in purposes:
        raise GuardViolation(
            "여론 측정은 리허설의 목적이 될 수 없음 (AI 페르소나 ≠ 실제 청중)"
        )


# '여론/민의/실제 청중/국민/시민(들)이 ~을 찬성/반대/지지/선호한다'는 단정 패턴.
_OPINION_CLAIM = re.compile(
    r"(여론|민의|실제\s*청중|국민|시민들?)[은는이가]?\s*[^.\n]{0,24}"
    r"(찬성|반대|지지|선호|원한다|바란다)"
)


def assert_not_opinion_claim(text: str) -> None:
    """리허설 결과 텍스트가 '여론/실제 청중이 ~을 지지/반대한다'고 단정하면 차단.

    수치를 '시뮬 조건의 응답 패턴'이 아니라 실제 여론으로 전면화하는 오용을 막는다.
    """
    if not text:
        return
    if _OPINION_CLAIM.search(text):
        raise GuardViolation(
            "리허설 결과를 여론/실제 청중 선호로 단정할 수 없음 — "
            "'시뮬 조건의 응답 패턴(여론 아님)'으로만 표기하세요."
        )
