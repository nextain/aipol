"""연금 영향 모델 (A축) — 방향성·밴드만 산출 (spec.md §3).

의도적으로 단순한 규칙 기반 방향 계산기다. 정밀 추계가 아니다 — 정밀 수치는
외부 추계모형(NABO·복지부·KDI·OECD) 어댑터의 몫(RFC §9 오픈 이슈).
모든 결과는 방향 + 정성/범위 밴드 + 가정을 함께 낸다(허위 정밀성 방어).
"""
from __future__ import annotations

from policy_lab.core.impact import Direction, ImpactModel, ImpactResult


def _is_raise(age_value) -> bool:
    """수급연령 레버 값이 '상향' 방향인지."""
    if isinstance(age_value, (int, float)):
        return age_value >= 66
    return age_value == "단계적 상향"


class PensionImpactModel(ImpactModel):
    """수급연령·국고투입·기초연금 → 재정 지속가능성·세대부담 방향."""

    model_id = "impact:pension-direction-v0"

    _BASE_ASSUMPTIONS = (
        "보험료율·소득대체율은 정부안으로 고정(전제).",
        "방향성 추정 — 정밀 연도/금액은 외부 추계모형 어댑터 필요.",
    )

    def evaluate(self, option) -> list[ImpactResult]:
        lv = option.lever_values
        age = lv.get("수급연령")
        subsidy = lv.get("국고투입")
        basic = lv.get("기초연금")

        # --- 재정 지속가능성 방향 ---
        fiscal = 0
        if _is_raise(age):
            fiscal += 1
        if subsidy == "확대":
            fiscal += 1  # 연금기금 지속가능성은 개선 방향
        if basic == "보편 확대":
            fiscal -= 1
        elif basic == "선별 강화":
            fiscal += 1

        mixed = subsidy == "확대"  # 일반재정 부담과 상충
        if mixed and fiscal > 0:
            fiscal_dir = Direction.MIXED
            fiscal_band = "연금기금 소진 시점은 늦추는 방향, 일반재정 부담은 늘리는 방향(상충)"
        elif fiscal > 0:
            fiscal_dir = Direction.IMPROVES
            fiscal_band = "소진 시점을 다소 늦추는 방향(수년 범위)"
        elif fiscal < 0:
            fiscal_dir = Direction.WORSENS
            fiscal_band = "소진 시점을 앞당기는 방향"
        else:
            fiscal_dir = Direction.NEUTRAL
            fiscal_band = "기준선 대비 방향성 미미"

        # --- 세대별 부담 방향 ---
        if _is_raise(age) and subsidy != "확대":
            gen_dir = Direction.MIXED
            gen_band = "현 수급세대 수급 지연, 미래세대 부담은 완화 방향"
        elif subsidy == "확대":
            gen_dir = Direction.MIXED
            gen_band = "현 세대 급여는 보호, 미래세대 일반재정 부담은 증가 방향"
        else:
            gen_dir = Direction.UNKNOWN
            gen_band = "레버 조합만으로 방향 단정 불가(가정 민감)"

        # --- 노후소득 보장(저소득 노인) 방향 ---
        if basic == "보편 확대":
            basic_dir = Direction.IMPROVES
            basic_band = "저소득 노인 보장 강화 방향, 재정 비용 증가 동반"
        elif basic == "선별 강화":
            basic_dir = Direction.MIXED
            basic_band = "표적 집단 보장 강화 방향, 사각지대·선별 비용 우려"
        else:
            basic_dir = Direction.NEUTRAL
            basic_band = "기초연금 구조 변화 방향성 미미"

        return [
            ImpactResult("재정 지속가능성", fiscal_dir, fiscal_band, self._BASE_ASSUMPTIONS),
            ImpactResult("세대별 부담", gen_dir, gen_band, self._BASE_ASSUMPTIONS),
            ImpactResult("노후소득 보장", basic_dir, basic_band, self._BASE_ASSUMPTIONS),
        ]
