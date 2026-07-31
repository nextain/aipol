"""[4] 재의견 측정 — 차분·통제·반사실 (RFC-0003 §4).

이 프로젝트의 채점표. 리뷰 치명: **절대 전환율은 안 품질이 아니라 시민 모델의 순응성을
잰다**(Solar 99% = 합의 아님). 그래서 절대값을 버리고:

  - **3-arm**(§4.1): 진짜 통합안 ① / 음성 더미 ② / 부정 통제 ③ 를 같은 시민에게.
    작동 인정 = `①Δ=①−② 유의 양(+)` **그리고** `③<②`. 안 서면 "순응 재생산"으로 기각.
  - **모델 불변성**(§4.2): 순응형·일관형 ≥2 시민모델에서 ①Δ 부호 일관. 한 모델만 점수 나면 실격.
  - **반사실**(§4.3): "반영"=텍스트 매칭 아니라 **행동** — 조항 제거 시 전환 철회하면 진짜 반영,
    안 하면 그 전환은 순응이었다(자기보고 위조 우회).
  - **집단 형평**(§4.4): 집단별 ①Δ + 집단별 미반영률, **사전** 임계(사후 선택 봉쇄).

통계는 닫힌형(두 비율 z검정)으로 결정론. 난수 없음.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .guards import GuardViolation
from .responses import Stance, ResponseLedger


# accept > conditional > reject — 수용 방향 개선의 순서
_ORDER = {Stance.REJECT: 0, Stance.CONDITIONAL: 1, Stance.ACCEPT: 2}


def improved(before: Stance, after: Stance) -> bool:
    """제시 후 수용 방향으로 움직였나 (reject→conditional→accept)."""
    return _ORDER[after] > _ORDER[before]


class Arm(str, Enum):
    """3-arm — 순응 기저선을 빼내기 위한 세 제시(§4.1)."""

    REAL = "real"          # ① 진짜 통합안 (시민 조건 반영)
    DUMMY = "dummy"        # ② 음성 더미 (같은 형식·권위·분량, 조건 미반영)
    NEGATIVE = "negative"  # ③ 부정 통제 (시민 조건과 반대로)


@dataclass(frozen=True)
class ArmObservation:
    """한 시민이 한 arm 제시 전후로 보인 입장 (한 안에 대해)."""

    pid: str
    segment: str
    citizen_model: str
    arm: Arm
    before: Stance
    after: Stance

    @property
    def moved(self) -> bool:
        return improved(self.before, self.after)


# ── 두 비율 z검정 (닫힌형, 결정론) ──────────────────────────────────────


def _norm_sf(z: float) -> float:
    """표준정규 상측 확률 P(Z>z) — erf 닫힌형."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def two_prop_ztest(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float]:
    """단측 두 비율 z검정 (집단1 > 집단2 가설). 반환 (z, p_one_sided).

    n=0 또는 분산 0 이면 (0.0, 1.0)(판정 불가 → 유의 아님으로 보수 처리).
    """
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1.0 - p) * (1.0 / n1 + 1.0 / n2))
    if se == 0.0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    return z, _norm_sf(z)


# ── 4.1 3-arm placebo ───────────────────────────────────────────────────


def _arm_counts(obs: list[ArmObservation], arm: Arm) -> tuple[int, int]:
    """(이동 수, 전체 수) for one arm."""
    a = [o for o in obs if o.arm == arm]
    return sum(1 for o in a if o.moved), len(a)


@dataclass(frozen=True)
class PlaceboResult:
    """3-arm 차분 결과 — 절대값이 아니라 이 Δ·부등식이 채점(§4.1)."""

    rate_real: float
    rate_dummy: float
    rate_negative: float
    delta: float          # ①Δ = real − dummy
    z: float
    p_value: float        # 단측 (real > dummy)
    delta_significant: bool
    negative_below_dummy: bool

    @property
    def works(self) -> bool:
        """작동 인정: ①Δ 유의 양 **그리고** ③<②. 둘 다라야."""
        return self.delta_significant and self.negative_below_dummy


def placebo_result(obs: list[ArmObservation], *, alpha: float = 0.05) -> PlaceboResult:
    """3-arm 차분 채점 (§4.1). ``alpha`` = 단측 유의수준."""
    xr, nr = _arm_counts(obs, Arm.REAL)
    xd, nd = _arm_counts(obs, Arm.DUMMY)
    xn, nn = _arm_counts(obs, Arm.NEGATIVE)
    rate = lambda x, n: (x / n) if n else 0.0
    rr, rd, rn = rate(xr, nr), rate(xd, nd), rate(xn, nn)
    z, p = two_prop_ztest(xr, nr, xd, nd)
    return PlaceboResult(
        rate_real=rr, rate_dummy=rd, rate_negative=rn,
        delta=rr - rd, z=z, p_value=p,
        delta_significant=(p < alpha and (rr - rd) > 0),
        negative_below_dummy=(rn < rd),
    )


def assert_placebo_control(obs: list[ArmObservation]) -> None:
    """3-arm 없으면 [4] 실행 거부 (§6 placebo_control)."""
    present = {o.arm for o in obs}
    missing = {Arm.REAL, Arm.DUMMY, Arm.NEGATIVE} - present
    if missing:
        raise GuardViolation(
            f"placebo_control 위반: arm 누락 {sorted(a.value for a in missing)} "
            "(§4.1 — 3-arm 없이 [4] 측정 금지, 순응 기저선 못 뺌)"
        )


# ── 4.2 시민 모델 불변성 ────────────────────────────────────────────────


@dataclass(frozen=True)
class InvarianceResult:
    deltas: dict[str, float]   # citizen_model → ①Δ
    signs_agree: bool


def model_invariance(obs: list[ArmObservation]) -> InvarianceResult:
    """시민 모델별 ①Δ 와 부호 일관성 (§4.2).

    ``signs_agree`` = 모든 모델이 **동일한 비영(非零) 부호**. Δ=0(진짜안과 더미를 못
    구분한 모델)은 일관으로 흡수하지 않는다(리뷰 §4.2: 그게 곧 "한 모델만 점수" 케이스).
    """
    models = sorted({o.citizen_model for o in obs})
    deltas: dict[str, float] = {}
    for m in models:
        mobs = [o for o in obs if o.citizen_model == m]
        deltas[m] = placebo_result(mobs).delta
    signs = {(d > 0) - (d < 0) for d in deltas.values()}  # {-1,0,1}
    agree = len(signs) == 1 and 0 not in signs  # 전원 같은 비영 부호
    return InvarianceResult(deltas=deltas, signs_agree=agree)


def assert_citizen_model_invariance(
    obs: list[ArmObservation], *, min_models: int = 2, require_positive: bool = True
) -> None:
    """≥2 시민모델 + ①Δ 부호 일관 (§6 citizen_model_invariance).

    ``require_positive`` (기본 True): '안이 작동'을 주장하려면 부호 일관만으론 부족하다 —
    전 모델 Δ가 음수면 부호는 일관해도 안이 **일관되게 역효과**(리뷰 §4.2 거짓 안심). 작동
    증명 맥락에선 모든 모델 ①Δ>0 을 요구. (순수 부호-일관 연구 시 False 로.)
    """
    models = {o.citizen_model for o in obs}
    if len(models) < min_models:
        raise GuardViolation(
            f"citizen_model_invariance 위반: 시민모델 {len(models)}종 < {min_models} "
            "(§4.2 — 한 모델만이면 '안이 아니라 모델을 잰 것')"
        )
    inv = model_invariance(obs)
    if not inv.signs_agree:
        raise GuardViolation(
            f"citizen_model_invariance 위반: 시민모델 간 ①Δ 부호 불일치/영 {inv.deltas} → 실격 "
            "(§4.2 — 안 품질이 아니라 모델 순응성을 잰 신호. Δ=0 모델은 효과 미복제)"
        )
    if require_positive and any(d <= 0 for d in inv.deltas.values()):
        raise GuardViolation(
            f"citizen_model_invariance 위반: 일부 모델 ①Δ ≤ 0 {inv.deltas} → '안이 작동'을 "
            "모델 가로질러 입증 못함(§4.2 — 부호 일관이어도 음/영이면 작동 아님)"
        )


# ── 4.3 반사실 반영 ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class CounterfactualObservation:
    """진짜 통합안(①)에서 전환한 시민에 대한 반사실: 반영 조항을 제거하면 철회하는가."""

    pid: str
    transitioned: bool          # ① 에서 수용 방향 전환했나
    withdraws_on_removal: bool  # 반영 조항 제거 시 전환 철회하나 (행동 정의)


def genuine_reflection_rate(cf: list[CounterfactualObservation]) -> float:
    """전환자 중 **진짜 반영**(철회) 비율. 나머지는 순응이었다(§4.3)."""
    transitioned = [c for c in cf if c.transitioned]
    if not transitioned:
        return 0.0
    return sum(1 for c in transitioned if c.withdraws_on_removal) / len(transitioned)


def assert_counterfactual_reflection(
    cf: list[CounterfactualObservation], *, min_genuine: float
) -> None:
    """전환의 상당수가 행동(철회)으로 진짜여야 (§6 counterfactual_reflection).

    ``min_genuine`` = 전환자 중 철회 비율 하한(호출자 명시). 미달이면 그 전환은
    대체로 순응 — 작동 주장 기각.
    """
    if not any(c.transitioned for c in cf):
        raise GuardViolation(
            "counterfactual_reflection 위반: 전환자 0 — 반사실 정의 불가 "
            "(§4.3 — 반영은 조항 제거 시 전환 철회로 정의)"
        )
    rate = genuine_reflection_rate(cf)
    if rate < min_genuine:
        raise GuardViolation(
            f"counterfactual_reflection 위반: 진짜 반영률 {rate:.2f} < {min_genuine} "
            "(§4.3 — 전환 다수가 조항 제거에도 유지 = 순응, 반영 아님)"
        )


# ── 4.4 집단 형평 (사전 정의) ───────────────────────────────────────────


@dataclass(frozen=True)
class SegmentEquity:
    segment: str
    delta: float                 # 집단별 ①Δ
    unreflected_ratio: float     # 집단 조건 미반영 비율


def segment_equity(
    obs: list[ArmObservation], unreflected_by_segment: dict[str, float]
) -> list[SegmentEquity]:
    """집단별 ①Δ + 미반영률 (§4.4). 미반영률은 [2] 합치기에서 사전 산출해 주입."""
    out: list[SegmentEquity] = []
    for seg in sorted({o.segment for o in obs}):
        sobs = [o for o in obs if o.segment == seg]
        out.append(
            SegmentEquity(
                segment=seg,
                delta=placebo_result(sobs).delta,
                unreflected_ratio=unreflected_by_segment.get(seg, 0.0),
            )
        )
    return out


def assert_segment_equity(
    equities: list[SegmentEquity], *, max_unreflected_ratio: float
) -> None:
    """특정 집단 미반영률이 사전 임계 초과면 자동 실격 (§4.4·§6).

    ``max_unreflected_ratio`` 는 측정 **전에** 명시(사후 정의 선택 봉쇄).
    """
    bad = [e for e in equities if e.unreflected_ratio > max_unreflected_ratio]
    if bad:
        names = ", ".join(f"{e.segment}({e.unreflected_ratio:.2f})" for e in bad)
        raise GuardViolation(
            f"집단 형평 위반: 미반영률 임계 {max_unreflected_ratio} 초과 — {names} "
            "(§4.4 — 사전 임계, 특정 집단 구조적 배제)"
        )


# ── 이음새: [1] ResponseLedger → [4] ArmObservation 어댑터 ───────────────


def ledger_to_arm_obs(
    ledger: ResponseLedger,
    proposal_id: str,
    *,
    baseline_round: str,
    arm_rounds: dict[str, Arm],
) -> list[ArmObservation]:
    """[1] 다차원 ledger 의 두 round(기준 vs 각 arm 제시 후)에서 한 안의 전후 입장을 뽑아
    [4] ArmObservation 으로 변환한다.

    리뷰 #5(이음새 미배선) 해소: 이전엔 ArmObservation 을 손으로 만들어 측정에 먹였으나,
    실제로는 ledger 에 기록된 같은 시민의 두 round stance 차이가 raw 다. ``arm_rounds`` =
    {round_id → Arm}. citizen_model·segment 는 CitizenResponse 에서 그대로 가져온다.
    """
    base = ledger.rounds.get(baseline_round, {})
    obs: list[ArmObservation] = []
    for round_id, arm in arm_rounds.items():
        cur = ledger.rounds.get(round_id, {})
        for pid in base.keys() & cur.keys():
            b = base[pid].stance(proposal_id)
            a = cur[pid].stance(proposal_id)
            if b is not None and a is not None:
                obs.append(
                    ArmObservation(pid, cur[pid].segment, cur[pid].model, arm, b, a)
                )
    return obs


# ── [4] 측정 런너 — 모든 가드를 강제하는 단일 게이트 ────────────────────


@dataclass(frozen=True)
class MeasurementResult:
    """[4] 채점 산출 — 게이트 통과 시에만 생성된다(가드가 먼저 발화)."""

    placebo: PlaceboResult
    invariance: InvarianceResult
    genuine_reflection: float
    equities: tuple[SegmentEquity, ...]


def run_measurement(
    obs: list[ArmObservation],
    cf: list[CounterfactualObservation],
    unreflected_by_segment: dict[str, float],
    *,
    alpha: float = 0.05,
    min_genuine: float,
    max_unreflected_ratio: float,
    require_positive: bool = True,
) -> MeasurementResult:
    """[4] 재의견 채점 — **5개 가드를 호출 전에 전부 발화**(리뷰 C3 미배선 해소).

    라이브 [4] 경로는 절대 전환율을 직접 보고하지 말고 이 런너를 지난다. 어느 가드든
    위반이면 ``GuardViolation`` 으로 멈춘다 — 순응 기저선 미제거·모델 종속·순응 전환·집단
    배제를 보고 단계 전에 차단.
    """
    assert_placebo_control(obs)                                    # 3-arm 강제(§4.1)
    assert_citizen_model_invariance(obs, require_positive=require_positive)  # 2모델·부호(§4.2)
    assert_counterfactual_reflection(cf, min_genuine=min_genuine)  # 반사실(§4.3)
    equities = segment_equity(obs, unreflected_by_segment)
    assert_segment_equity(equities, max_unreflected_ratio=max_unreflected_ratio)  # 형평(§4.4)
    return MeasurementResult(
        placebo=placebo_result(obs, alpha=alpha),
        invariance=model_invariance(obs),
        genuine_reflection=genuine_reflection_rate(cf),
        equities=tuple(equities),
    )
