"""Deterministic virtual-clock rehearsal of the AIPOL run sheet."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .experiment import (
    ArtifactApproval,
    ArtifactKind,
    ExperimentArtifact,
    ExperimentStage,
    MeasurementSpec,
    ParticipantType,
    PensionExperimentSession,
    PolicyOptionDefinition,
    PROCEDURE_CONFIG,
    content_hash,
)


@dataclass(frozen=True)
class RehearsalReceipt:
    essential_complete_minute: int
    event_end_minute: int
    measurements: tuple[str, ...]
    recoveries: tuple[str, ...]
    timeline: tuple[tuple[int, str], ...]


class RehearsalFailure(RuntimeError):
    pass


def _validate_procedure(procedure_config: dict) -> None:
    expected = tuple(
        stage.value for stage in ExperimentStage if stage is not ExperimentStage.WITHDRAWN
    )
    configured = tuple(procedure_config.get("stages") or ())
    if configured != expected:
        raise RehearsalFailure(
            f"procedure/state-machine drift: configured={configured!r}, expected={expected!r}"
        )
    if tuple(procedure_config.get("measurements") or ()) != ("M1", "M2", "M3"):
        raise RehearsalFailure("procedure measurement drift")
    if procedure_config.get("exposures") != {
        "E1a": "calculator", "E1b": "expert", "E2": "ai"
    }:
        raise RehearsalFailure("procedure exposure drift")


def run_virtual_rehearsal(
    *,
    failures: frozenset[str] = frozenset(),
    procedure_config: dict | None = None,
) -> RehearsalReceipt:
    """Drive the real state machine with virtual time; never claim a field rehearsal."""
    config = PROCEDURE_CONFIG if procedure_config is None else procedure_config
    _validate_procedure(config)
    minute = 0
    timeline: list[tuple[int, str]] = []
    recoveries: list[str] = []
    epoch = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)

    def now() -> datetime:
        return epoch + timedelta(minutes=minute)

    def advance(target: int, label: str) -> None:
        nonlocal minute
        if target < minute:
            raise RehearsalFailure(f"schedule overrun before {label}")
        minute = target
        timeline.append((minute, label))

    spec = MeasurementSpec("main-choice", content_hash("A/B/C 선택"), "options-v1")
    options = tuple(
        PolicyOptionDefinition(option, f"정책안 {option}", "options-v1")
        for option in ("A", "B", "C")
    )
    session = PensionExperimentSession(
        experiment_version="rehearsal-v1",
        session_id="virtual-clock",
        measurement_spec=spec,
        policy_options=options,
        clock=now,
    )
    personal = ExperimentArtifact(
        "calculator", "v1", ArtifactKind.PERSONAL_COMPARISON,
        content_hash({"calculator": "v1"}),
    )

    def approved_artifact(identifier: str, kind: ArtifactKind) -> ExperimentArtifact:
        digest = content_hash({"artifact": identifier})
        return ExperimentArtifact(
            identifier, "v1", kind, digest,
            ArtifactApproval(f"approval-{identifier}", "reviewer", epoch.isoformat(), digest),
        )

    expert = approved_artifact("expert", ArtifactKind.EXPERT_EXPLANATION)
    ai = approved_artifact("ai", ArtifactKind.AI_OPINION)
    session.set_expert_artifact(expert)
    session.set_session_ai_artifact(ai)
    participant = "synthetic-rehearsal"
    session.register_participant(participant, ParticipantType.SYNTHETIC)

    advance(10, "동의·참여 연결 완료")
    session.record_consent(
        participant, consent_version="v1", affirmed=True,
        expected_revision=0, idempotency_key="consent",
    )
    advance(25, "E1a 개인 비교와 M1 완료")
    session.record_exposure(
        participant, personal, read_ack=True, expected_revision=1, idempotency_key="E1a"
    )
    session.submit_measurement(
        participant, "M1", choice="A", reason=None, confidence=3,
        expected_revision=2, idempotency_key="M1",
    )
    advance(40, "E1b 전문가 설명과 M2 완료")
    session.record_exposure(
        participant, expert, read_ack=True, expected_revision=3, idempotency_key="E1b"
    )
    session.submit_measurement(
        participant, "M2", choice="B", reason=None, confidence=3,
        expected_revision=4, idempotency_key="M2",
    )

    if "ai_live_unavailable" in failures:
        advance(58, "AI 라이브 생성 실패 감지")
        recoveries.append("승인된 고정 E2 대체본 사용")
    else:
        advance(58, "AI 자료 준비와 사람 승인 완료")
    advance(70, "M2 집계·AI 승인·선정 완료")

    if "participant_network_drop" in failures:
        advance(78, "참가자 재접속·마지막 완료 단계 복구")
        recoveries.append("M3 전 체크포인트에서 재개")
    if "unrecoverable_measurement_store" in failures:
        raise RehearsalFailure(
            "M3 저장소 복구 실패: 실제 행사를 중단하고 측정 누락을 숨기지 않는다"
        )
    advance(85, "E2 AI 자료와 M3 완료")
    session.record_exposure(
        participant, ai, read_ack=True, expected_revision=5, idempotency_key="E2"
    )
    session.submit_measurement(
        participant, "M3", choice="C", reason=None, confidence=3,
        expected_revision=6, idempotency_key="M3",
    )
    stage, _ = session.participant_state(participant)
    if stage is not ExperimentStage.COMPLETE:
        raise RehearsalFailure(f"state machine did not complete: {stage.value}")

    advance(95, "최종 결과·한계 안내 완료")
    advance(100, "마감·장애 여유 종료")
    measurements = tuple(record.measurement_id for record in session.measurement_records)
    if measurements != tuple(config["measurements"]):
        raise RehearsalFailure("rehearsal measurements drifted from procedure")
    return RehearsalReceipt(95, minute, measurements, tuple(recoveries), tuple(timeline))
