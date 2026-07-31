"""연금 레퍼런스 도메인 테스트.

도메인 plugin이 코어 인터페이스를 만족하고, 영향 모델이 방향·밴드만 내며,
근거 앵커 검증이 동작하는지 확인한다.
"""
from __future__ import annotations

from policy_lab.core.impact import Direction, ImpactResult
from policy_lab.core.levers import PolicyOption
from policy_lab.domains.pension import PensionDomain


def test_plugin_shape():
    d = PensionDomain()
    assert d.key == "pension"
    assert len(d.levers()) == 3
    assert len(d.fixed_variables()) == 2
    assert len(d.segments()) == 3
    assert set(d.prompts()) == {"scenario", "issues", "impact_sim", "risk", "revision"}


def test_protocol_whitelist_filled_from_levers():
    d = PensionDomain()
    proto = d.protocol()
    proto.validate()  # human_gate 포함 표준 프로토콜
    aq = [s for s in proto.stages if s.type.value == "audience_query"]
    assert aq and set(aq[0].whitelist_lever_keys) == {"수급연령", "국고투입", "기초연금"}


def test_impact_model_outputs_direction_and_band():
    d = PensionDomain()
    model = d.impact_model()
    opt = PolicyOption(
        "테스트안",
        {"수급연령": "단계적 상향", "국고투입": "최소화", "기초연금": "선별 강화"},
    )
    results = model.evaluate(opt)
    assert all(isinstance(r, ImpactResult) for r in results)
    fiscal = next(r for r in results if r.metric == "재정 지속가능성")
    assert fiscal.direction == Direction.IMPROVES
    # 밴드는 방향/범위 표현이라 단일숫자 가드를 통과해 생성됨(생성 자체가 검증)
    assert fiscal.band


def test_impact_model_mixed_when_subsidy_expands():
    d = PensionDomain()
    opt = PolicyOption(
        "확대안",
        {"수급연령": "단계적 상향", "국고투입": "확대", "기초연금": "보편 확대"},
    )
    results = d.impact_model().evaluate(opt)
    fiscal = next(r for r in results if r.metric == "재정 지속가능성")
    assert fiscal.direction == Direction.MIXED


def test_evidence_anchors_and_rules():
    store = PensionDomain().evidence()
    assert store.get("기금소진").value == "2055"
    assert store.get("개혁효과기준선").value == "2056"
    # 환각 검출: 자동조정장치 '도입' 주장은 앵커 위반
    hits = store.contradictions("이번 개혁으로 자동조정장치 도입이 확정되었다.")
    assert hits
    # 정상 진술은 위반 없음
    assert not store.contradictions("자동조정장치는 이번 합의에서 제외되었다.")
