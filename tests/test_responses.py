"""[1] 다차원 응답 스키마 계약 테스트 (RFC-0003 §6).

테스트는 "계약이 실제로 막는가"를 검증한다(RFC-0001 원칙).
"""
import pytest

from policy_lab.core.responses import (
    Stance,
    ProposalResponse,
    CitizenResponse,
    ResponseLedger,
)


def test_conditional_requires_text():
    """조건부 수용은 조건 텍스트가 없으면 거부된다 (반영 재료 보장)."""
    with pytest.raises(ValueError):
        ProposalResponse("1안", Stance.CONDITIONAL, "")
    with pytest.raises(ValueError):
        ProposalResponse("1안", Stance.CONDITIONAL, "   ")
    # 조건 텍스트 있으면 통과
    ProposalResponse("1안", Stance.CONDITIONAL, "저소득 고령자는 예외면 수용")


def test_accept_reject_text_optional():
    """수용·거부는 텍스트가 없어도 된다."""
    ProposalResponse("1안", Stance.ACCEPT)
    ProposalResponse("2안", Stance.REJECT)


def test_missing_proposal_rejected():
    """모든 안에 stance 가 없으면 거부 (다차원 응답 강제)."""
    r = {"1안": ProposalResponse("1안", Stance.ACCEPT)}
    with pytest.raises(ValueError):
        CitizenResponse("K1", "senior", "qwen", r, proposals=("1안", "2안", "3안"))
    # 모두 있으면 통과
    full = {
        "1안": ProposalResponse("1안", Stance.ACCEPT),
        "2안": ProposalResponse("2안", Stance.REJECT),
        "3안": ProposalResponse("3안", Stance.CONDITIONAL, "수급연령 예외면"),
    }
    cr = CitizenResponse("K1", "senior", "qwen", full, proposals=("1안", "2안", "3안"))
    assert len(cr.conditions()) == 1  # 3안만 조건부


def test_ledger_dist_transition_moved():
    """집계·전이·이동 — [4] 측정의 raw 단위."""
    led = ResponseLedger()
    led.record("r1", CitizenResponse("K1", "s", "m", {"1안": ProposalResponse("1안", Stance.ACCEPT)}))
    led.record("r1", CitizenResponse("K2", "s", "m", {"1안": ProposalResponse("1안", Stance.REJECT)}))
    d = led.stance_dist("r1", "1안")
    assert d["accept"] == 1 and d["reject"] == 1 and d["conditional"] == 0

    # r2: K1 이 거부로 이동
    led.record("r2", CitizenResponse("K1", "s", "m", {"1안": ProposalResponse("1안", Stance.REJECT)}))
    led.record("r2", CitizenResponse("K2", "s", "m", {"1안": ProposalResponse("1안", Stance.REJECT)}))
    assert led.moved("r1", "r2", "1안") == ["K1"]
    t = led.transitions("r1", "r2", "1안")
    assert t[("accept", "reject")] == 1
