"""AIPOL 연금 실험의 세 번 측정 실행 코어.

이 모듈은 참가자별 상태를 순서대로 전진시키고, 이미 기록한 동의·노출·응답을
수정하지 않는다. 저장소 어댑터는 이 불변식을 데이터베이스 트랜잭션과 고유 제약으로
다시 강제해야 한다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from threading import RLock
from typing import Callable, TypeVar


class ExperimentError(ValueError):
    """실험 계약 위반."""


class CollectionDisabled(ExperimentError):
    """실제 참가자 수집이 동결표로 열리지 않음."""


class InvalidTransition(ExperimentError):
    """현재 단계에서 허용하지 않는 작업."""


class StateRevisionConflict(ExperimentError):
    """낙관적 잠금의 기대 상태 버전이 현재 버전과 다름."""


class IdempotencyConflict(ExperimentError):
    """같은 멱등 키가 다른 요청 본문에 재사용됨."""


class ImmutableRecordConflict(ExperimentError):
    """이미 동결된 세션 자료나 참가자 기록을 바꾸려 함."""


class ParticipantType(str, Enum):
    REAL = "real"
    SYNTHETIC = "synthetic"


class ExperimentStage(str, Enum):
    CONSENT = "consent"
    M1 = "M1"
    E1A = "E1a"
    M2 = "M2"
    E2 = "E2"
    E1B = "E1b"
    A1 = "A1"
    E3 = "E3"
    M3 = "M3"
    COMPLETE = "complete"
    WITHDRAWN = "withdrawn"


# Shared by persistence and rehearsal so the documented procedure cannot drift
# from the executable participant state machine.
LEGACY_PROCEDURE_CONFIG = {
    "version": "aipol-pension-3-measurements-v1",
    "stages": ["consent", "E1a", "M1", "E1b", "M2", "E2", "M3", "complete"],
    "exposures": {"E1a": "calculator", "E1b": "expert", "E2": "ai"},
    "measurements": ["M1", "M2", "M3"],
    "option_order": "stable-per-participant",
    "e2_release": "registration-closed-and-m2-barrier",
}

PROCEDURE_CONFIG = {
    "version": "aipol-pension-3-measurements-v2",
    "stages": ["consent", "M1", "E1a", "M2", "E2", "E1b", "A1", "E3", "M3", "complete"],
    "exposures": {"E1a": "calculator", "E2": "d", "E1b": "expert", "E3": "d_prime"},
    "feedback": {"A1": "audience"},
    "measurements": ["M1", "M2", "M3"],
    "option_order": "stable-per-participant",
    "e2_release": "registration-closed-and-m2-barrier",
}


class ArtifactKind(str, Enum):
    PERSONAL_COMPARISON = "personal_comparison"
    EXPERT_EXPLANATION = "expert_explanation"
    AI_OPINION = "ai_opinion"
    FINAL_AI_OPINION = "final_ai_opinion"


MEASUREMENT_FOR_STAGE = {
    ExperimentStage.M1: "M1",
    ExperimentStage.M2: "M2",
    ExperimentStage.M3: "M3",
}

LEGACY_NEXT_AFTER_MEASUREMENT = {
    "M1": ExperimentStage.E1B,
    "M2": ExperimentStage.E2,
    "M3": ExperimentStage.COMPLETE,
}

LEGACY_EXPOSURE_FOR_STAGE = {
    ExperimentStage.E1A: (ArtifactKind.PERSONAL_COMPARISON, 2, ExperimentStage.M1),
    ExperimentStage.E1B: (ArtifactKind.EXPERT_EXPLANATION, 4, ExperimentStage.M2),
    ExperimentStage.E2: (ArtifactKind.AI_OPINION, 6, ExperimentStage.M3),
}

NEXT_AFTER_MEASUREMENT = {
    "M1": ExperimentStage.E1A,
    "M2": ExperimentStage.E2,
    "M3": ExperimentStage.COMPLETE,
}

EXPOSURE_FOR_STAGE = {
    ExperimentStage.E1A: (ArtifactKind.PERSONAL_COMPARISON, 3, ExperimentStage.M2),
    ExperimentStage.E2: (ArtifactKind.AI_OPINION, 5, ExperimentStage.E1B),
    ExperimentStage.E1B: (ArtifactKind.EXPERT_EXPLANATION, 6, ExperimentStage.A1),
    ExperimentStage.E3: (ArtifactKind.FINAL_AI_OPINION, 8, ExperimentStage.M3),
}

REQUIRED_FREEZE_APPROVALS = frozenset(
    {
        "policy_options",
        "calculation",
        "measurement",
        "privacy",
        "research_ethics",
        "source_license",
        "procedure",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ExperimentError(f"{label}는 SHA-256 64자리 16진수여야 합니다")


def _require_iso_timestamp(value: str, label: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ExperimentError(f"{label}은 ISO 8601 형식이어야 합니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExperimentError(f"{label}에는 시간대가 포함되어야 합니다")


def content_hash(value: object) -> str:
    """JSON으로 표현 가능한 값의 안정적인 SHA-256."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FreezeApproval:
    category: str
    approved_by: str
    approved_at: str
    content_hash: str
    approval_id: str

    def validate(self) -> None:
        if not self.category or not self.approval_id or not self.approved_by or not self.approved_at:
            raise ExperimentError(
                "동결 승인의 category, approval_id, approved_by, approved_at은 필수입니다"
            )
        _require_iso_timestamp(self.approved_at, "동결 승인 approved_at")
        _require_hash(self.content_hash, "동결 승인 content_hash")


@dataclass(frozen=True)
class FreezeManifest:
    manifest_id: str
    experiment_version: str
    option_set_version: str
    measurement_spec_hash: str
    status: str = "draft"
    collection_enabled: bool = False
    approvals: tuple[FreezeApproval, ...] = ()

    def permits_real_collection(
        self,
        *,
        experiment_version: str,
        option_set_version: str,
        measurement_spec_hash: str,
    ) -> bool:
        for approval in self.approvals:
            approval.validate()
        categories = {approval.category for approval in self.approvals}
        return (
            bool(self.manifest_id)
            and self.status == "frozen"
            and self.collection_enabled is True
            and self.experiment_version == experiment_version
            and self.option_set_version == option_set_version
            and self.measurement_spec_hash == measurement_spec_hash
            and REQUIRED_FREEZE_APPROVALS <= categories
        )


@dataclass(frozen=True)
class PolicyOptionDefinition:
    policy_option_id: str
    label: str
    policy_version: str

    def __post_init__(self) -> None:
        if not self.policy_option_id or not self.label or not self.policy_version:
            raise ExperimentError("정책안 ID, 표시명, 정책 버전은 필수입니다")


@dataclass(frozen=True)
class MeasurementSpec:
    question_id: str
    question_text_hash: str
    option_set_version: str
    confidence_min: int = 1
    confidence_max: int = 5

    def __post_init__(self) -> None:
        if not self.question_id or not self.option_set_version:
            raise ExperimentError("측정 문항 ID와 선택지 세트 버전은 필수입니다")
        _require_hash(self.question_text_hash, "question_text_hash")
        if self.confidence_min >= self.confidence_max:
            raise ExperimentError("confidence_min은 confidence_max보다 작아야 합니다")

    @property
    def spec_hash(self) -> str:
        return content_hash(asdict(self))


@dataclass(frozen=True)
class ArtifactApproval:
    approval_id: str
    approved_by: str
    approved_at: str
    content_hash: str

    def validate(self, artifact_hash: str) -> None:
        if not self.approval_id or not self.approved_by or not self.approved_at:
            raise ExperimentError("자료 승인 ID, 승인자, 승인 시각은 필수입니다")
        _require_iso_timestamp(self.approved_at, "자료 승인 approved_at")
        _require_hash(self.content_hash, "승인 content_hash")
        if self.content_hash != artifact_hash:
            raise ExperimentError("승인 해시와 자료 해시가 다릅니다")


@dataclass(frozen=True)
class ExperimentArtifact:
    artifact_id: str
    artifact_version: str
    kind: ArtifactKind
    content_hash: str
    approval: ArtifactApproval | None = None
    fallback_used: bool = False

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.artifact_version:
            raise ExperimentError("자료 ID와 버전은 필수입니다")
        _require_hash(self.content_hash, "자료 content_hash")

    def require_human_approval(self) -> None:
        if self.approval is None:
            raise ExperimentError(f"{self.kind.value} 자료는 사람 승인이 필요합니다")
        self.approval.validate(self.content_hash)


@dataclass(frozen=True)
class ConsentRecord:
    experiment_version: str
    session_id: str
    participant_pseudonym: str
    consent_version: str
    affirmed: bool
    consented_at: datetime
    state_revision: int
    idempotency_key: str


@dataclass(frozen=True)
class ExposureRecord:
    artifact_id: str
    artifact_version: str
    content_hash: str
    experiment_version: str
    session_id: str
    participant_pseudonym: str
    stage_sequence: int
    opened_at: datetime
    completed_at: datetime
    read_ack: bool
    fallback_used: bool
    approval_id: str | None
    state_revision: int
    idempotency_key: str


@dataclass(frozen=True)
class MeasurementRecord:
    experiment_version: str
    session_id: str
    state_revision: int
    participant_pseudonym: str
    participant_type: ParticipantType
    measurement_id: str
    choice: str | None
    stance: str | None
    reason: str | None
    confidence: int | None
    question_id: str
    measurement_spec_hash: str
    option_set_version: str
    option_order: tuple[str, ...]
    preceding_exposure_hash: str
    submitted_at: datetime
    idempotency_key: str


@dataclass(frozen=True)
class WithdrawalRecord:
    experiment_version: str
    session_id: str
    participant_pseudonym: str
    withdrawn_from: ExperimentStage
    reason: str | None
    withdrawn_at: datetime
    state_revision: int
    idempotency_key: str


@dataclass(frozen=True)
class AudienceFeedbackRecord:
    experiment_version: str
    session_id: str
    participant_pseudonym: str
    response: str | None
    abstained: bool
    submitted_at: datetime
    state_revision: int
    idempotency_key: str


@dataclass
class _Participant:
    pseudonym: str
    participant_type: ParticipantType
    option_order: tuple[str, ...]
    stage: ExperimentStage = ExperimentStage.CONSENT
    state_revision: int = 0


T = TypeVar("T")


class PensionExperimentSession:
    """한 세션의 참가자 상태와 append-only 기록을 관리한다.

    이 구현은 인메모리 참조 구현이다. 운영 저장소는 같은 멱등·고유·상태 버전 검사를
    한 데이터베이스 트랜잭션에서 수행해야 한다.
    """

    def __init__(
        self,
        *,
        experiment_version: str,
        session_id: str,
        measurement_spec: MeasurementSpec,
        policy_options: tuple[PolicyOptionDefinition, ...],
        freeze_manifest: FreezeManifest | None = None,
        procedure_config: dict | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not experiment_version or not session_id:
            raise ExperimentError("experiment_version과 session_id는 필수입니다")
        option_ids = tuple(option.policy_option_id for option in policy_options)
        if option_ids != ("A", "B", "C"):
            raise ExperimentError("AIPOL 주 선택 문항은 고정 순서의 정책안 A/B/C 세 개여야 합니다")
        if any(option.policy_version != measurement_spec.option_set_version for option in policy_options):
            raise ExperimentError("모든 정책안 버전은 option_set_version과 같아야 합니다")

        self.experiment_version = experiment_version
        self.session_id = session_id
        self.measurement_spec = measurement_spec
        self.policy_options = policy_options
        self.option_ids = option_ids
        self.freeze_manifest = freeze_manifest
        self.procedure_config = procedure_config or LEGACY_PROCEDURE_CONFIG
        procedure_version = self.procedure_config.get("version")
        if procedure_version not in {
            LEGACY_PROCEDURE_CONFIG["version"], PROCEDURE_CONFIG["version"]
        }:
            raise ExperimentError("지원하지 않는 행사 절차 버전입니다")
        self._legacy_procedure = procedure_version == LEGACY_PROCEDURE_CONFIG["version"]
        self._clock = clock
        self._lock = RLock()
        self._participants: dict[str, _Participant] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, object]] = {}
        self._consents: list[ConsentRecord] = []
        self._exposures: list[ExposureRecord] = []
        self._measurements: list[MeasurementRecord] = []
        self._withdrawals: list[WithdrawalRecord] = []
        self._audience_feedback: list[AudienceFeedbackRecord] = []
        self._expert_artifact: ExperimentArtifact | None = None
        self._ai_artifact: ExperimentArtifact | None = None
        self._final_ai_artifact: ExperimentArtifact | None = None

    @property
    def collection_enabled(self) -> bool:
        return self.freeze_manifest is not None and self.freeze_manifest.permits_real_collection(
            experiment_version=self.experiment_version,
            option_set_version=self.measurement_spec.option_set_version,
            measurement_spec_hash=self.measurement_spec.spec_hash,
        )

    @property
    def consent_records(self) -> tuple[ConsentRecord, ...]:
        return tuple(self._consents)

    @property
    def exposure_records(self) -> tuple[ExposureRecord, ...]:
        return tuple(self._exposures)

    @property
    def measurement_records(self) -> tuple[MeasurementRecord, ...]:
        return tuple(self._measurements)

    @property
    def withdrawal_records(self) -> tuple[WithdrawalRecord, ...]:
        return tuple(self._withdrawals)

    @property
    def audience_feedback_records(self) -> tuple[AudienceFeedbackRecord, ...]:
        return tuple(self._audience_feedback)

    def register_participant(
        self,
        participant_pseudonym: str,
        participant_type: ParticipantType | str,
        *,
        option_order: tuple[str, ...] | None = None,
    ) -> None:
        with self._lock:
            if not participant_pseudonym:
                raise ExperimentError("participant_pseudonym은 필수입니다")
            if participant_pseudonym in self._participants:
                raise ImmutableRecordConflict("이미 등록된 참가자입니다")
            try:
                participant_type = ParticipantType(participant_type)
            except ValueError as exc:
                raise ExperimentError("participant_type은 real 또는 synthetic이어야 합니다") from exc
            if participant_type is ParticipantType.REAL and not self.collection_enabled:
                raise CollectionDisabled("서명된 동결표가 없어 실제 참가자 수집이 닫혀 있습니다")
            order = option_order or self.option_ids
            if len(order) != len(self.option_ids) or set(order) != set(self.option_ids):
                raise ExperimentError("표시 순서는 동결된 정책안 ID를 정확히 한 번씩 포함해야 합니다")
            self._participants[participant_pseudonym] = _Participant(
                participant_pseudonym, participant_type, tuple(order)
            )

    def participant_state(self, participant_pseudonym: str) -> tuple[ExperimentStage, int]:
        participant = self._participant(participant_pseudonym)
        return participant.stage, participant.state_revision

    def set_expert_artifact(self, artifact: ExperimentArtifact) -> None:
        if artifact.kind is not ArtifactKind.EXPERT_EXPLANATION:
            raise ExperimentError("전문가 자료 종류가 아닙니다")
        artifact.require_human_approval()
        with self._lock:
            self._expert_artifact = self._set_once(self._expert_artifact, artifact, "전문가 자료")

    def set_session_ai_artifact(self, artifact: ExperimentArtifact) -> None:
        if artifact.kind is not ArtifactKind.AI_OPINION:
            raise ExperimentError("AI 의견 자료 종류가 아닙니다")
        artifact.require_human_approval()
        with self._lock:
            self._ai_artifact = self._set_once(self._ai_artifact, artifact, "세션 AI 자료")

    def set_session_final_ai_artifact(self, artifact: ExperimentArtifact) -> None:
        if artifact.kind is not ArtifactKind.FINAL_AI_OPINION:
            raise ExperimentError("D′ 자료 종류가 아닙니다")
        artifact.require_human_approval()
        with self._lock:
            self._final_ai_artifact = self._set_once(
                self._final_ai_artifact, artifact, "세션 D′ 자료"
            )

    def record_consent(
        self,
        participant_pseudonym: str,
        *,
        consent_version: str,
        affirmed: bool,
        expected_revision: int,
        idempotency_key: str,
    ) -> ConsentRecord:
        participant = self._participant(participant_pseudonym)
        payload = {"op": "consent", "consent_version": consent_version, "affirmed": affirmed}

        def action() -> ConsentRecord:
            self._require_stage(participant, ExperimentStage.CONSENT)
            if not consent_version:
                raise ExperimentError("consent_version은 필수입니다")
            if affirmed is not True:
                raise ExperimentError("명시적인 참여 동의(affirmed=true)가 필요합니다")
            participant.state_revision += 1
            participant.stage = (
                ExperimentStage.E1A if self._legacy_procedure else ExperimentStage.M1
            )
            record = ConsentRecord(
                self.experiment_version,
                self.session_id,
                participant.pseudonym,
                consent_version,
                affirmed,
                self._now(),
                participant.state_revision,
                idempotency_key,
            )
            self._consents.append(record)
            return record

        return self._execute(participant, expected_revision, idempotency_key, payload, action)

    def record_exposure(
        self,
        participant_pseudonym: str,
        artifact: ExperimentArtifact,
        *,
        read_ack: bool,
        opened_at: datetime | None = None,
        expected_revision: int,
        idempotency_key: str,
    ) -> ExposureRecord:
        participant = self._participant(participant_pseudonym)
        payload = {
            "op": "exposure",
            "artifact": asdict(artifact),
            "read_ack": read_ack,
            "opened_at": opened_at.isoformat() if opened_at else None,
        }

        def action() -> ExposureRecord:
            try:
                exposure_map = (
                    LEGACY_EXPOSURE_FOR_STAGE if self._legacy_procedure else EXPOSURE_FOR_STAGE
                )
                expected_kind, sequence, next_stage = exposure_map[participant.stage]
            except KeyError as exc:
                raise InvalidTransition(f"{participant.stage.value} 단계에서는 자료 노출을 기록할 수 없습니다") from exc
            if artifact.kind is not expected_kind:
                raise InvalidTransition(f"{participant.stage.value} 단계 자료 종류가 아닙니다")
            if not read_ack:
                raise ExperimentError("자료 확인 완료(read_ack)가 있어야 다음 단계로 이동합니다")
            if expected_kind is ArtifactKind.EXPERT_EXPLANATION:
                self._require_session_artifact(self._expert_artifact, artifact, "전문가")
            elif expected_kind is ArtifactKind.AI_OPINION:
                self._require_session_artifact(self._ai_artifact, artifact, "AI")
            elif expected_kind is ArtifactKind.FINAL_AI_OPINION:
                self._require_session_artifact(self._final_ai_artifact, artifact, "D′")

            now = self._now()
            effective_opened_at = opened_at or now
            if effective_opened_at.tzinfo is None or effective_opened_at > now:
                raise ExperimentError("자료 opened_at은 시간대가 있는 완료 이전 시각이어야 합니다")
            participant.state_revision += 1
            participant.stage = next_stage
            record = ExposureRecord(
                artifact.artifact_id,
                artifact.artifact_version,
                artifact.content_hash,
                self.experiment_version,
                self.session_id,
                participant.pseudonym,
                sequence,
                effective_opened_at,
                now,
                True,
                artifact.fallback_used,
                artifact.approval.approval_id if artifact.approval else None,
                participant.state_revision,
                idempotency_key,
            )
            self._exposures.append(record)
            return record

        return self._execute(participant, expected_revision, idempotency_key, payload, action)

    def submit_audience_feedback(
        self,
        participant_pseudonym: str,
        *,
        response: str | None,
        abstained: bool,
        expected_revision: int,
        idempotency_key: str,
    ) -> AudienceFeedbackRecord:
        participant = self._participant(participant_pseudonym)
        cleaned = response.strip() if isinstance(response, str) else None
        payload = {"op": "audience_feedback", "response": cleaned, "abstained": abstained}

        def action() -> AudienceFeedbackRecord:
            self._require_stage(participant, ExperimentStage.A1)
            if not self._legacy_procedure and abstained is not True and not cleaned:
                raise ExperimentError("청중 의견을 입력하거나 의견 보류를 선택해야 합니다")
            if cleaned and len(cleaned) > 2_000:
                raise ExperimentError("청중 의견은 2,000자 이하여야 합니다")
            if abstained is True and cleaned:
                raise ExperimentError("의견 보류와 청중 의견을 함께 제출할 수 없습니다")
            participant.state_revision += 1
            participant.stage = ExperimentStage.E3
            record = AudienceFeedbackRecord(
                self.experiment_version,
                self.session_id,
                participant.pseudonym,
                cleaned,
                abstained,
                self._now(),
                participant.state_revision,
                idempotency_key,
            )
            self._audience_feedback.append(record)
            return record

        return self._execute(participant, expected_revision, idempotency_key, payload, action)

    def submit_measurement(
        self,
        participant_pseudonym: str,
        measurement_id: str,
        *,
        choice: str | None,
        reason: str | None,
        confidence: int | None,
        expected_revision: int,
        idempotency_key: str,
        stance: str | None = None,
    ) -> MeasurementRecord:
        participant = self._participant(participant_pseudonym)
        payload = {
            "op": "measurement",
            "measurement_id": measurement_id,
            "choice": choice,
            "stance": stance,
            "reason": reason,
            "confidence": confidence,
        }

        def action() -> MeasurementRecord:
            expected_measurement = MEASUREMENT_FOR_STAGE.get(participant.stage)
            if expected_measurement != measurement_id:
                raise InvalidTransition(
                    f"현재 {participant.stage.value} 단계에서 {measurement_id} 제출은 허용되지 않습니다"
                )
            if choice is not None and choice not in self.option_ids:
                raise ExperimentError("동결된 정책안 ID가 아닌 선택입니다")
            if measurement_id == "M2" and not self._legacy_procedure:
                if stance not in ("accept", "conditional", "reject"):
                    raise ExperimentError("M2에는 수용·조건부 수용·비선택 상태가 필요합니다")
                if stance in ("conditional", "reject") and not (reason or "").strip():
                    raise ExperimentError("조건부 수용과 비선택에는 이유가 필요합니다")
            elif stance is not None:
                raise ExperimentError("수용 상태는 새 절차의 M2에서만 제출할 수 있습니다")
            if confidence is not None and not (
                self.measurement_spec.confidence_min
                <= confidence
                <= self.measurement_spec.confidence_max
            ):
                raise ExperimentError("confidence가 동결된 척도 밖입니다")
            exposure_hash = self._preceding_exposure_hash(participant.pseudonym, measurement_id)
            participant.state_revision += 1
            transition_map = (
                LEGACY_NEXT_AFTER_MEASUREMENT if self._legacy_procedure else NEXT_AFTER_MEASUREMENT
            )
            participant.stage = transition_map[measurement_id]
            record = MeasurementRecord(
                self.experiment_version,
                self.session_id,
                participant.state_revision,
                participant.pseudonym,
                participant.participant_type,
                measurement_id,
                choice,
                stance,
                reason,
                confidence,
                self.measurement_spec.question_id,
                self.measurement_spec.spec_hash,
                self.measurement_spec.option_set_version,
                participant.option_order,
                exposure_hash,
                self._now(),
                idempotency_key,
            )
            self._measurements.append(record)
            return record

        return self._execute(participant, expected_revision, idempotency_key, payload, action)

    def withdraw_participant(
        self,
        participant_pseudonym: str,
        *,
        reason: str | None,
        expected_revision: int,
        idempotency_key: str,
    ) -> WithdrawalRecord:
        participant = self._participant(participant_pseudonym)
        payload = {"op": "withdraw", "reason": reason}

        def action() -> WithdrawalRecord:
            if participant.stage in (ExperimentStage.COMPLETE, ExperimentStage.WITHDRAWN):
                raise InvalidTransition("완료 또는 철회 상태는 다시 변경할 수 없습니다")
            previous = participant.stage
            participant.state_revision += 1
            participant.stage = ExperimentStage.WITHDRAWN
            record = WithdrawalRecord(
                self.experiment_version,
                self.session_id,
                participant.pseudonym,
                previous,
                reason,
                self._now(),
                participant.state_revision,
                idempotency_key,
            )
            self._withdrawals.append(record)
            return record

        return self._execute(participant, expected_revision, idempotency_key, payload, action)

    def transition_table(
        self,
        from_measurement: str,
        to_measurement: str,
        *,
        participant_type: ParticipantType = ParticipantType.REAL,
    ) -> dict[tuple[str | None, str | None], int]:
        """두 측정 모두 제출한 사람만 분모로 삼은 개인 내 전이표."""
        by_participant: dict[str, dict[str, str | None]] = {}
        for record in self._measurements:
            if record.participant_type is participant_type:
                by_participant.setdefault(record.participant_pseudonym, {})[record.measurement_id] = record.choice
        table: dict[tuple[str | None, str | None], int] = {}
        for measurements in by_participant.values():
            if from_measurement in measurements and to_measurement in measurements:
                key = (measurements[from_measurement], measurements[to_measurement])
                table[key] = table.get(key, 0) + 1
        return table

    def funnel_counts(
        self, *, participant_type: ParticipantType = ParticipantType.REAL
    ) -> dict[str, int]:
        participants = {
            pseudonym
            for pseudonym, participant in self._participants.items()
            if participant.participant_type is participant_type
        }
        exposure_sets = {
            sequence: {
                record.participant_pseudonym
                for record in self._exposures
                if record.stage_sequence == sequence and record.participant_pseudonym in participants
            }
            for sequence in ((2, 4, 6) if self._legacy_procedure else (3, 5, 6, 8))
        }
        measurement_sets = {
            measurement: {
                record.participant_pseudonym
                for record in self._measurements
                if record.measurement_id == measurement and record.participant_pseudonym in participants
            }
            for measurement in ("M1", "M2", "M3")
        }
        result = {
            "registered": len(participants),
            "consented": sum(record.participant_pseudonym in participants for record in self._consents),
            "E1a": len(exposure_sets[2 if self._legacy_procedure else 3]),
            "M1": len(measurement_sets["M1"]),
            "E1b": len(exposure_sets[4 if self._legacy_procedure else 6]),
            "M2": len(measurement_sets["M2"]),
            "E2": len(exposure_sets[6 if self._legacy_procedure else 5]),
            "M3": len(measurement_sets["M3"]),
            "complete": sum(
                participant.participant_type is participant_type
                and participant.stage is ExperimentStage.COMPLETE
                for participant in self._participants.values()
            ),
            "withdrawn": sum(
                participant.participant_type is participant_type
                and participant.stage is ExperimentStage.WITHDRAWN
                for participant in self._participants.values()
            ),
        }
        if not self._legacy_procedure:
            result["A1"] = sum(
                record.participant_pseudonym in participants
                for record in self._audience_feedback
            )
            result["E3"] = len(exposure_sets[8])
        return result

    def _participant(self, participant_pseudonym: str) -> _Participant:
        try:
            return self._participants[participant_pseudonym]
        except KeyError as exc:
            raise ExperimentError("등록되지 않은 참가자입니다") from exc

    @staticmethod
    def _set_once(
        current: ExperimentArtifact | None,
        new: ExperimentArtifact,
        label: str,
    ) -> ExperimentArtifact:
        if current is None:
            return new
        if current == new:
            return current
        raise ImmutableRecordConflict(f"{label}는 세션 중 교체할 수 없습니다")

    @staticmethod
    def _require_session_artifact(
        selected: ExperimentArtifact | None,
        supplied: ExperimentArtifact,
        label: str,
    ) -> None:
        if selected is None:
            raise ExperimentError(f"승인된 세션 {label} 자료가 아직 없습니다")
        if selected != supplied:
            raise ImmutableRecordConflict(f"참가자별로 다른 {label} 자료를 노출할 수 없습니다")

    @staticmethod
    def _require_stage(participant: _Participant, expected: ExperimentStage) -> None:
        if participant.stage is not expected:
            raise InvalidTransition(
                f"현재 단계는 {participant.stage.value}이며 {expected.value} 작업을 할 수 없습니다"
            )

    def _preceding_exposure_hash(self, participant_pseudonym: str, measurement_id: str) -> str:
        if measurement_id == "M1" and not self._legacy_procedure:
            return content_hash([asdict(option) for option in self.policy_options])
        sequence = {
            "M1": 2,
            "M2": 4 if self._legacy_procedure else 3,
            "M3": 6 if self._legacy_procedure else 8,
        }[measurement_id]
        matches = [
            record.content_hash
            for record in self._exposures
            if record.participant_pseudonym == participant_pseudonym
            and record.stage_sequence == sequence
        ]
        if len(matches) != 1:
            raise InvalidTransition(f"{measurement_id} 직전 노출 기록이 정확히 하나여야 합니다")
        return matches[0]

    def _execute(
        self,
        participant: _Participant,
        expected_revision: int,
        idempotency_key: str,
        payload: object,
        action: Callable[[], T],
    ) -> T:
        with self._lock:
            if not idempotency_key:
                raise ExperimentError("idempotency_key는 필수입니다")
            key = (participant.pseudonym, idempotency_key)
            fingerprint = content_hash(payload)
            previous = self._idempotency.get(key)
            if previous is not None:
                previous_fingerprint, result = previous
                if previous_fingerprint != fingerprint:
                    raise IdempotencyConflict("같은 idempotency_key에 다른 payload가 제출되었습니다")
                return result  # type: ignore[return-value]
            if participant.state_revision != expected_revision:
                raise StateRevisionConflict(
                    f"expected_revision={expected_revision}, current={participant.state_revision}"
                )
            result = action()
            self._idempotency[key] = (fingerprint, result)
            return result

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ExperimentError("서버 시각은 timezone-aware datetime이어야 합니다")
        return value.astimezone(timezone.utc)
