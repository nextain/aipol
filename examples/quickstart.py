"""policy-lab 1분 사용 예제.

실행: python examples/quickstart.py  (먼저 `pip install -e ".[test]"`)

연금 도메인을 로드해 레버·근거·영향모델을 보고, 방어장치가 실제로 막는 것을 보여준다.
"행사를 굴리는 앱"이 아니라 그 밑의 엔진 + 안전장치임을 확인하는 용도.
"""
from policy_lab.domains.pension import PensionDomain
from policy_lab.core.levers import PolicyOption
from policy_lab.core import HumanGate, GuardViolation, assert_ab_separation


def main() -> None:
    d = PensionDomain()
    print("도메인:", d.label)
    print("레버(변화):", [(l.key, l.options) for l in d.levers()])
    print("고정변수:", [(f.key, f.value) for f in d.fixed_variables()])
    print()

    print("근거 앵커(Evidence):")
    for e in d.evidence().all():
        print(f"  - {e.key}: {e.value or '(정성)'}  <{e.source}, {e.as_of}>")
    print()

    opt = PolicyOption(
        "전문가1안",
        {"수급연령": "단계적 상향", "국고투입": "최소화", "기초연금": "선별 강화"},
    )
    print(f"[A축] 정책안 '{opt.name}' 영향 — 방향·밴드만:")
    for r in d.impact_model().evaluate(opt):
        print(f"  - {r.metric}: {r.direction.value} / {r.band}")
    print()

    proto = d.protocol()
    proto.validate()
    print(f"[프로토콜] '{proto.name}': {len(proto.stages)} stage, validate() 통과(human_gate 포함)")
    print()

    print("[방어장치 데모]")
    gate = HumanGate("쟁점 3개: 수급연령/국고/기초연금")
    try:
        gate.release()
    except GuardViolation as e:
        print("  human_gate 차단 →", e)
    gate.approve("public-reviewer")
    print("  승인 후 release →", gate.release())

    hits = d.evidence().contradictions("이번 개혁으로 자동조정장치 도입이 확정되었다.")
    print("  근거 위반 검출 →", hits)

    try:
        assert_ab_separation({"gpt-x"}, {"gpt-x"})
    except GuardViolation as e:
        print("  A/B 분리 차단 →", e)


if __name__ == "__main__":
    main()
