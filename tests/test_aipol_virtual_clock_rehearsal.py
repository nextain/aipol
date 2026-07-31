from __future__ import annotations

import pytest

from policy_lab.domains.pension.rehearsal import RehearsalFailure, run_virtual_rehearsal


def test_virtual_clock_preserves_three_measurements_and_five_minute_buffer() -> None:
    receipt = run_virtual_rehearsal()
    assert receipt.measurements == ("M1", "M2", "M3")
    assert receipt.essential_complete_minute <= 95
    assert receipt.event_end_minute == 100
    assert receipt.timeline[-2:] == ((95, "최종 결과·한계 안내 완료"), (100, "마감·장애 여유 종료"))


def test_virtual_clock_recovers_ai_and_network_failures_without_dropping_measurements() -> None:
    receipt = run_virtual_rehearsal(failures=frozenset({"ai_live_unavailable", "participant_network_drop"}))
    assert receipt.measurements == ("M1", "M2", "M3")
    assert receipt.recoveries == ("승인된 고정 E2 대체본 사용", "M3 전 체크포인트에서 재개")
    assert receipt.essential_complete_minute == 95


def test_virtual_clock_reports_unrecoverable_storage_failure_instead_of_false_completion() -> None:
    with pytest.raises(RehearsalFailure, match="측정 누락을 숨기지 않는다"):
        run_virtual_rehearsal(failures=frozenset({"unrecoverable_measurement_store"}))


def test_virtual_clock_fails_closed_when_procedure_drifts_from_state_machine() -> None:
    with pytest.raises(RehearsalFailure, match="procedure/state-machine drift"):
        run_virtual_rehearsal(procedure_config={
            "stages": ["consent", "E1a", "M1", "E2", "M3", "complete"],
            "measurements": ["M1", "M2", "M3"],
            "exposures": {"E1a": "calculator", "E1b": "expert", "E2": "ai"},
        })
