"""REQ-EXP-001~006 / REQ-TEST-001~002 집중 계약 테스트."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from policy_lab.domains.pension import (
    ArtifactApproval,
    ArtifactKind,
    CollectionDisabled,
    ExperimentArtifact,
    ExperimentStage,
    FreezeApproval,
    FreezeManifest,
    IdempotencyConflict,
    ImmutableRecordConflict,
    MeasurementSpec,
    ParticipantType,
    PensionExperimentSession,
    PolicyOptionDefinition,
    StateRevisionConflict,
)
from policy_lab.domains.pension.experiment import ExperimentError, InvalidTransition, content_hash


FIXED_NOW = datetime(2026, 8, 12, 5, 30, tzinfo=timezone.utc)
QUESTION_HASH = "1" * 64


def _spec() -> MeasurementSpec:
    return MeasurementSpec("main-policy-choice", QUESTION_HASH, "options-v1", 1, 5)


def _options() -> tuple[PolicyOptionDefinition, ...]:
    return (
        PolicyOptionDefinition("A", "정책안 A", "options-v1"),
        PolicyOptionDefinition("B", "정책안 B", "options-v1"),
        PolicyOptionDefinition("C", "정책안 C", "options-v1"),
    )


def _freeze(spec: MeasurementSpec, enabled: bool = True) -> FreezeManifest:
    approvals = tuple(
        FreezeApproval(
            category, "research-owner", "2026-08-01T09:00:00+09:00",
            content_hash(category), f"approval-{category}",
        )
        for category in (
            "policy_options",
            "calculation",
            "measurement",
            "privacy",
            "research_ethics",
            "source_license",
            "procedure",
        )
    )
    return FreezeManifest(
        "freeze-v1",
        "2026-08-12.1",
        "options-v1",
        spec.spec_hash,
        "frozen",
        enabled,
        approvals,
    )


def _session(*, collection_enabled: bool = True) -> PensionExperimentSession:
    spec = _spec()
    return PensionExperimentSession(
        experiment_version="2026-08-12.1",
        session_id="session-01",
        measurement_spec=spec,
        policy_options=_options(),
        freeze_manifest=_freeze(spec, collection_enabled),
        clock=lambda: FIXED_NOW,
    )


def _artifact(kind: ArtifactKind, marker: str, *, fallback: bool = False) -> ExperimentArtifact:
    digest = content_hash({"kind": kind.value, "marker": marker})
    approval = None
    if kind is not ArtifactKind.PERSONAL_COMPARISON:
        approval = ArtifactApproval(
            f"approval-{marker}", "human-reviewer", "2026-08-12T14:00:00+09:00", digest
        )
    return ExperimentArtifact(
        marker,
        "v1",
        kind,
        digest,
        approval,
        fallback,
    )


def _advance_all(
    session: PensionExperimentSession,
    participant: str,
    *,
    choices: tuple[str | None, str | None, str | None] = ("A", "B", "C"),
) -> None:
    e1a = _artifact(ArtifactKind.PERSONAL_COMPARISON, f"personal-{participant}")
    expert = _artifact(ArtifactKind.EXPERT_EXPLANATION, "expert-session")
    ai = _artifact(ArtifactKind.AI_OPINION, "ai-session")
    session.set_expert_artifact(expert)
    session.set_session_ai_artifact(ai)
    session.record_consent(
        participant, consent_version="consent-v1", affirmed=True, expected_revision=0, idempotency_key=f"{participant}-c"
    )
    session.record_exposure(
        participant, e1a, read_ack=True, expected_revision=1, idempotency_key=f"{participant}-e1a"
    )
    session.submit_measurement(
        participant,
        "M1",
        choice=choices[0],
        reason="선택 이유",
        confidence=3,
        expected_revision=2,
        idempotency_key=f"{participant}-m1",
    )
    session.record_exposure(
        participant, expert, read_ack=True, expected_revision=3, idempotency_key=f"{participant}-e1b"
    )
    session.submit_measurement(
        participant,
        "M2",
        choice=choices[1],
        reason=None,
        confidence=4,
        expected_revision=4,
        idempotency_key=f"{participant}-m2",
    )
    session.record_exposure(
        participant, ai, read_ack=True, expected_revision=5, idempotency_key=f"{participant}-e2"
    )
    session.submit_measurement(
        participant,
        "M3",
        choice=choices[2],
        reason=None,
        confidence=5,
        expected_revision=6,
        idempotency_key=f"{participant}-m3",
    )


def test_collection_gate_defaults_off_and_synthetic_rehearsal_stays_available():
    spec = _spec()
    session = PensionExperimentSession(
        experiment_version="2026-08-12.1",
        session_id="session-closed",
        measurement_spec=spec,
        policy_options=_options(),
    )
    assert session.collection_enabled is False
    with pytest.raises(CollectionDisabled):
        session.register_participant("real-1", ParticipantType.REAL)
    with pytest.raises(CollectionDisabled):
        session.register_participant("real-string", "real")
    session.register_participant("synthetic-1", ParticipantType.SYNTHETIC)
    assert session.participant_state("synthetic-1") == (ExperimentStage.CONSENT, 0)


def test_main_measurement_requires_exactly_three_stable_policy_options():
    with pytest.raises(ExperimentError):
        PensionExperimentSession(
            experiment_version="2026-08-12.1",
            session_id="bad-options",
            measurement_spec=_spec(),
            policy_options=_options()[:2],
        )


def test_human_approval_timestamps_require_iso_8601_timezone():
    digest = content_hash("approval")
    with pytest.raises(ExperimentError, match="시간대"):
        FreezeApproval(
            "privacy", "reviewer", "2026-08-01T09:00:00", digest, "approval-privacy"
        ).validate()
    artifact = ExperimentArtifact(
        "expert-v1",
        "v1",
        ArtifactKind.EXPERT_EXPLANATION,
        digest,
        ArtifactApproval("approval-1", "reviewer", "not-a-time", digest),
    )
    with pytest.raises(ExperimentError, match="ISO 8601"):
        artifact.require_human_approval()


def test_three_measurements_are_append_only_and_keep_same_question_options_and_order():
    session = _session()
    session.register_participant("real-1", ParticipantType.REAL, option_order=("C", "A", "B"))
    _advance_all(session, "real-1")

    assert session.participant_state("real-1") == (ExperimentStage.COMPLETE, 7)
    records = session.measurement_records
    assert [record.measurement_id for record in records] == ["M1", "M2", "M3"]
    assert len({record.question_id for record in records}) == 1
    assert len({record.measurement_spec_hash for record in records}) == 1
    assert len({record.option_set_version for record in records}) == 1
    assert {record.option_order for record in records} == {("C", "A", "B")}
    assert all(record.participant_type is ParticipantType.REAL for record in records)
    assert [record.state_revision for record in records] == [3, 5, 7]
    assert records[0].preceding_exposure_hash != records[1].preceding_exposure_hash
    with pytest.raises(FrozenInstanceError):
        records[0].choice = "B"  # type: ignore[misc]


def test_skips_future_exposure_and_overwrite_are_rejected():
    session = _session()
    session.register_participant("real-1", ParticipantType.REAL)
    expert = _artifact(ArtifactKind.EXPERT_EXPLANATION, "expert-session")
    session.set_expert_artifact(expert)
    with pytest.raises(InvalidTransition):
        session.record_exposure(
            "real-1", expert, read_ack=True, expected_revision=0, idempotency_key="skip-expert"
        )

    session.record_consent(
        "real-1", consent_version="v1", affirmed=True, expected_revision=0, idempotency_key="consent"
    )
    personal = _artifact(ArtifactKind.PERSONAL_COMPARISON, "personal")
    session.record_exposure(
        "real-1", personal, read_ack=True, expected_revision=1, idempotency_key="personal"
    )
    with pytest.raises(InvalidTransition):
        session.submit_measurement(
            "real-1",
            "M2",
            choice="A",
            reason=None,
            confidence=3,
            expected_revision=2,
            idempotency_key="future-m2",
        )
    session.submit_measurement(
        "real-1",
        "M1",
        choice="A",
        reason=None,
        confidence=3,
        expected_revision=2,
        idempotency_key="m1",
    )
    with pytest.raises(InvalidTransition):
        session.submit_measurement(
            "real-1",
            "M1",
            choice="B",
            reason=None,
            confidence=3,
            expected_revision=3,
            idempotency_key="overwrite-m1",
        )


def test_idempotency_and_optimistic_lock_are_server_side_guards():
    session = _session()
    session.register_participant("real-1", ParticipantType.REAL)
    first = session.record_consent(
        "real-1", consent_version="v1", affirmed=True, expected_revision=0, idempotency_key="same-key"
    )
    retry = session.record_consent(
        "real-1", consent_version="v1", affirmed=True, expected_revision=0, idempotency_key="same-key"
    )
    assert retry is first
    assert len(session.consent_records) == 1
    with pytest.raises(IdempotencyConflict):
        session.record_consent(
            "real-1", consent_version="changed", affirmed=True, expected_revision=0, idempotency_key="same-key"
        )
    with pytest.raises(StateRevisionConflict):
        session.record_exposure(
            "real-1",
            _artifact(ArtifactKind.PERSONAL_COMPARISON, "p"),
            read_ack=True,
            expected_revision=0,
            idempotency_key="different-key",
        )


def test_simultaneous_submissions_commit_only_one_state_transition():
    session = _session()
    session.register_participant("real-1", ParticipantType.REAL)

    def submit(key: str):
        return session.record_consent(
            "real-1", consent_version="v1", affirmed=True, expected_revision=0, idempotency_key=key
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, "concurrent-a"), pool.submit(submit, "concurrent-b")]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(type(future.result()).__name__)
        except StateRevisionConflict:
            outcomes.append("StateRevisionConflict")

    assert sorted(outcomes) == ["ConsentRecord", "StateRevisionConflict"]
    assert len(session.consent_records) == 1


def test_expert_and_ai_exposures_require_approved_session_wide_exact_artifacts():
    session = _session()
    digest = content_hash("unapproved")
    unapproved = ExperimentArtifact(
        "expert", "v1", ArtifactKind.EXPERT_EXPLANATION, digest
    )
    with pytest.raises(ExperimentError):
        session.set_expert_artifact(unapproved)

    ai = _artifact(ArtifactKind.AI_OPINION, "ai-primary")
    session.set_session_ai_artifact(ai)
    session.set_session_ai_artifact(ai)  # 같은 자료 재시도는 멱등
    with pytest.raises(ImmutableRecordConflict):
        session.set_session_ai_artifact(_artifact(ArtifactKind.AI_OPINION, "ai-other"))


def test_real_only_aggregation_is_default_and_preserves_nonresponse_and_attrition():
    session = _session()
    session.register_participant("real-1", ParticipantType.REAL)
    session.register_participant("synthetic-1", ParticipantType.SYNTHETIC)
    session.register_participant("real-dropout", ParticipantType.REAL)
    _advance_all(session, "real-1", choices=("A", None, "B"))
    _advance_all(session, "synthetic-1", choices=("C", "C", "C"))
    session.record_consent(
        "real-dropout", consent_version="v1", affirmed=True, expected_revision=0, idempotency_key="drop-c"
    )
    session.withdraw_participant(
        "real-dropout", reason="중도 이탈", expected_revision=1, idempotency_key="drop-w"
    )

    assert session.transition_table("M1", "M2") == {("A", None): 1}
    assert session.transition_table(
        "M1", "M2", participant_type=ParticipantType.SYNTHETIC
    ) == {("C", "C"): 1}
    counts = session.funnel_counts()
    assert counts == {
        "registered": 2,
        "consented": 2,
        "E1a": 1,
        "M1": 1,
        "E1b": 1,
        "M2": 1,
        "E2": 1,
        "M3": 1,
        "complete": 1,
        "withdrawn": 1,
    }


def test_freeze_contract_files_are_machine_readable_and_example_is_closed():
    from jsonschema import Draft202012Validator, FormatChecker

    root = Path(__file__).parents[1]
    schema = json.loads((root / "contracts/aipol-experiment-freeze.schema.json").read_text("utf-8"))
    example = json.loads((root / "contracts/aipol-experiment-freeze.example.json").read_text("utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
    assert set(schema["required"]) <= set(example)
    assert example["status"] == "draft"
    assert example["collection_enabled"] is False


def test_operational_gate_contract_schemas_are_draft_2020_12_valid():
    from jsonschema import Draft202012Validator

    root = Path(__file__).parents[1] / "contracts"
    for name in (
        "aipol-registration.schema.json",
        "aipol-canonical-document.schema.json",
        "aipol-ai-candidate.schema.json",
        "aipol-ai-candidate-approved-public.schema.json",
        "aipol-calculator-receipt.schema.json",
    ):
        schema = json.loads((root / name).read_text("utf-8"))
        Draft202012Validator.check_schema(schema)

    receipt_schema = json.loads((root / "aipol-calculator-receipt.schema.json").read_text("utf-8"))
    receipt_example = {
        "contract_id": "calculator-completion-v1",
        "version": "1.0.0",
        "mode": "signed_one_time_completion",
        "issuer": "https://calculator.example.test",
        "audience": "aipol-event-tool",
        "public_key_id": "fixture-key-1",
        "receipt_format": "flattened_jws_json",
        "signature_algorithm": "EdDSA",
    }
    from jsonschema import FormatChecker

    Draft202012Validator(receipt_schema, format_checker=FormatChecker()).validate(receipt_example)


def test_operational_gate_contract_schemas_reject_invalid_formats():
    from jsonschema import Draft202012Validator, FormatChecker
    from jsonschema.exceptions import ValidationError

    root = Path(__file__).parents[1] / "contracts"
    checker = FormatChecker()

    canonical_schema = json.loads((root / "aipol-canonical-document.schema.json").read_text("utf-8"))
    canonical_with_invalid_datetime = {
        "category": "privacy",
        "document_id": "privacy-v1",
        "document_version": "v1",
        "body": "Approved privacy notice",
        "bound_settings_hash": "0" * 64,
        "evidence": {},
        "content_hash": "1" * 64,
        "approval_id": "approval-1",
        "approved_by": "approver",
        "approved_at": "not-a-date-time",
        "registered_by": "registrar",
    }
    with pytest.raises(ValidationError, match="not a 'date-time'"):
        Draft202012Validator(canonical_schema, format_checker=checker).validate(canonical_with_invalid_datetime)

    receipt_schema = json.loads((root / "aipol-calculator-receipt.schema.json").read_text("utf-8"))
    receipt_with_invalid_uri = {
        "contract_id": "calculator-completion-v1",
        "version": "1.0.0",
        "mode": "signed_one_time_completion",
        "issuer": "https://exa mple.invalid",
        "audience": "aipol-event-tool",
        "public_key_id": "fixture-key-1",
        "receipt_format": "flattened_jws_json",
        "signature_algorithm": "EdDSA",
    }
    with pytest.raises(ValidationError, match="not a 'uri'"):
        Draft202012Validator(receipt_schema, format_checker=checker).validate(receipt_with_invalid_uri)

    registration_schema = json.loads(
        (root / "aipol-registration.schema.json").read_text("utf-8")
    )
    with pytest.raises(ValidationError):
        Draft202012Validator(registration_schema).validate({
            "admission_code": "aaaaaaaaaaaaaaaa",
            "registration_nonce": "nonce-12345678901",
            "idempotency_key": "idem-12345678",
        })

    ai_schema = json.loads((root / "aipol-ai-candidate.schema.json").read_text("utf-8"))
    invalid_ai = {
        "candidate_role": "fallback",
        "artifact_id": "ai-fallback",
        "artifact_version": "v1",
        "content": {"title": " ", "body": "approved body"},
        "model": "model", "deployment": "deployment", "prompt_version": "prompt-v1",
        "generated_at": "2026-07-01T00:00:00Z",
        "evidence_refs": ["source-1"], "m2_aggregate_hash": None,
        "approval_id": "approval-1", "approved_by": "reviewer",
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(ai_schema, format_checker=checker).validate(invalid_ai)
    valid_request = {
        **invalid_ai,
        "content": {"title": "approved title", "body": "approved body", "unbound": "no"},
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(ai_schema, format_checker=checker).validate(valid_request)

    freeze_schema = json.loads(
        (root / "aipol-experiment-freeze.schema.json").read_text("utf-8")
    )
    categories = (
        "policy_options", "calculation", "measurement", "privacy",
        "research_ethics", "source_license", "procedure",
    )
    duplicate_freeze = {
        "manifest_id": "freeze-duplicate",
        "experiment_version": "v1",
        "option_set_version": "options-v1",
        "measurement_spec_hash": "0" * 64,
        "status": "frozen",
        "collection_enabled": True,
        "approvals": [
            {
                "category": category,
                "approval_id": f"approval-{category}",
                "approved_by": "reviewer",
                "approved_at": "2026-07-01T00:00:00Z",
                "content_hash": str(index) * 64,
            }
            for index, category in enumerate(categories, 1)
        ] + [{
            "category": "privacy", "approval_id": "approval-privacy-duplicate",
            "approved_by": "other-reviewer",
            "approved_at": "2026-07-01T00:00:00Z", "content_hash": "f" * 64,
        }],
    }
    with pytest.raises(ValidationError):
        Draft202012Validator(freeze_schema, format_checker=checker).validate(duplicate_freeze)
