from __future__ import annotations

from datetime import datetime, timezone

import pytest

from policy_lab.domains.pension import (
    ArtifactApproval,
    ArtifactKind,
    ExperimentArtifact,
    ExperimentStage,
    ParticipantType,
    PensionExperimentSession,
    FreezeApproval,
    FreezeManifest,
    MeasurementSpec,
    PolicyOptionDefinition,
)
from policy_lab.domains.pension.experiment import (
    ExperimentError,
    V4_PROCEDURE_CONFIG,
    content_hash,
)
FIXED_NOW = datetime(2026, 8, 9, 1, 0, tzinfo=timezone.utc)


def spec() -> MeasurementSpec:
    return MeasurementSpec("main-policy-choice", "1" * 64, "options-v1", 1, 5)


def options() -> tuple[PolicyOptionDefinition, ...]:
    return tuple(
        PolicyOptionDefinition(option_id, f"정책안 {option_id}", "options-v1")
        for option_id in ("A", "B", "C")
    )


def freeze(measurement_spec: MeasurementSpec) -> FreezeManifest:
    approvals = tuple(
        FreezeApproval(
            category, "owner", "2026-08-09T09:00:00+09:00",
            content_hash(category), f"approval-{category}",
        )
        for category in (
            "policy_options", "calculation", "measurement", "privacy",
            "research_ethics", "source_license", "procedure",
        )
    )
    return FreezeManifest(
        "freeze-v4", "2026-08-09.v4", "options-v1",
        measurement_spec.spec_hash, "frozen", True, approvals,
    )


def approved(kind: ArtifactKind, name: str) -> ExperimentArtifact:
    digest = content_hash({"kind": kind.value, "name": name})
    return ExperimentArtifact(
        name,
        "v1",
        kind,
        digest,
        ArtifactApproval(
            f"approval-{name}",
            "human-reviewer",
            "2026-08-09T09:00:00+09:00",
            digest,
        ),
    )


def session() -> PensionExperimentSession:
    measurement_spec = spec()
    return PensionExperimentSession(
        experiment_version="2026-08-09.v4",
        session_id="deliberation-v4",
        measurement_spec=measurement_spec,
        policy_options=options(),
        freeze_manifest=freeze(measurement_spec),
        procedure_config=V4_PROCEDURE_CONFIG,
        clock=lambda: FIXED_NOW,
    )


def test_v4_has_no_personal_calculation_and_d_is_not_a_fourth_choice():
    flow = V4_PROCEDURE_CONFIG
    assert "calculator" not in str(flow)
    assert "personal" not in str(flow)
    assert flow["m3_primary_option_ids"] == ["A", "B", "C"]
    assert flow["m3_secondary_evaluation"] == "D_acceptability_and_opinion"


def test_v4_executes_two_deliberations_then_separate_d_evaluation_contract():
    flow = session()
    flow.register_participant("reviewer", ParticipantType.REAL)
    issues = approved(ArtifactKind.ISSUE_DELIBERATION, "five-issues")
    draft_d = approved(ArtifactKind.AI_OPINION, "draft-d")
    expert = approved(ArtifactKind.EXPERT_EXPLANATION, "expert-d")
    flow.set_issue_deliberation_artifact(issues)
    flow.set_session_ai_artifact(draft_d)
    flow.set_expert_artifact(expert)

    flow.record_consent(
        "reviewer", consent_version="v4", affirmed=True,
        expected_revision=0, idempotency_key="consent",
    )
    assert flow.participant_state("reviewer") == (ExperimentStage.E0, 1)
    flow.acknowledge_policy_options(
        "reviewer", content_hash_value=flow.policy_options_content_hash,
        expected_revision=1, idempotency_key="first-deliberation",
    )
    flow.submit_measurement(
        "reviewer", "M1", choice="B", stance="conditional",
        reason="재정 지속가능성 조건을 더 확인해야 합니다.", confidence=None,
        expected_revision=2, idempotency_key="m1",
    )
    flow.record_exposure(
        "reviewer", issues, read_ack=True,
        opened_at=datetime(2026, 8, 8, 23, 0, tzinfo=timezone.utc),
        expected_revision=3, idempotency_key="second-deliberation",
    )
    assessments = {
        "A": {"stance": "reject", "reason": "세대 형평성 우려"},
        "B": {"stance": "accept", "reason": "쟁점 설명 후 수용"},
        "C": {"stance": "reject", "reason": "재정 위험"},
    }
    flow.submit_measurement(
        "reviewer", "M2", choice="B", reason=None, confidence=3,
        option_assessments=assessments,
        expected_revision=4, idempotency_key="m2",
    )
    flow.record_exposure(
        "reviewer", draft_d, read_ack=True,
        expected_revision=5, idempotency_key="draft-d",
    )
    flow.record_exposure(
        "reviewer", expert, read_ack=True,
        expected_revision=6, idempotency_key="expert-d",
    )

    with pytest.raises(ExperimentError, match="A/B/C"):
        flow.submit_measurement(
            "reviewer", "M3", choice="D", reason=None, confidence=None,
            expected_revision=7, idempotency_key="wrong-fourth-option",
        )
    record = flow.submit_measurement(
        "reviewer", "M3", choice="A", reason=None, confidence=None,
        expected_revision=7, idempotency_key="m3",
    )
    assert record.option_order == ("A", "B", "C")
    assert flow.participant_state("reviewer") == (ExperimentStage.COMPLETE, 8)
