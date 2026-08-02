"""AIPOL 3차 측정용 SQLite 어댑터.

기존 도메인 중립 회차 설문 테이블은 보존하고, AIPOL 연금 실험의 더 엄격한 상태·노출·
멱등 계약은 별도 append-only 테이블에서 강제한다. 모든 쓰기는 ``BEGIN IMMEDIATE`` 한
트랜잭션 안에서 낙관적 잠금과 고유 제약을 함께 확인한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import string
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Protocol
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
import secret_env  # noqa: E402
from policy_lab.domains.pension.experiment import (  # noqa: E402
    ArtifactApproval,
    ArtifactKind,
    CollectionDisabled,
    ExperimentArtifact,
    ExperimentError,
    ExperimentStage,
    FreezeApproval,
    FreezeManifest,
    IdempotencyConflict,
    ImmutableRecordConflict,
    MeasurementSpec,
    LEGACY_PROCEDURE_CONFIG,
    ParticipantType,
    PensionExperimentSession,
    PolicyOptionDefinition,
    PROCEDURE_CONFIG,
    REQUIRED_FREEZE_APPROVALS,
    StateRevisionConflict,
    content_hash,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS aipol_experiments (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  experiment_version TEXT NOT NULL,
  session_id TEXT NOT NULL,
  measurement_spec TEXT NOT NULL,
  question_text TEXT NOT NULL DEFAULT '',
  policy_options TEXT NOT NULL,
  freeze_manifest TEXT,
  freeze_manifest_anchor_id TEXT,
  consent_version TEXT NOT NULL,
  consent_text TEXT NOT NULL DEFAULT '',
  admission_code_hash TEXT,
  capacity INTEGER NOT NULL DEFAULT 0 CHECK(capacity >= 0),
  registration_open INTEGER NOT NULL DEFAULT 0 CHECK(registration_open IN (0,1)),
  e2_released INTEGER NOT NULL DEFAULT 0 CHECK(e2_released IN (0,1)),
  e2_selected_candidate_id TEXT,
  e2_m2_aggregate_hash TEXT,
  created_by TEXT NOT NULL DEFAULT 'legacy-unknown',
  credential_key_id TEXT NOT NULL DEFAULT 'legacy-event-session',
  procedure_config TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL,
  UNIQUE(experiment_version, session_id)
);

CREATE TABLE IF NOT EXISTS aipol_artifacts (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  artifact_id TEXT NOT NULL,
  artifact_version TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  content TEXT NOT NULL,
  approval_id TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  fallback_used INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, kind),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_canonical_documents (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category IN ('policy_options','calculation','measurement','privacy','research_ethics','source_license','procedure')),
  document_id TEXT NOT NULL,
  document_version TEXT NOT NULL,
  body TEXT NOT NULL,
  bound_settings_hash TEXT NOT NULL,
  evidence TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  approval_id TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  registered_by TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, category),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_canonical_drafts (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  category TEXT NOT NULL CHECK(category IN ('policy_options','calculation','measurement','privacy','research_ethics','source_license','procedure')),
  document_id TEXT NOT NULL,
  document_version TEXT NOT NULL,
  body TEXT NOT NULL,
  bound_settings_hash TEXT NOT NULL,
  evidence TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  editor_by TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, category),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_ai_candidates (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  candidate_role TEXT NOT NULL CHECK(candidate_role IN ('primary','fallback')),
  artifact_id TEXT NOT NULL,
  artifact_version TEXT NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  deployment TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  evidence_refs TEXT NOT NULL,
  m2_aggregate_hash TEXT,
  approval_id TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  registered_by TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, candidate_role),
  UNIQUE(experiment_id, artifact_id),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_e2_selections (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL UNIQUE,
  candidate_id TEXT NOT NULL,
  candidate_role TEXT NOT NULL,
  m2_aggregate_hash TEXT NOT NULL,
  m2_cutoff_at TEXT NOT NULL,
  selection_reason TEXT NOT NULL,
  selected_by TEXT NOT NULL,
  selected_at TEXT NOT NULL,
  candidate_content_hash TEXT NOT NULL,
  candidate_approval_hash TEXT NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id),
  FOREIGN KEY(candidate_id) REFERENCES aipol_ai_candidates(id)
);

CREATE TABLE IF NOT EXISTS aipol_m2_finalizations (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL UNIQUE,
  aggregate_hash TEXT NOT NULL,
  finalized_at TEXT NOT NULL,
  finalized_by TEXT NOT NULL,
  cohort_registered_count INTEGER NOT NULL,
  cohort_m2_count INTEGER NOT NULL,
  cohort_attrited_count INTEGER NOT NULL,
  barrier_hash TEXT NOT NULL,
  approval_id TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_freeze_settings_anchors (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL UNIQUE,
  settings_envelope TEXT NOT NULL,
  settings_hash TEXT NOT NULL,
  approval_id TEXT NOT NULL UNIQUE,
  approved_by TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_freeze_manifest_anchors (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL UNIQUE,
  manifest_envelope TEXT NOT NULL,
  manifest_hash TEXT NOT NULL,
  approval_id TEXT NOT NULL UNIQUE,
  approved_by TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_participants (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  pseudonym TEXT NOT NULL,
  token_hash TEXT NOT NULL,
  participant_type TEXT NOT NULL CHECK(participant_type IN ('real','synthetic')),
  option_order TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'consent',
  state_revision INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, pseudonym),
  UNIQUE(experiment_id, token_hash),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_synthetic_review_revocations (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  participant_id TEXT NOT NULL UNIQUE,
  revoked_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  revoked_at TEXT NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_synthetic_review_grants (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  participant_id TEXT NOT NULL UNIQUE,
  issued_by TEXT NOT NULL,
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_registration_nonces (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  nonce_hash TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  participant_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, nonce_hash),
  UNIQUE(experiment_id, idempotency_key),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_participant_recovery_codes (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  participant_id TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, code_hash),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_participant_recoveries (
  id TEXT PRIMARY KEY,
  recovery_code_id TEXT NOT NULL UNIQUE,
  participant_id TEXT NOT NULL,
  prior_token_hash TEXT NOT NULL,
  replacement_token_hash TEXT NOT NULL,
  recovered_at TEXT NOT NULL,
  FOREIGN KEY(recovery_code_id) REFERENCES aipol_participant_recovery_codes(id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_admission_seats (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, code_hash),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_admission_claims (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  seat_id TEXT NOT NULL UNIQUE,
  participant_id TEXT NOT NULL UNIQUE,
  claimed_at TEXT NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id),
  FOREIGN KEY(seat_id) REFERENCES aipol_admission_seats(id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_consents (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  experiment_version TEXT NOT NULL,
  session_id TEXT NOT NULL,
  consent_version TEXT NOT NULL,
  affirmed INTEGER NOT NULL CHECK(affirmed=1),
  consented_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_exposures (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  stage TEXT NOT NULL CHECK(stage IN ('E1a','E1b','E2')),
  artifact_id TEXT NOT NULL,
  artifact_version TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  stage_sequence INTEGER NOT NULL,
  opened_at TEXT NOT NULL,
  completed_at TEXT NOT NULL,
  read_ack INTEGER NOT NULL CHECK(read_ack=1),
  fallback_used INTEGER NOT NULL DEFAULT 0,
  approval_id TEXT,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(participant_id, stage),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_exposure_opens (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  stage TEXT NOT NULL CHECK(stage IN ('E1a','E1b','E2')),
  artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(participant_id, stage),
  UNIQUE(participant_id, idempotency_key),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_measurements (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  experiment_version TEXT NOT NULL,
  session_id TEXT NOT NULL,
  measurement_id TEXT NOT NULL CHECK(measurement_id IN ('M1','M2','M3')),
  participant_type TEXT NOT NULL CHECK(participant_type IN ('real','synthetic')),
  choice TEXT,
  stance TEXT CHECK(stance IN ('accept','conditional','reject') OR stance IS NULL),
  reason TEXT,
  confidence INTEGER,
  question_id TEXT NOT NULL,
  measurement_spec_hash TEXT NOT NULL,
  option_set_version TEXT NOT NULL,
  option_order TEXT NOT NULL,
  preceding_exposure_hash TEXT NOT NULL,
  submitted_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(experiment_version, session_id, participant_id, measurement_id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_audience_feedback (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  response TEXT,
  abstained INTEGER NOT NULL CHECK(abstained IN (0,1)),
  submitted_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  CHECK((abstained=1 AND response IS NULL) OR (abstained=0 AND length(trim(response)) > 0)),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

-- E3 exists only in procedure v2.  Separate tables keep the legacy exposure
-- table and its CHECK constraint byte-for-byte compatible with existing v1 DBs.
CREATE TABLE IF NOT EXISTS aipol_v2_exposure_opens (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  artifact_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(participant_id, idempotency_key),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_v2_exposures (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  artifact_id TEXT NOT NULL,
  artifact_version TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  stage_sequence INTEGER NOT NULL CHECK(stage_sequence=8),
  opened_at TEXT NOT NULL,
  completed_at TEXT NOT NULL,
  read_ack INTEGER NOT NULL CHECK(read_ack=1),
  approval_id TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(participant_id, idempotency_key),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_withdrawals (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  withdrawn_from TEXT NOT NULL,
  reason TEXT,
  withdrawn_at TEXT NOT NULL,
  actor TEXT NOT NULL,
  cutoff_at TEXT,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_secondary_evaluations (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  measurement_id TEXT NOT NULL CHECK(measurement_id='M3'),
  artifact_id TEXT NOT NULL,
  acceptance INTEGER NOT NULL CHECK(acceptance BETWEEN 1 AND 5),
  reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(participant_id, measurement_id, artifact_id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_idempotency (
  participant_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response TEXT NOT NULL,
  created_at REAL NOT NULL,
  PRIMARY KEY(participant_id, idempotency_key),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_approval_events (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  approval_id TEXT NOT NULL UNIQUE,
  editor_by TEXT NOT NULL,
  approver_by TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(experiment_id, object_type, object_id),
  CHECK(editor_by <> approver_by),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_calculator_receipts (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  participant_id TEXT NOT NULL,
  receipt_id TEXT NOT NULL,
  contract_hash TEXT NOT NULL,
  verified_at TEXT NOT NULL,
  verifier_id TEXT NOT NULL,
  receipt_hash TEXT NOT NULL,
  UNIQUE(experiment_id, receipt_id),
  UNIQUE(participant_id),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_experiment_audit_outbox (
  event_id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  experiment_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_aipol_experiment_audit_pending
ON aipol_experiment_audit_outbox(delivered_at, created_at);

CREATE TRIGGER IF NOT EXISTS aipol_consents_no_update
BEFORE UPDATE ON aipol_consents BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_consents_no_delete
BEFORE DELETE ON aipol_consents BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_registration_nonces_no_update
BEFORE UPDATE ON aipol_registration_nonces BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_registration_nonces_no_delete
BEFORE DELETE ON aipol_registration_nonces BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admission_seats_no_update
BEFORE UPDATE ON aipol_admission_seats BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admission_seats_no_delete
BEFORE DELETE ON aipol_admission_seats BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admission_claims_no_update
BEFORE UPDATE ON aipol_admission_claims BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_admission_claims_no_delete
BEFORE DELETE ON aipol_admission_claims BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_exposures_no_update
BEFORE UPDATE ON aipol_exposures BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_exposures_no_delete
BEFORE DELETE ON aipol_exposures BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_exposure_opens_no_update
BEFORE UPDATE ON aipol_exposure_opens BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_exposure_opens_no_delete
BEFORE DELETE ON aipol_exposure_opens BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_measurements_no_update
BEFORE UPDATE ON aipol_measurements BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_measurements_no_delete
BEFORE DELETE ON aipol_measurements BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_audience_feedback_no_update
BEFORE UPDATE ON aipol_audience_feedback BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_audience_feedback_no_delete
BEFORE DELETE ON aipol_audience_feedback BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_v2_exposure_opens_no_update
BEFORE UPDATE ON aipol_v2_exposure_opens BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_v2_exposure_opens_no_delete
BEFORE DELETE ON aipol_v2_exposure_opens BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_v2_exposures_no_update
BEFORE UPDATE ON aipol_v2_exposures BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_v2_exposures_no_delete
BEFORE DELETE ON aipol_v2_exposures BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_withdrawals_no_update
BEFORE UPDATE ON aipol_withdrawals BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_withdrawals_no_delete
BEFORE DELETE ON aipol_withdrawals BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_secondary_no_update
BEFORE UPDATE ON aipol_secondary_evaluations BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_secondary_no_delete
BEFORE DELETE ON aipol_secondary_evaluations BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_artifacts_no_update
BEFORE UPDATE ON aipol_artifacts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_artifacts_no_delete
BEFORE DELETE ON aipol_artifacts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_canonical_documents_no_update
BEFORE UPDATE ON aipol_canonical_documents BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_canonical_documents_no_delete
BEFORE DELETE ON aipol_canonical_documents BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_canonical_drafts_no_update
BEFORE UPDATE ON aipol_canonical_drafts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_canonical_drafts_no_delete
BEFORE DELETE ON aipol_canonical_drafts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_ai_candidates_no_update
BEFORE UPDATE ON aipol_ai_candidates BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_ai_candidates_no_delete
BEFORE DELETE ON aipol_ai_candidates BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_e2_selections_no_update
BEFORE UPDATE ON aipol_e2_selections BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_e2_selections_no_delete
BEFORE DELETE ON aipol_e2_selections BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m2_finalizations_no_update
BEFORE UPDATE ON aipol_m2_finalizations BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m2_finalizations_no_delete
BEFORE DELETE ON aipol_m2_finalizations BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_freeze_settings_anchors_no_update
BEFORE UPDATE ON aipol_freeze_settings_anchors BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_freeze_settings_anchors_no_delete
BEFORE DELETE ON aipol_freeze_settings_anchors BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_freeze_manifest_anchors_no_update
BEFORE UPDATE ON aipol_freeze_manifest_anchors BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_freeze_manifest_anchors_no_delete
BEFORE DELETE ON aipol_freeze_manifest_anchors BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_approval_events_no_update
BEFORE UPDATE ON aipol_approval_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_approval_events_no_delete
BEFORE DELETE ON aipol_approval_events BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_calculator_receipts_no_update
BEFORE UPDATE ON aipol_calculator_receipts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_calculator_receipts_no_delete
BEFORE DELETE ON aipol_calculator_receipts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_participant_recovery_codes_no_update
BEFORE UPDATE ON aipol_participant_recovery_codes BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_participant_recovery_codes_no_delete
BEFORE DELETE ON aipol_participant_recovery_codes BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_participant_recoveries_no_update
BEFORE UPDATE ON aipol_participant_recoveries BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_participant_recoveries_no_delete
BEFORE DELETE ON aipol_participant_recoveries BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_synthetic_review_revocations_no_update
BEFORE UPDATE ON aipol_synthetic_review_revocations BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_synthetic_review_revocations_no_delete
BEFORE DELETE ON aipol_synthetic_review_revocations BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_synthetic_review_grants_no_update
BEFORE UPDATE ON aipol_synthetic_review_grants BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_synthetic_review_grants_no_delete
BEFORE DELETE ON aipol_synthetic_review_grants BEGIN SELECT RAISE(ABORT, 'append-only'); END;

CREATE INDEX IF NOT EXISTS idx_aipol_participants_experiment_type
ON aipol_participants(experiment_id, participant_type);
CREATE INDEX IF NOT EXISTS idx_aipol_exposures_participant_revision
ON aipol_exposures(participant_id, state_revision);
CREATE INDEX IF NOT EXISTS idx_aipol_measurements_participant_revision
ON aipol_measurements(participant_id, state_revision);
"""


class ParticipantAuthenticationError(ExperimentError):
    """참여 토큰이 없거나 실험에 속하지 않음."""


class CompletionReceiptVerifier(Protocol):
    """Deployment port for verification. This service never mints receipts."""

    verifier_id: str

    def verify(self, receipt: dict, contract: dict, context: dict) -> str:
        """Return the immutable external receipt id or raise ExperimentError."""


_completion_receipt_verifier: CompletionReceiptVerifier | None = None


def configure_completion_receipt_verifier(verifier: CompletionReceiptVerifier | None) -> None:
    global _completion_receipt_verifier
    _completion_receipt_verifier = verifier


def completion_receipt_configured() -> bool:
    return _completion_receipt_verifier is not None


def _validate_admission_code(value: str) -> str:
    """Require a high-entropy server-generated event admission credential."""
    code = value.strip()
    if not 16 <= len(code) <= 128:
        raise ExperimentError("참여코드는 16~128자여야 합니다")
    if any(character.isspace() for character in code):
        raise ExperimentError("참여코드에는 공백을 사용할 수 없습니다")
    if any(character not in string.ascii_letters + string.digits + string.punctuation for character in code):
        raise ExperimentError("참여코드는 ASCII 영문, 숫자, 기호만 사용할 수 있습니다")
    classes = sum((
        any(character.islower() for character in code),
        any(character.isupper() for character in code),
        any(character.isdigit() for character in code),
        any(character in string.punctuation for character in code),
    ))
    if classes < 3:
        raise ExperimentError("참여코드는 대·소문자, 숫자, 기호 중 3종 이상과 8개 이상의 서로 다른 문자를 포함해야 합니다")
    return code


def _backfill_freeze_manifest_anchors(connection: sqlite3.Connection) -> None:
    """Seal pre-anchor manifests exactly once during an in-place schema upgrade."""
    rows = connection.execute(
        "SELECT * FROM aipol_experiments WHERE freeze_manifest IS NOT NULL "
        "AND freeze_manifest_anchor_id IS NULL"
    ).fetchall()
    for row in rows:
        try:
            envelope = json.loads(row["freeze_manifest"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ImmutableRecordConflict("legacy freeze manifest is malformed") from exc
        if not isinstance(envelope, dict):
            raise ImmutableRecordConflict("legacy freeze manifest must be an object")
        experiment_id = str(row["id"])
        editor_by = str(row["created_by"] or "legacy-unknown")
        approved_by = str(envelope.get("frozen_by") or "server:legacy-freeze-migration")
        if hmac.compare_digest(editor_by, approved_by):
            approved_by = "server:legacy-freeze-migration"
        approved_at = str(envelope.get("frozen_at") or "")
        try:
            datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError:
            approved_at = datetime.fromtimestamp(
                float(row["created_at"]), timezone.utc
            ).isoformat()
        suffix = hashlib.sha256(experiment_id.encode()).hexdigest()[:16]
        anchor_id = f"fma-legacy-{suffix}"
        approval_id = f"freeze-manifest-migration:{experiment_id}"
        envelope = {
            **envelope,
            "manifest_approval": {
                "approval_id": approval_id,
                "approved_by": approved_by,
                "approved_at": approved_at,
            },
        }
        digest = content_hash(envelope)
        connection.execute(
            "INSERT INTO aipol_approval_events(id,experiment_id,object_type,object_id,"
            "content_hash,approval_id,editor_by,approver_by,approved_at,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                f"av-{suffix}", experiment_id, "freeze_manifest", anchor_id,
                digest, approval_id, editor_by, approved_by, approved_at, time.time(),
            ),
        )
        connection.execute(
            "INSERT INTO aipol_freeze_manifest_anchors(id,experiment_id,manifest_envelope,"
            "manifest_hash,approval_id,approved_by,approved_at,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                anchor_id, experiment_id, _json(envelope), digest, approval_id,
                approved_by, approved_at, time.time(),
            ),
        )
        connection.execute(
            "UPDATE aipol_experiments SET freeze_manifest=NULL,freeze_manifest_anchor_id=? "
            "WHERE id=? AND freeze_manifest_anchor_id IS NULL",
            (anchor_id, experiment_id),
        )


def init() -> None:
    with db._conn() as connection:
        connection.executescript(_SCHEMA)
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(aipol_experiments)")}
        if "question_text" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN question_text TEXT NOT NULL DEFAULT ''"
            )
        if "consent_text" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN consent_text TEXT NOT NULL DEFAULT ''"
            )
        if "admission_code_hash" not in columns:
            connection.execute("ALTER TABLE aipol_experiments ADD COLUMN admission_code_hash TEXT")
        if "capacity" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN capacity INTEGER NOT NULL DEFAULT 0 CHECK(capacity >= 0)"
            )
        if "registration_open" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN registration_open INTEGER NOT NULL DEFAULT 0 CHECK(registration_open IN (0,1))"
            )
        if "e2_released" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN e2_released INTEGER NOT NULL DEFAULT 0 CHECK(e2_released IN (0,1))"
            )
        if "e2_selected_candidate_id" not in columns:
            connection.execute("ALTER TABLE aipol_experiments ADD COLUMN e2_selected_candidate_id TEXT")
        if "e2_m2_aggregate_hash" not in columns:
            connection.execute("ALTER TABLE aipol_experiments ADD COLUMN e2_m2_aggregate_hash TEXT")
        if "created_by" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN created_by TEXT NOT NULL DEFAULT 'legacy-unknown'"
            )
        if "credential_key_id" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN credential_key_id TEXT NOT NULL DEFAULT 'legacy-event-session'"
            )
        if "procedure_config" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN procedure_config TEXT NOT NULL DEFAULT '{}'"
            )
        if "freeze_manifest_anchor_id" not in columns:
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN freeze_manifest_anchor_id TEXT"
            )
        selection_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(aipol_e2_selections)")
        }
        if "candidate_content_hash" not in selection_columns:
            connection.execute(
                "ALTER TABLE aipol_e2_selections ADD COLUMN candidate_content_hash TEXT NOT NULL DEFAULT ''"
            )
        if "candidate_approval_hash" not in selection_columns:
            connection.execute(
                "ALTER TABLE aipol_e2_selections ADD COLUMN candidate_approval_hash TEXT NOT NULL DEFAULT ''"
            )
        finalization_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(aipol_m2_finalizations)")
        }
        for column, declaration in (
            ("cohort_registered_count", "INTEGER NOT NULL DEFAULT 0"),
            ("cohort_m2_count", "INTEGER NOT NULL DEFAULT 0"),
            ("cohort_attrited_count", "INTEGER NOT NULL DEFAULT 0"),
            ("barrier_hash", "TEXT NOT NULL DEFAULT ''"),
            ("approval_id", "TEXT NOT NULL DEFAULT ''"),
            ("approved_at", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in finalization_columns:
                connection.execute(
                    f"ALTER TABLE aipol_m2_finalizations ADD COLUMN {column} {declaration}"
                )
        consent_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(aipol_consents)")
        }
        if "affirmed" not in consent_columns:
            connection.execute(
                "ALTER TABLE aipol_consents ADD COLUMN affirmed INTEGER CHECK(affirmed=1)"
            )
        measurement_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(aipol_measurements)")
        }
        if "stance" not in measurement_columns:
            connection.execute(
                "ALTER TABLE aipol_measurements ADD COLUMN stance TEXT "
                "CHECK(stance IN ('accept','conditional','reject') OR stance IS NULL)"
            )
        withdrawal_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(aipol_withdrawals)")
        }
        if "actor" not in withdrawal_columns:
            connection.execute("ALTER TABLE aipol_withdrawals ADD COLUMN actor TEXT")
        if "cutoff_at" not in withdrawal_columns:
            connection.execute("ALTER TABLE aipol_withdrawals ADD COLUMN cutoff_at TEXT")
        _backfill_freeze_manifest_anchors(connection)
        ttl = _synthetic_review_ttl_seconds()
        legacy_synthetic = connection.execute(
            "SELECT p.* FROM aipol_participants p "
            "LEFT JOIN aipol_synthetic_review_grants g ON g.participant_id=p.id "
            "WHERE p.participant_type='synthetic' AND g.participant_id IS NULL"
        ).fetchall()
        for participant in legacy_synthetic:
            issued_at = datetime.fromtimestamp(float(participant["created_at"]), timezone.utc)
            connection.execute(
                "INSERT INTO aipol_synthetic_review_grants VALUES(?,?,?,?,?,?)",
                (
                    _id("srg"), participant["experiment_id"], participant["id"],
                    "migration:legacy-synthetic", issued_at.isoformat(),
                    (issued_at + timedelta(seconds=ttl)).isoformat(),
                ),
            )


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


LEGACY_CREDENTIAL_KEY_ID = "legacy-event-session"


def _credential_secrets() -> dict[str, str]:
    try:
        raw = secret_env.text("EVENT_CREDENTIAL_SECRETS_JSON")
    except ValueError as exc:
        raise RuntimeError("EVENT_CREDENTIAL_SECRETS_JSON_B64 must be valid base64-encoded UTF-8") from exc
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("EVENT_CREDENTIAL_SECRETS_JSON must be valid JSON") from exc
        if (
            not isinstance(parsed, dict)
            or not parsed
            or any(
                not isinstance(key, str)
                or not key.strip()
                or not isinstance(secret, str)
                or len(secret) < 32
                for key, secret in parsed.items()
            )
        ):
            raise RuntimeError("credential secrets must map non-empty key ids to 32+ character secrets")
        return {key.strip(): secret for key, secret in parsed.items()}
    legacy = os.environ.get("EVENT_SESSION_SECRET", "")
    if os.environ.get("EVENT_ENV", "development").lower() != "production" and len(legacy) >= 32:
        return {LEGACY_CREDENTIAL_KEY_ID: legacy}
    return {}


def _active_credential_key_id(*, required: bool = True) -> str:
    secrets_by_id = _credential_secrets()
    configured = os.environ.get("EVENT_CREDENTIAL_ACTIVE_KEY_ID", "").strip()
    key_id = configured or (LEGACY_CREDENTIAL_KEY_ID if LEGACY_CREDENTIAL_KEY_ID in secrets_by_id else "")
    if required and (not key_id or key_id not in secrets_by_id):
        raise ExperimentError("an active versioned credential key is required")
    return key_id


def _credential_secret(key_id: str) -> str:
    secret = _credential_secrets().get(key_id)
    if not secret:
        raise CollectionDisabled(f"credential key is unavailable for experiment: {key_id}")
    return secret


def _secret_hash(namespace: str, value: str, *, key_id: str) -> str:
    secret = _credential_secret(key_id)
    return hmac.new(secret.encode(), f"{namespace}:{value}".encode(), hashlib.sha256).hexdigest()


def _participant_token(experiment_id: str, nonce: str, *, key_id: str) -> str:
    return hmac.new(
        bytes.fromhex(_secret_hash("participant-token-key", experiment_id, key_id=key_id)),
        nonce.encode(),
        hashlib.sha256,
    ).hexdigest().upper()


def _new_recovery_code() -> str:
    return "AIPOL-RC-" + secrets.token_urlsafe(32)


def _validate_recovery_code(value: str) -> str:
    code = value.strip()
    if not 40 <= len(code) <= 128 or not code.startswith("AIPOL-RC-"):
        raise ParticipantAuthenticationError("recovery code is invalid or already consumed")
    if any(character.isspace() for character in code):
        raise ParticipantAuthenticationError("recovery code is invalid or already consumed")
    return code


def _issue_recovery_code(
    connection: sqlite3.Connection,
    *,
    experiment_id: str,
    participant_id: str,
    credential_key_id: str,
) -> str:
    while True:
        raw_code = _new_recovery_code()
        code_hash = _secret_hash(
            f"participant-recovery:{experiment_id}", raw_code,
            key_id=credential_key_id,
        )
        try:
            connection.execute(
                "INSERT INTO aipol_participant_recovery_codes(id,experiment_id,participant_id,"
                "code_hash,created_at) VALUES(?,?,?,?,?)",
                (_id("prc"), experiment_id, participant_id, code_hash, time.time()),
            )
            return raw_code
        except sqlite3.IntegrityError:
            continue


def credential_readiness(*, fail: bool = False) -> dict:
    """Report whether every active experiment retains its versioned credential key."""
    available = set(_credential_secrets())
    active_key_id = _active_credential_key_id(required=False)
    with db._conn() as connection:
        required = {
            row["credential_key_id"]
            for row in connection.execute(
                "SELECT DISTINCT e.credential_key_id FROM aipol_experiments e "
                "WHERE e.freeze_manifest_anchor_id IS NOT NULL AND (e.registration_open=1 OR EXISTS ("
                "SELECT 1 FROM aipol_participants p WHERE p.experiment_id=e.id "
                "AND p.stage NOT IN ('complete','withdrawn')))"
            )
        }
    missing = sorted(required - available)
    ready = bool(active_key_id and active_key_id in available and not missing)
    result = {
        "ready": ready,
        "active_key_id": active_key_id or None,
        "required_key_ids": sorted(required),
        "missing_key_ids": missing,
    }
    if fail and missing:
        raise RuntimeError("active experiments reference unavailable credential keys: " + ", ".join(missing))
    return result


def admission_readiness() -> dict:
    """Expose legacy/missing seat inventories as collection-closed, never recover hashes."""
    with db._conn() as connection:
        rows = connection.execute(
            "SELECT e.id,e.capacity,e.admission_code_hash,COUNT(s.id) AS seat_count "
            "FROM aipol_experiments e LEFT JOIN aipol_admission_seats s "
            "ON s.experiment_id=e.id GROUP BY e.id,e.capacity,e.admission_code_hash"
        ).fetchall()
    legacy = sorted(
        row["id"] for row in rows if row["admission_code_hash"] and row["seat_count"] == 0
    )
    closed = sorted(
        row["id"] for row in rows if row["seat_count"] != row["capacity"]
    )
    return {
        "ready": not closed,
        "collection_closed_experiment_ids": closed,
        "legacy_admission_rotation_required_ids": legacy,
    }


def _new_admission_code() -> str:
    """Return a high-entropy one-time seat credential for secure distribution."""
    return _validate_admission_code(f"Aipol-7-{secrets.token_urlsafe(18)}")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _queue_experiment_audit(
    connection: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    experiment_id: str,
    payload: dict | None = None,
) -> None:
    """Persist an audit delivery record in the same transaction as the mutation."""
    if not actor.strip():
        raise ExperimentError("실험 변경 audit actor가 필요합니다")
    connection.execute(
        "INSERT INTO aipol_experiment_audit_outbox(event_id,actor,action,experiment_id,"
        "payload_json,created_at,delivered_at) VALUES(?,?,?,?,?,?,NULL)",
        (
            _id("xpa"), actor.strip(), action, experiment_id,
            _json(payload or {}), datetime.now(timezone.utc).isoformat(),
        ),
    )


def _row_experiment(row: sqlite3.Row) -> dict:
    result = dict(row)
    result.pop("admission_code_hash", None)
    result["registration_open"] = bool(result["registration_open"])
    result["e2_released"] = bool(result["e2_released"])
    result["measurement_spec"] = json.loads(result["measurement_spec"])
    result["policy_options"] = json.loads(result["policy_options"])
    result["procedure_config"] = json.loads(result.get("procedure_config") or "{}")
    result["freeze_manifest"] = (
        json.loads(result["freeze_manifest"]) if result.get("freeze_manifest") else None
    )
    return result


def _parse_spec(value: dict) -> MeasurementSpec:
    return MeasurementSpec(**value)


def _parse_options(values: list[dict]) -> tuple[PolicyOptionDefinition, ...]:
    try:
        return tuple(
            PolicyOptionDefinition(
                policy_option_id=value["policy_option_id"],
                label=value["label"],
                policy_version=value["policy_version"],
            )
            for value in values
        )
    except (KeyError, TypeError) as exc:
        raise ExperimentError("각 정책안에는 policy_option_id, label, policy_version이 필요합니다") from exc


def _parse_manifest(value: dict | None) -> FreezeManifest | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ExperimentError("동결표는 JSON 객체여야 합니다")
    expected_manifest_fields = {
        "manifest_id", "experiment_version", "option_set_version", "measurement_spec_hash",
        "status", "collection_enabled", "approvals",
    }
    server_manifest_fields = {
        "artifact_bindings", "frozen_at", "frozen_by", "settings_binding",
        "manifest_approval",
    }
    if not expected_manifest_fields <= set(value) or set(value) - expected_manifest_fields - server_manifest_fields:
        raise ExperimentError(
            "동결표 필드가 계약과 일치하지 않습니다: "
            f"missing={sorted(expected_manifest_fields - set(value))}, "
            f"unexpected={sorted(set(value) - expected_manifest_fields - server_manifest_fields)}"
        )
    approval_fields = {"category", "approval_id", "approved_by", "approved_at", "content_hash"}
    if not isinstance(value.get("approvals"), list) or any(
        not isinstance(approval, dict) or set(approval) != approval_fields
        for approval in value.get("approvals", [])
    ):
        raise ExperimentError("동결 승인 필드가 계약과 일치하지 않습니다")
    try:
        approvals = tuple(FreezeApproval(**approval) for approval in value.get("approvals", []))
    except (TypeError, KeyError) as exc:
        raise ExperimentError(
            "각 동결 승인에는 category, approval_id, approved_by, approved_at, content_hash가 필요합니다"
        ) from exc
    categories = [approval.category for approval in approvals]
    if len(categories) != len(set(categories)):
        raise ExperimentError("동결표 승인 category는 중복될 수 없습니다")
    unknown = set(categories) - REQUIRED_FREEZE_APPROVALS
    if unknown:
        raise ExperimentError("알 수 없는 동결 승인 category: " + ", ".join(sorted(unknown)))
    return FreezeManifest(
        manifest_id=value.get("manifest_id", ""),
        experiment_version=value.get("experiment_version", ""),
        option_set_version=value.get("option_set_version", ""),
        measurement_spec_hash=value.get("measurement_spec_hash", ""),
        status=value.get("status", "draft"),
        collection_enabled=value.get("collection_enabled", False),
        approvals=approvals,
    )


def _parse_artifact(
    row: sqlite3.Row | dict,
    connection: sqlite3.Connection | None = None,
) -> ExperimentArtifact:
    value = dict(row)
    try:
        content = json.loads(value["content"]) if isinstance(value["content"], str) else value["content"]
        digest = content_hash(content)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ImmutableRecordConflict("artifact payload is malformed") from exc
    if not hmac.compare_digest(digest, str(value["content_hash"])):
        raise ImmutableRecordConflict("artifact payload does not match its approval hash")
    if connection is not None:
        _validate_approval_event(
            connection,
            experiment_id=value["experiment_id"],
            object_type="artifact",
            object_id=value["kind"],
            digest=digest,
            approval_id=value["approval_id"],
            approved_by=value["approved_by"],
            approved_at=value["approved_at"],
        )
    approval = ArtifactApproval(
        value["approval_id"], value["approved_by"], value["approved_at"], digest
    )
    return ExperimentArtifact(
        value["artifact_id"],
        value["artifact_version"],
        ArtifactKind(value["kind"]),
        digest,
        approval,
        bool(value["fallback_used"]),
    )


def _parse_ai_candidate(
    row: sqlite3.Row | dict,
    connection: sqlite3.Connection | None = None,
) -> ExperimentArtifact:
    value = dict(row)
    _validate_ai_candidate_row(value, connection)
    return ExperimentArtifact(
        value["artifact_id"],
        value["artifact_version"],
        ArtifactKind.AI_OPINION,
        value["content_hash"],
        ArtifactApproval(
            value["approval_id"], value["approved_by"], value["approved_at"],
            value["content_hash"],
        ),
        value["candidate_role"] == "fallback",
    )


def create_experiment(
    *,
    title: str,
    experiment_version: str,
    session_id: str,
    consent_version: str,
    consent_text: str,
    question_id: str,
    question_text: str,
    option_set_version: str,
    policy_options: list[dict],
    capacity: int,
    created_by: str,
    procedure_version: str = "v1",
) -> dict:
    """승인 전 설정을 저장한다. 수집은 항상 닫힌 상태로 시작한다."""
    if not title.strip() or not question_text.strip() or not consent_version.strip() or not consent_text.strip() or not created_by.strip():
        raise ExperimentError("제목, 동의문 버전·본문, 주 선택 문항은 필수입니다")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 10_000:
        raise ExperimentError("정원은 1~10,000 정수여야 합니다")
    spec = MeasurementSpec(
        question_id=question_id,
        question_text_hash=content_hash(question_text.strip()),
        option_set_version=option_set_version,
    )
    options = _parse_options(policy_options)
    if procedure_version == "v1":
        procedure_config = LEGACY_PROCEDURE_CONFIG
    elif procedure_version == "v2":
        procedure_config = PROCEDURE_CONFIG
    else:
        raise ExperimentError("procedure_version은 v1 또는 v2여야 합니다")
    option_records = []
    for supplied, option in zip(policy_options, options, strict=True):
        if not isinstance(supplied, dict):
            raise ExperimentError("정책안 레지스트리는 객체 세 개여야 합니다")
        option_records.append({**supplied, **asdict(option)})
    # 생성 단계에서도 A/B/C 세트의 형식을 검증하되 실제 정책값은 호출자가 제공해야 한다.
    PensionExperimentSession(
        experiment_version=experiment_version,
        session_id=session_id,
        measurement_spec=spec,
        policy_options=options,
        procedure_config=procedure_config,
    )
    experiment_id = _id("xp")
    credential_key_id = _active_credential_key_id()
    admission_credentials: list[str] = []
    while len(admission_credentials) < capacity:
        candidate = _new_admission_code()
        if candidate not in admission_credentials:
            admission_credentials.append(candidate)
    with db._conn() as connection:
        connection.execute(
            "INSERT INTO aipol_experiments(id,title,experiment_version,session_id,measurement_spec,"
            "question_text,policy_options,freeze_manifest,consent_version,consent_text,"
            "admission_code_hash,capacity,created_by,credential_key_id,procedure_config,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                experiment_id,
                title.strip(),
                experiment_version,
                session_id,
                _json(asdict(spec)),
                question_text.strip(),
                _json(option_records),
                None,
                consent_version,
                consent_text.strip(),
                None,
                capacity,
                created_by.strip(),
                credential_key_id,
                _json(procedure_config),
                time.time(),
            ),
        )
        connection.executemany(
            "INSERT INTO aipol_admission_seats(id,experiment_id,code_hash,created_at) "
            "VALUES(?,?,?,?)",
            [
                (
                    _id("seat"),
                    experiment_id,
                    _secret_hash(
                        f"admission-seat:{experiment_id}", credential,
                        key_id=credential_key_id,
                    ),
                    time.time(),
                )
                for credential in admission_credentials
            ],
        )
        _queue_experiment_audit(
            connection, actor=created_by, action="experiment.created",
            experiment_id=experiment_id,
            payload={"experiment_version": experiment_version, "session_id": session_id},
        )
    result = get_experiment(experiment_id)
    # Raw credentials are returned only on creation. All persistent/read models
    # retain HMACs, so this response is the operator's secure distribution copy.
    result["admission_credentials"] = admission_credentials
    return result


def get_experiment(experiment_id: str, connection=None) -> dict:
    owns = connection is None
    connection = connection or db._conn()
    try:
        row = connection.execute(
            "SELECT * FROM aipol_experiments WHERE id=?", (experiment_id,)
        ).fetchone()
        if not row:
            raise KeyError(experiment_id)
        result = _row_experiment(row)
        if result.get("freeze_manifest_anchor_id"):
            if result.get("freeze_manifest") is not None:
                raise ImmutableRecordConflict(
                    "anchored experiment must not retain a mutable freeze manifest copy"
                )
            result["freeze_manifest"] = _validated_freeze_manifest_anchor(connection, result)
        elif result.get("freeze_manifest") is not None:
            raise ImmutableRecordConflict("freeze manifest is not append-only anchored")
        seat_count = connection.execute(
            "SELECT COUNT(*) FROM aipol_admission_seats WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()[0]
        legacy_rotation_required = bool(row["admission_code_hash"] and seat_count == 0)
        inventory_ready = seat_count == result["capacity"] and seat_count > 0
        result["admission_state"] = (
            "legacy_rotation_required"
            if legacy_rotation_required
            else "ready" if inventory_ready else "inventory_invalid"
        )
        result["admission_seat_count"] = seat_count
        if not inventory_ready:
            result["registration_open"] = False
        manifest = _parse_manifest(result["freeze_manifest"])
        spec = _parse_spec(result["measurement_spec"])
        result["collection_enabled"] = bool(
            inventory_ready
            and
            manifest
            and manifest.permits_real_collection(
                experiment_version=result["experiment_version"],
                option_set_version=spec.option_set_version,
                measurement_spec_hash=spec.spec_hash,
            )
        )
        result["measurement_spec_hash"] = spec.spec_hash
        if result["freeze_manifest"]:
            _validate_frozen_settings(connection, result)
        return result
    finally:
        if owns:
            connection.close()


def list_experiments() -> list[dict]:
    with db._conn() as connection:
        ids = [row["id"] for row in connection.execute(
            "SELECT id FROM aipol_experiments ORDER BY created_at DESC"
        )]
    return [get_experiment(experiment_id) for experiment_id in ids]


def legacy_rotation_confirmation(experiment_id: str, new_capacity: int) -> str:
    return f"ROTATE {experiment_id} TO {new_capacity}"


def rotate_legacy_admission_seats(
    experiment_id: str,
    *,
    actor: str,
    reason: str,
    new_capacity: int,
    confirmation: str,
) -> dict:
    """Issue a fresh one-time seat inventory for a legacy hash-only experiment."""
    if not actor.strip() or not 8 <= len(reason.strip()) <= 500:
        raise ExperimentError("actor and an 8 to 500 character rotation reason are required")
    if isinstance(new_capacity, bool) or not isinstance(new_capacity, int) or new_capacity < 1:
        raise ExperimentError("new_capacity must be a positive integer")
    if not hmac.compare_digest(
        confirmation.strip(), legacy_rotation_confirmation(experiment_id, new_capacity)
    ):
        raise ExperimentError("typed legacy rotation confirmation does not match")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM aipol_experiments WHERE id=?", (experiment_id,)
        ).fetchone()
        if not row:
            raise KeyError(experiment_id)
        seat_count = connection.execute(
            "SELECT COUNT(*) FROM aipol_admission_seats WHERE experiment_id=?",
            (experiment_id,),
        ).fetchone()[0]
        if not row["admission_code_hash"] or seat_count != 0:
            raise ImmutableRecordConflict(
                "fresh seat issue is allowed only for a legacy hash-only experiment"
            )
        old_capacity = int(row["capacity"])
        if row["freeze_manifest_anchor_id"] and new_capacity != old_capacity:
            raise ImmutableRecordConflict(
                "new_capacity cannot change after experiment settings are frozen"
            )
        participants = connection.execute(
            "SELECT id FROM aipol_participants WHERE experiment_id=? "
            "AND participant_type='real' ORDER BY created_at,id",
            (experiment_id,),
        ).fetchall()
        participant_count = len(participants)
        if new_capacity < participant_count:
            raise ExperimentError(
                "new_capacity cannot be lower than the existing real participant count"
            )
        credential_key_id = str(row["credential_key_id"])
        _credential_secret(credential_key_id)
        issued_count = new_capacity - participant_count
        raw_inventory: list[str] = []
        seen: set[str] = set()
        while len(raw_inventory) < new_capacity:
            candidate = _new_admission_code()
            if candidate not in seen:
                seen.add(candidate)
                raw_inventory.append(candidate)
        reserved_credentials = raw_inventory[:participant_count]
        credentials = raw_inventory[participant_count:]
        now = time.time()
        seat_rows = [
            (
                _id("seat"), experiment_id,
                _secret_hash(
                    f"admission-seat:{experiment_id}", credential,
                    key_id=credential_key_id,
                ),
                now,
            )
            for credential in raw_inventory
        ]
        connection.executemany(
            "INSERT INTO aipol_admission_seats(id,experiment_id,code_hash,created_at) "
            "VALUES(?,?,?,?)",
            seat_rows,
        )
        if reserved_credentials:
            connection.executemany(
                "INSERT INTO aipol_admission_claims(id,experiment_id,seat_id,participant_id,claimed_at) "
                "VALUES(?,?,?,?,?)",
                [
                    (
                        _id("claim"), experiment_id, seat_rows[index][0], participant["id"],
                        datetime.now(timezone.utc).isoformat(),
                    )
                    for index, participant in enumerate(participants)
                ],
            )
        connection.execute(
            "UPDATE aipol_experiments SET admission_code_hash=NULL,capacity=? WHERE id=?",
            (new_capacity, experiment_id),
        )
        _queue_experiment_audit(
            connection,
            actor=actor,
            action="experiment.admission_seats.rotated",
            experiment_id=experiment_id,
            payload={
                "old_capacity": old_capacity,
                "new_capacity": new_capacity,
                "existing_participant_count": participant_count,
                "issued_count": issued_count,
                "reason": reason.strip(),
            },
        )
    result = get_experiment(experiment_id)
    result["admission_credentials"] = credentials
    return result


def _bound_settings_hash(experiment: dict, category: str) -> str:
    if category == "policy_options":
        value = {"policy_options": experiment["policy_options"]}
    elif category == "measurement":
        value = {
            "measurement_spec": experiment["measurement_spec"],
            "question_text": experiment["question_text"],
        }
    elif category in {"privacy", "research_ethics", "procedure"}:
        value = {
            "category": category,
            "experiment_version": experiment["experiment_version"],
            "session_id": experiment["session_id"],
            "consent_version": experiment["consent_version"],
            "consent_text_hash": content_hash(experiment["consent_text"]),
            "procedure_config": experiment["procedure_config"],
        }
    else:
        value = {
            "category": category,
            "experiment_version": experiment["experiment_version"],
            "session_id": experiment["session_id"],
        }
    return content_hash(value)


def _live_settings_envelope(experiment: dict) -> dict:
    """Canonical live experiment settings that no frozen read may diverge from."""
    measurement_spec = experiment["measurement_spec"]
    policy_options = experiment["policy_options"]
    question_text = experiment["question_text"]
    consent_text = experiment["consent_text"]
    return {
        "experiment_id": experiment["id"],
        "title": experiment["title"],
        "experiment_version": experiment["experiment_version"],
        "session_id": experiment["session_id"],
        "measurement_spec": measurement_spec,
        "measurement_spec_hash": _parse_spec(measurement_spec).spec_hash,
        "question_id": measurement_spec["question_id"],
        "question_text": question_text,
        "question_text_hash": content_hash(question_text),
        "option_set_version": measurement_spec["option_set_version"],
        "policy_options": policy_options,
        "policy_options_hash": content_hash(policy_options),
        "consent_version": experiment["consent_version"],
        "consent_text": consent_text,
        "consent_text_hash": content_hash(consent_text),
        "procedure_config": experiment["procedure_config"],
        "capacity": experiment["capacity"],
        "credential_key_id": experiment["credential_key_id"],
    }


def _validated_freeze_manifest_anchor(
    connection: sqlite3.Connection, experiment: dict
) -> dict:
    anchor_id = str(experiment.get("freeze_manifest_anchor_id") or "")
    rows = connection.execute(
        "SELECT * FROM aipol_freeze_manifest_anchors WHERE id=? AND experiment_id=?",
        (anchor_id, experiment["id"]),
    ).fetchall()
    if len(rows) != 1:
        raise ImmutableRecordConflict("freeze manifest must have exactly one independent anchor")
    anchor = dict(rows[0])
    try:
        envelope = json.loads(anchor["manifest_envelope"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ImmutableRecordConflict("freeze manifest anchor is malformed") from exc
    if not isinstance(envelope, dict):
        raise ImmutableRecordConflict("freeze manifest anchor must contain an object")
    digest = content_hash(envelope)
    approval = envelope.get("manifest_approval")
    if not isinstance(approval, dict) or set(approval) != {
        "approval_id", "approved_by", "approved_at",
    }:
        raise ImmutableRecordConflict("freeze manifest approval binding is malformed")
    expected = (
        digest, anchor["approval_id"], anchor["approved_by"], anchor["approved_at"],
    )
    actual = (
        str(anchor["manifest_hash"]), approval["approval_id"],
        approval["approved_by"], approval["approved_at"],
    )
    if any(
        not hmac.compare_digest(str(left), str(right))
        for left, right in zip(actual, expected, strict=True)
    ):
        raise ImmutableRecordConflict("freeze manifest does not match its immutable anchor")
    if (
        not hmac.compare_digest(str(envelope.get("frozen_by") or ""), str(anchor["approved_by"]))
        or not hmac.compare_digest(str(envelope.get("frozen_at") or ""), str(anchor["approved_at"]))
    ):
        raise ImmutableRecordConflict("freeze manifest signer metadata does not match its anchor")
    _validate_approval_event(
        connection,
        experiment_id=experiment["id"],
        object_type="freeze_manifest",
        object_id=anchor_id,
        digest=digest,
        approval_id=anchor["approval_id"],
        approved_by=anchor["approved_by"],
        approved_at=anchor["approved_at"],
    )
    _parse_manifest(envelope)
    return envelope


def _validate_frozen_settings(connection: sqlite3.Connection, experiment: dict) -> None:
    manifest = experiment.get("freeze_manifest")
    binding = manifest.get("settings_binding") if isinstance(manifest, dict) else None
    if not isinstance(binding, dict) or set(binding) != {
        "anchor_id", "settings_hash", "approval_id", "approved_by", "approved_at",
    }:
        raise ImmutableRecordConflict("frozen settings binding is missing or malformed")
    rows = connection.execute(
        "SELECT * FROM aipol_freeze_settings_anchors WHERE experiment_id=?",
        (experiment["id"],),
    ).fetchall()
    if len(rows) != 1:
        raise ImmutableRecordConflict("frozen settings must have exactly one independent anchor")
    anchor = dict(rows[0])
    try:
        anchored_envelope = json.loads(anchor["settings_envelope"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ImmutableRecordConflict("frozen settings anchor is malformed") from exc
    anchored_hash = content_hash(anchored_envelope)
    live_hash = content_hash(_live_settings_envelope(experiment))
    expected = (
        anchor["id"], anchored_hash, anchor["approval_id"],
        anchor["approved_by"], anchor["approved_at"],
    )
    actual = tuple(binding[key] for key in (
        "anchor_id", "settings_hash", "approval_id", "approved_by", "approved_at",
    ))
    if (
        not hmac.compare_digest(str(anchor["settings_hash"]), anchored_hash)
        or not hmac.compare_digest(live_hash, anchored_hash)
        or any(
            not hmac.compare_digest(str(left), str(right))
            for left, right in zip(actual, expected, strict=True)
        )
    ):
        raise ImmutableRecordConflict("live experiment settings do not match the frozen anchor")
    _validate_approval_event(
        connection,
        experiment_id=experiment["id"],
        object_type="freeze_settings",
        object_id="live_settings",
        digest=anchored_hash,
        approval_id=anchor["approval_id"],
        approved_by=anchor["approved_by"],
        approved_at=anchor["approved_at"],
    )
    if manifest.get("collection_enabled"):
        documents = connection.execute(
            "SELECT * FROM aipol_canonical_documents WHERE experiment_id=?",
            (experiment["id"],),
        ).fetchall()
        if len(documents) != len(REQUIRED_FREEZE_APPROVALS):
            raise ImmutableRecordConflict("frozen canonical document set is incomplete")
        seen = set()
        for row in documents:
            document = _validate_canonical_row(connection, row)
            seen.add(document["category"])
            if not hmac.compare_digest(
                document["bound_settings_hash"],
                _bound_settings_hash(experiment, document["category"]),
            ):
                raise ImmutableRecordConflict(
                    f"{document['category']} canonical settings binding no longer matches"
                )
            _validate_canonical_freeze_binding(experiment, document)
        if seen != REQUIRED_FREEZE_APPROVALS:
            raise ImmutableRecordConflict("frozen canonical document categories do not match")


def _server_approval(
    connection: sqlite3.Connection,
    experiment: dict,
    *,
    object_type: str,
    object_id: str,
    digest: str,
    approval_id: str,
    approved_by: str,
    approved_at: str | None = None,
) -> str:
    if not approval_id.strip() or not approved_by.strip():
        raise ExperimentError("approval_id와 승인 계정은 필수입니다")
    editor_by = str(experiment.get("created_by") or "")
    if not editor_by or editor_by == "legacy-unknown":
        raise CollectionDisabled("서명된 편집자 계정이 없는 기존 실험은 승인할 수 없습니다")
    if editor_by == approved_by:
        raise ExperimentError("편집자와 승인자는 서로 다른 서명 계정이어야 합니다")
    approved_at = approved_at or datetime.now(timezone.utc).isoformat()
    connection.execute(
        "INSERT INTO aipol_approval_events(id,experiment_id,object_type,object_id,content_hash,"
        "approval_id,editor_by,approver_by,approved_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            _id("av"), experiment["id"], object_type, object_id, digest, approval_id,
            editor_by, approved_by, approved_at, time.time(),
        ),
    )
    return approved_at


def _validate_approval_event(
    connection: sqlite3.Connection,
    *,
    experiment_id: str,
    object_type: str,
    object_id: str,
    digest: str,
    approval_id: str,
    approved_by: str,
    approved_at: str,
) -> None:
    """Anchor a materialized approved row to its independent append-only approval event."""
    rows = connection.execute(
        "SELECT content_hash,approval_id,editor_by,approver_by,approved_at "
        "FROM aipol_approval_events WHERE experiment_id=? AND object_type=? AND object_id=?",
        (experiment_id, object_type, object_id),
    ).fetchall()
    if len(rows) != 1:
        raise ImmutableRecordConflict("approved object must have exactly one approval event")
    event = rows[0]
    experiment = connection.execute(
        "SELECT created_by FROM aipol_experiments WHERE id=?", (experiment_id,)
    ).fetchone()
    expected = (
        digest,
        approval_id,
        experiment["created_by"] if experiment else "",
        approved_by,
        approved_at,
    )
    actual = (
        event["content_hash"], event["approval_id"], event["editor_by"],
        event["approver_by"], event["approved_at"],
    )
    if len(actual) != len(expected) or any(
        not hmac.compare_digest(str(left), str(right))
        for left, right in zip(actual, expected, strict=True)
    ):
        raise ImmutableRecordConflict("approved object does not match its approval event")


def _validate_canonical_row(connection: sqlite3.Connection, row: sqlite3.Row | dict) -> dict:
    value = dict(row)
    try:
        evidence = json.loads(value["evidence"]) if isinstance(value["evidence"], str) else value["evidence"]
        envelope = {
            "category": value["category"],
            "document_id": value["document_id"],
            "document_version": value["document_version"],
            "body": value["body"],
            "bound_settings_hash": value["bound_settings_hash"],
            "evidence": evidence,
        }
        digest = content_hash(envelope)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ImmutableRecordConflict("canonical document payload is malformed") from exc
    if not hmac.compare_digest(digest, str(value["content_hash"])):
        raise ImmutableRecordConflict("canonical document payload does not match its approval hash")
    if value["category"] == "calculation":
        _validate_calculation_evidence(evidence)
    _validate_approval_event(
        connection,
        experiment_id=value["experiment_id"],
        object_type="canonical_document",
        object_id=value["category"],
        digest=digest,
        approval_id=value["approval_id"],
        approved_by=value["approved_by"],
        approved_at=value["approved_at"],
    )
    return {**value, "evidence": evidence, "content_hash": digest}


def _freeze_artifact_digest(experiment: dict, binding_key: str) -> str:
    manifest = experiment.get("freeze_manifest")
    bindings = manifest.get("artifact_bindings") if isinstance(manifest, dict) else None
    digest = bindings.get(binding_key) if isinstance(bindings, dict) else None
    if not isinstance(digest, str) or len(digest) != 64:
        raise CollectionDisabled(f"freeze artifact binding is missing: {binding_key}")
    return digest


def _require_freeze_artifact_digest(experiment: dict, binding_key: str, digest: str) -> None:
    if not hmac.compare_digest(_freeze_artifact_digest(experiment, binding_key), digest):
        raise ImmutableRecordConflict(f"artifact payload does not match freeze binding: {binding_key}")


def _validate_canonical_freeze_binding(experiment: dict, document: dict) -> None:
    manifest = experiment.get("freeze_manifest")
    if not manifest:
        return
    approvals = manifest.get("approvals") if isinstance(manifest, dict) else None
    matches = [
        item for item in (approvals or [])
        if isinstance(item, dict) and item.get("category") == document["category"]
    ]
    if len(matches) != 1:
        raise ImmutableRecordConflict("canonical document does not match freeze approval")
    binding = matches[0]
    for key in ("content_hash", "approval_id", "approved_by", "approved_at"):
        if not hmac.compare_digest(str(binding.get(key) or ""), str(document[key])):
            raise ImmutableRecordConflict(
                f"canonical document {key} does not match freeze approval"
            )


def _validate_selected_ai_binding(
    connection: sqlite3.Connection,
    experiment: dict,
    candidate: dict,
    approval_digest: str,
) -> None:
    selection = connection.execute(
        "SELECT * FROM aipol_e2_selections WHERE experiment_id=?", (experiment["id"],)
    ).fetchone()
    if not selection:
        raise ImmutableRecordConflict("selected AI candidate has no append-only release binding")
    expected = (
        candidate["id"], candidate["candidate_role"], candidate["content_hash"], approval_digest,
    )
    actual = (
        selection["candidate_id"], selection["candidate_role"],
        selection["candidate_content_hash"], selection["candidate_approval_hash"],
    )
    if any(
        not hmac.compare_digest(str(left), str(right))
        for left, right in zip(actual, expected, strict=True)
    ):
        raise ImmutableRecordConflict("selected AI candidate does not match its release binding")


def _receipt_contract_hash(contract: dict) -> str:
    required = (
        "contract_id", "version", "issuer", "audience", "public_key_id",
        "receipt_format", "signature_algorithm",
    )
    if not isinstance(contract, dict) or contract.get("mode") != "signed_one_time_completion":
        raise ExperimentError("계산기 receipt 계약은 signed_one_time_completion 모드여야 합니다")
    if any(not str(contract.get(key) or "").strip() for key in required):
        raise ExperimentError("계산기 receipt 계약의 식별자·버전·발급자·대상·키 ID가 필요합니다")
    if contract["receipt_format"] != "flattened_jws_json" or contract["signature_algorithm"] != "EdDSA":
        raise ExperimentError("계산기 receipt 계약은 flattened JWS JSON과 EdDSA를 사용해야 합니다")
    return content_hash(contract)


CALCULATOR_INTEGRATION_VERSION = "aipol-calculator-return-v2"
CALCULATOR_CONTEXT_MAX_BYTES = 2048
CALCULATOR_CSP_NONE = "default-src 'self'; script-src 'self'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
CALCULATOR_CSP_SELF = "default-src 'self'; script-src 'self'; connect-src 'self'; form-action 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
CALCULATOR_CONTEXT_FIELDS = (
    "experiment_id", "experiment_version", "session_id", "participant_pseudonym",
    "artifact_id", "artifact_hash", "contract_hash",
)


def _canonical_https_origin(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ExperimentError("calculator origin must be an exact HTTPS origin")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExperimentError("calculator origin port is invalid") from exc
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    suffix = "" if port in (None, 443) else f":{port}"
    return f"https://{host}{suffix}"


def _canonical_calculator_csp(value: str) -> str:
    """Accept only a reviewed, byte-exact calculator response CSP."""
    if value not in {CALCULATOR_CSP_NONE, CALCULATOR_CSP_SELF}:
        raise ExperimentError("calculator CSP header is not an approved canonical policy")
    directives = {}
    for part in value.split("; "):
        name, *tokens = part.split(" ")
        if name in directives:
            raise ExperimentError("calculator CSP contains a duplicate directive")
        directives[name] = tokens
    if directives.get("default-src") != ["'self'"] or directives.get("script-src") != ["'self'"]:
        raise ExperimentError("calculator scripts must be same-origin external files only")
    if directives.get("connect-src") not in (["'none'"], ["'self'"]):
        raise ExperimentError("calculator connections must be disabled or exact self")
    for name in ("form-action", "object-src", "base-uri", "frame-ancestors"):
        if directives.get(name) != ["'none'"]:
            raise ExperimentError(f"calculator {name} must be 'none'")
    return value


def _clean_calculator_launch_url(value: str, approved_origin: str) -> str:
    """Validate a canonical, credential-free URL on the exact approved origin."""
    if not isinstance(value, str) or not value or value != value.strip() or "\\" in value:
        raise ExperimentError("calculator launch URL is not canonical")
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ExperimentError("calculator launch URL port is invalid") from exc
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
        or parsed.password is not None or parsed.params or parsed.query or parsed.fragment
        or any(ord(character) < 32 for character in value)
    ):
        raise ExperimentError("calculator launch URL must not contain credentials, query, or fragment")
    origin = _canonical_https_origin(f"https://{parsed.netloc}")
    if origin != approved_origin:
        raise ExperimentError("calculator launch URL origin does not match the approved origin")
    if port == 443 and parsed.netloc.endswith(":443"):
        raise ExperimentError("calculator launch URL must use the canonical default port")
    decoded_path = unquote(parsed.path).casefold()
    if re.search(r"(?:^|[^a-z0-9])(token|access[_-]?token|api[_-]?key|secret|password|credential|signature|sas)(?:$|[^a-z0-9])", decoded_path):
        raise ExperimentError("calculator launch URL path resembles embedded credentials")
    canonical = f"{origin}{parsed.path}"
    if value != canonical:
        raise ExperimentError("calculator launch URL is not canonical")
    return value


def _calculator_context(value: dict) -> dict:
    if set(value) != set(CALCULATOR_CONTEXT_FIELDS):
        raise ExperimentError("calculator receipt context fields do not match the contract")
    if any(not isinstance(value[field], str) or not value[field].strip() for field in CALCULATOR_CONTEXT_FIELDS):
        raise ExperimentError("calculator receipt context values must be non-empty strings")
    serialized = _json(value).encode("utf-8")
    if len(serialized) > CALCULATOR_CONTEXT_MAX_BYTES:
        raise ExperimentError("calculator receipt context is too large")
    forbidden = ("token", "admission", "income", "salary", "email", "phone", "name", "resident")
    if any(any(word in field.lower() for word in forbidden) for field in value):
        raise ExperimentError("calculator receipt context contains a sensitive field")
    return value


def _validate_calculation_evidence(evidence: dict) -> None:
    required_text = (
        "source_repository", "source_commit", "source_tree_hash", "build_hash",
        "license_spdx", "license_evidence_hash", "approved_origin", "csp",
        "network_test_hash", "policy_values_status", "integration_status",
        "integration_contract_version", "integration_test_hash",
    )
    if not isinstance(evidence, dict) or any(not str(evidence.get(key) or "").strip() for key in required_text):
        raise ExperimentError("계산 정본에는 소스·빌드·라이선스·origin·CSP·네트워크 증거가 필요합니다")
    if len(evidence["source_commit"]) != 40 or any(ch not in "0123456789abcdef" for ch in evidence["source_commit"].lower()):
        raise ExperimentError("계산기 source_commit은 40자리 Git SHA여야 합니다")
    for key in (
        "source_tree_hash", "build_hash", "license_evidence_hash", "network_test_hash",
        "integration_test_hash",
    ):
        if len(evidence[key]) != 64 or any(ch not in "0123456789abcdef" for ch in evidence[key].lower()):
            raise ExperimentError(f"계산기 {key}는 SHA-256이어야 합니다")
    if evidence["approved_origin"] != _canonical_https_origin(evidence["approved_origin"]):
        raise ExperimentError("계산기 approved_origin은 정규화된 exact HTTPS origin이어야 합니다")
    if evidence.get("raw_input_egress") is not False:
        raise ExperimentError("계산기 raw_input_egress=false 네트워크 검증이 필요합니다")
    if _canonical_calculator_csp(evidence["csp"]) != evidence["csp"]:
        raise ExperimentError("계산기 CSP에는 default-src 지시자가 필요합니다")
    if evidence["license_spdx"].upper() in ("NOASSERTION", "NONE", "UNKNOWN"):
        raise ExperimentError("계산기 소스 라이선스가 확정되지 않았습니다")
    if evidence["policy_values_status"] != "approved":
        raise ExperimentError("계산기 정책값은 승인된 상태여야 합니다")
    if evidence["integration_status"] != "approved":
        raise ExperimentError("계산기 통합은 승인된 상태여야 합니다")
    if evidence["integration_contract_version"] != CALCULATOR_INTEGRATION_VERSION:
        raise ExperimentError("계산기가 승인된 fragment/postMessage 계약을 구현해야 합니다")
    contract_hash = _receipt_contract_hash(evidence.get("receipt_contract"))
    if evidence.get("receipt_contract_hash") != contract_hash:
        raise ExperimentError("계산기 receipt 계약 해시가 일치하지 않습니다")


def register_canonical_document(
    experiment_id: str,
    *,
    category: str,
    document_id: str,
    document_version: str,
    body: str,
    evidence: dict,
    declared_content_hash: str,
    approval_id: str,
    approved_by: str,
    registered_by: str,
) -> dict:
    if category not in REQUIRED_FREEZE_APPROVALS:
        raise ExperimentError("알 수 없는 정본 category입니다")
    if not all(value.strip() for value in (document_id, document_version, body, approval_id, approved_by, registered_by)):
        raise ExperimentError("정본 문서·승인·등록자 필드는 필수입니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["freeze_manifest"] or connection.execute(
            "SELECT 1 FROM aipol_participants WHERE experiment_id=? LIMIT 1", (experiment_id,)
        ).fetchone():
            raise ExperimentError("참가자 등록 뒤에는 정본 문서를 추가할 수 없습니다")
        if approved_by != registered_by:
            raise ExperimentError("approved_by는 서명된 승인자 계정과 일치해야 합니다")
        if category == "calculation":
            _validate_calculation_evidence(evidence)
        elif not isinstance(evidence, dict):
            raise ExperimentError("정본 evidence는 JSON 객체여야 합니다")
        envelope = {
            "category": category,
            "document_id": document_id,
            "document_version": document_version,
            "body": body,
            "bound_settings_hash": _bound_settings_hash(experiment, category),
            "evidence": evidence,
        }
        digest = content_hash(envelope)
        if digest != declared_content_hash:
            raise ExperimentError("서버가 계산한 정본 해시와 declared_content_hash가 다릅니다")
        draft_row = connection.execute(
            "SELECT * FROM aipol_canonical_drafts WHERE experiment_id=? AND category=?",
            (experiment_id, category),
        ).fetchone()
        if not draft_row:
            raise ExperimentError("생성 편집자가 등록한 정본 초안이 필요합니다")
        draft = dict(draft_row)
        draft_evidence = json.loads(draft["evidence"])
        draft_envelope = {
            "category": draft["category"],
            "document_id": draft["document_id"],
            "document_version": draft["document_version"],
            "body": draft["body"],
            "bound_settings_hash": draft["bound_settings_hash"],
            "evidence": draft_evidence,
        }
        if (
            draft["editor_by"] != experiment["created_by"]
            or content_hash(draft_envelope) != draft["content_hash"]
            or draft_envelope != envelope
            or draft["content_hash"] != digest
        ):
            raise ExperimentError("승인 요청이 편집자 등록 초안과 일치하지 않습니다")
        approved_at = _server_approval(
            connection, experiment, object_type="canonical_document",
            object_id=category, digest=digest, approval_id=approval_id,
            approved_by=approved_by,
        )
        FreezeApproval(category, approved_by, approved_at, digest, approval_id).validate()
        try:
            connection.execute(
                "INSERT INTO aipol_canonical_documents(id,experiment_id,category,document_id,"
                "document_version,body,bound_settings_hash,evidence,content_hash,approval_id,"
                "approved_by,approved_at,registered_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _id("cd"), experiment_id, category, document_id, document_version, body,
                    envelope["bound_settings_hash"], _json(evidence), digest, approval_id,
                    approved_by, approved_at, registered_by, time.time(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ImmutableRecordConflict("category별 정본 문서는 한 번만 등록할 수 있습니다") from exc
        _queue_experiment_audit(
            connection, actor=registered_by, action="experiment.canonical.approved",
            experiment_id=experiment_id,
            payload={"category": category, "content_hash": digest, "approval_id": approval_id},
        )
    return {**envelope, "content_hash": digest, "approval_id": approval_id,
            "approved_by": approved_by, "approved_at": approved_at, "registered_by": registered_by}


def register_canonical_draft(
    experiment_id: str,
    *,
    category: str,
    document_id: str,
    document_version: str,
    body: str,
    evidence: dict,
    declared_content_hash: str,
    editor_by: str,
) -> dict:
    if category not in REQUIRED_FREEZE_APPROVALS:
        raise ExperimentError("알 수 없는 정본 category입니다")
    if not all(value.strip() for value in (
        document_id, document_version, body, declared_content_hash, editor_by,
    )):
        raise ExperimentError("정본 초안 문서·해시·편집자 필드는 필수입니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["created_by"] != editor_by:
            raise ExperimentError("실험 생성 편집자만 정본 초안을 등록할 수 있습니다")
        if experiment["freeze_manifest"] or connection.execute(
            "SELECT 1 FROM aipol_participants WHERE experiment_id=? LIMIT 1", (experiment_id,)
        ).fetchone():
            raise ExperimentError("참가자 등록 뒤에는 정본 초안을 추가할 수 없습니다")
        if category == "calculation":
            _validate_calculation_evidence(evidence)
        elif not isinstance(evidence, dict):
            raise ExperimentError("정본 evidence는 JSON 객체여야 합니다")
        envelope = {
            "category": category,
            "document_id": document_id,
            "document_version": document_version,
            "body": body,
            "bound_settings_hash": _bound_settings_hash(experiment, category),
            "evidence": evidence,
        }
        digest = content_hash(envelope)
        if digest != declared_content_hash:
            raise ExperimentError("서버가 계산한 초안 해시와 declared_content_hash가 다릅니다")
        registered_at = datetime.now(timezone.utc).isoformat()
        try:
            connection.execute(
                "INSERT INTO aipol_canonical_drafts(id,experiment_id,category,document_id,"
                "document_version,body,bound_settings_hash,evidence,content_hash,editor_by,"
                "registered_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _id("cdraft"), experiment_id, category, document_id, document_version,
                    body, envelope["bound_settings_hash"], _json(evidence), digest, editor_by,
                    registered_at, time.time(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ImmutableRecordConflict("category별 편집자 초안은 한 번만 등록할 수 있습니다") from exc
        _queue_experiment_audit(
            connection, actor=editor_by, action="experiment.canonical.drafted",
            experiment_id=experiment_id,
            payload={"category": category, "content_hash": digest},
        )
    return {**envelope, "content_hash": digest, "editor_by": editor_by,
            "registered_at": registered_at}


def list_canonical_drafts(experiment_id: str) -> list[dict]:
    with db._conn() as connection:
        get_experiment(experiment_id, connection)
        rows = connection.execute(
            "SELECT category,document_id,document_version,body,bound_settings_hash,evidence,"
            "content_hash,editor_by,registered_at FROM aipol_canonical_drafts "
            "WHERE experiment_id=? ORDER BY category",
            (experiment_id,),
        ).fetchall()
    return [
        {**dict(row), "evidence": json.loads(row["evidence"])}
        for row in rows
    ]


def canonical_document_hash_preview(
    experiment_id: str,
    *,
    category: str,
    document_id: str,
    document_version: str,
    body: str,
    evidence: dict,
) -> dict:
    experiment = get_experiment(experiment_id)
    if category not in REQUIRED_FREEZE_APPROVALS:
        raise ExperimentError("알 수 없는 정본 category입니다")
    if category == "calculation":
        _validate_calculation_evidence(evidence)
    envelope = {
        "category": category,
        "document_id": document_id,
        "document_version": document_version,
        "body": body,
        "bound_settings_hash": _bound_settings_hash(experiment, category),
        "evidence": evidence,
    }
    return {**envelope, "content_hash": content_hash(envelope)}


def list_canonical_documents(experiment_id: str) -> list[dict]:
    with db._conn() as connection:
        experiment = get_experiment(experiment_id, connection)
        rows = connection.execute(
            "SELECT * FROM aipol_canonical_documents "
            "WHERE experiment_id=? ORDER BY category",
            (experiment_id,),
        ).fetchall()
        validated = []
        for row in rows:
            document = _validate_canonical_row(connection, row)
            _validate_canonical_freeze_binding(experiment, document)
            validated.append({
                key: document[key] for key in (
                    "category", "document_id", "document_version", "bound_settings_hash",
                    "content_hash", "approval_id", "approved_by", "approved_at", "registered_by",
                )
            })
    return validated


def set_freeze_manifest(experiment_id: str, manifest_value: dict, *, approved_by: str) -> dict:
    """동결표가 설정과 정확히 일치할 때만 실제 참가자 수집을 연다."""
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["freeze_manifest"]:
            raise ImmutableRecordConflict("동결 manifest는 교체할 수 없습니다")
        if connection.execute(
            "SELECT 1 FROM aipol_participants WHERE experiment_id=? LIMIT 1", (experiment_id,)
        ).fetchone():
            raise ExperimentError("참가자가 등록된 뒤에는 동결표를 바꿀 수 없습니다")
        manifest = _parse_manifest(manifest_value)
        if manifest is None:
            raise ExperimentError("동결표가 필요합니다")
        spec = _parse_spec(experiment["measurement_spec"])
        if manifest.collection_enabled and not manifest.permits_real_collection(
            experiment_version=experiment["experiment_version"],
            option_set_version=spec.option_set_version,
            measurement_spec_hash=spec.spec_hash,
        ):
            raise CollectionDisabled("동결표가 실험 설정과 일치하지 않거나 필수 승인이 없습니다")
        if manifest.collection_enabled:
            _credential_secret(experiment["credential_key_id"])
            documents = {
                row["category"]: dict(row)
                for row in connection.execute(
                    "SELECT * FROM aipol_canonical_documents WHERE experiment_id=?",
                    (experiment_id,),
                )
            }
            if set(documents) != REQUIRED_FREEZE_APPROVALS:
                missing = sorted(REQUIRED_FREEZE_APPROVALS - set(documents))
                raise CollectionDisabled("필수 정본 문서가 없습니다: " + ", ".join(missing))
            documents = {
                category: _validate_canonical_row(connection, document)
                for category, document in documents.items()
            }
            for category, document in documents.items():
                if document["bound_settings_hash"] != _bound_settings_hash(experiment, category):
                    raise CollectionDisabled(f"{category} 정본이 현재 실험 설정과 다릅니다")
                approval = next(item for item in manifest.approvals if item.category == category)
                if approval.content_hash != document["content_hash"]:
                    raise CollectionDisabled(f"{category} 동결 해시가 저장 정본과 다릅니다")
                if approval.approval_id != document["approval_id"]:
                    raise CollectionDisabled(f"{category} 동결 approval_id가 저장 승인과 다릅니다")
            for category, document in documents.items():
                approval = next(item for item in manifest.approvals if item.category == category)
                if approval.approved_by != approved_by or document["approved_by"] != approved_by:
                    raise CollectionDisabled(f"{category} approval does not match the signed approver")
                if approval.approved_at != document["approved_at"]:
                    raise CollectionDisabled(f"{category} approval time does not match the server audit")
            incomplete = [
                option.get("policy_option_id", "?")
                for option in experiment["policy_options"]
                if not option.get("source")
                or not option.get("approved_by")
                or not isinstance(option.get("lever_values"), dict)
                or not option["lever_values"]
            ]
            if incomplete:
                raise CollectionDisabled(
                    "정책안 출처·승인자·레버 값이 동결되지 않았습니다: " + ", ".join(incomplete)
                )
            calculation_approval = next(
                approval for approval in manifest.approvals if approval.category == "calculation"
            )
            calculation_artifact = connection.execute(
                "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, ArtifactKind.PERSONAL_COMPARISON.value),
            ).fetchone()
            calculation_content = json.loads(calculation_artifact["content"]) if calculation_artifact else {}
            if calculation_content.get("canonical_document_hash") != calculation_approval.content_hash:
                raise CollectionDisabled(
                    "동결 승인 해시와 일치하는 개인 조건 비교 도구가 등록되지 않았습니다"
                )
            calculation_evidence = documents["calculation"]["evidence"]
            if (
                calculation_content.get("receipt_contract_hash")
                != calculation_evidence.get("receipt_contract_hash")
            ):
                raise CollectionDisabled("approved calculator completion receipt contract is missing")
            expert = connection.execute(
                "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, ArtifactKind.EXPERT_EXPLANATION.value),
            ).fetchone()
            fallback = connection.execute(
                "SELECT * FROM aipol_ai_candidates WHERE experiment_id=? AND candidate_role='fallback'",
                (experiment_id,),
            ).fetchone()
            if not expert:
                raise CollectionDisabled("approved E1b expert artifact must exist before freeze")
            if not fallback:
                raise CollectionDisabled("approved E2 fallback candidate must exist before freeze")
            _parse_artifact(calculation_artifact, connection)
            _parse_artifact(expert, connection)
            _validate_ai_candidate_row(fallback, connection)
            artifact_bindings = {
                "E1a": calculation_artifact["content_hash"],
                "E1b": expert["content_hash"],
                "E2_fallback": fallback["content_hash"],
                "receipt_contract": calculation_evidence["receipt_contract_hash"],
                "calculator_integration": calculation_evidence["integration_test_hash"],
            }
        else:
            artifact_bindings = {}
        settings_envelope = _live_settings_envelope(experiment)
        settings_hash = content_hash(settings_envelope)
        settings_anchor_id = _id("fsa")
        settings_approval_id = f"freeze-settings:{experiment_id}:{manifest.manifest_id}"
        settings_approved_at = _server_approval(
            connection,
            experiment,
            object_type="freeze_settings",
            object_id="live_settings",
            digest=settings_hash,
            approval_id=settings_approval_id,
            approved_by=approved_by,
        )
        connection.execute(
            "INSERT INTO aipol_freeze_settings_anchors(id,experiment_id,settings_envelope,"
            "settings_hash,approval_id,approved_by,approved_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                settings_anchor_id, experiment_id, _json(settings_envelope), settings_hash,
                settings_approval_id, approved_by, settings_approved_at, time.time(),
            ),
        )
        settings_binding = {
            "anchor_id": settings_anchor_id,
            "settings_hash": settings_hash,
            "approval_id": settings_approval_id,
            "approved_by": approved_by,
            "approved_at": settings_approved_at,
        }
        manifest_anchor_id = _id("fma")
        manifest_approval_id = f"freeze-manifest:{experiment_id}:{manifest.manifest_id}"
        manifest_approved_at = datetime.now(timezone.utc).isoformat()
        manifest_envelope = {
            **asdict(manifest),
            "approvals": [asdict(a) for a in manifest.approvals],
            "artifact_bindings": artifact_bindings,
            "settings_binding": settings_binding,
            "frozen_by": approved_by,
            "frozen_at": manifest_approved_at,
            "manifest_approval": {
                "approval_id": manifest_approval_id,
                "approved_by": approved_by,
                "approved_at": manifest_approved_at,
            },
        }
        manifest_hash = content_hash(manifest_envelope)
        _server_approval(
            connection,
            experiment,
            object_type="freeze_manifest",
            object_id=manifest_anchor_id,
            digest=manifest_hash,
            approval_id=manifest_approval_id,
            approved_by=approved_by,
            approved_at=manifest_approved_at,
        )
        connection.execute(
            "INSERT INTO aipol_freeze_manifest_anchors(id,experiment_id,manifest_envelope,"
            "manifest_hash,approval_id,approved_by,approved_at,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                manifest_anchor_id, experiment_id, _json(manifest_envelope), manifest_hash,
                manifest_approval_id, approved_by, manifest_approved_at, time.time(),
            ),
        )
        connection.execute(
            "UPDATE aipol_experiments SET freeze_manifest=NULL,freeze_manifest_anchor_id=?,"
            "registration_open=? WHERE id=?",
            (
                manifest_anchor_id,
                int(manifest.collection_enabled),
                experiment_id,
            ),
        )
        _queue_experiment_audit(
            connection, actor=approved_by, action="experiment.frozen",
            experiment_id=experiment_id,
            payload={
                "manifest_id": manifest.manifest_id,
                "collection_enabled": manifest.collection_enabled,
                "settings_hash": settings_hash,
                "settings_approval_id": settings_approval_id,
                "manifest_hash": manifest_hash,
                "manifest_approval_id": manifest_approval_id,
            },
        )
    return get_experiment(experiment_id)


def close_registration(experiment_id: str, *, actor: str) -> dict:
    """실제 참가자 등록을 비가역적으로 닫아 M2 마감 집단을 확정한다."""
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if not experiment["collection_enabled"]:
            raise CollectionDisabled("실제 수집이 열린 실험만 등록을 마감할 수 있습니다")
        connection.execute(
            "UPDATE aipol_experiments SET registration_open=0 WHERE id=?", (experiment_id,)
        )
        finalization = _maybe_finalize_m2(
            connection, experiment_id, actor=actor.strip()
        )
        _queue_experiment_audit(
            connection, actor=actor, action="experiment.registration.closed",
            experiment_id=experiment_id,
        )
    return get_experiment(experiment_id)


def mark_pending_attrition(experiment_id: str, *, actor: str, reason: str) -> dict:
    """사전 규칙에 따라 M2 미완료자를 append-only 중도이탈로 보존한다."""
    if not actor.strip() or not reason.strip():
        raise ExperimentError("담당자와 중도이탈 처리 근거가 필요합니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["registration_open"]:
            raise ExperimentError("참가자 등록 마감 뒤에만 중도이탈을 처리할 수 있습니다")
        pending = connection.execute(
            "SELECT * FROM aipol_participants WHERE experiment_id=? AND participant_type='real' "
            "AND stage NOT IN ('E2','M3','complete','withdrawn')",
            (experiment_id,),
        ).fetchall()
        cutoff_at = None
        for row in pending:
            participant = dict(row)
            session = _hydrate(connection, experiment, participant)
            idempotency_key = _id("admin-attrition")
            record = session.withdraw_participant(
                participant["pseudonym"], reason=reason.strip(),
                expected_revision=participant["state_revision"], idempotency_key=idempotency_key,
            )
            cutoff_at = cutoff_at or record.withdrawn_at.isoformat()
            connection.execute(
                "INSERT INTO aipol_withdrawals(id,participant_id,withdrawn_from,reason,withdrawn_at,"
                "actor,cutoff_at,state_revision,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    _id("wd"), participant["id"], record.withdrawn_from.value, record.reason,
                    record.withdrawn_at.isoformat(), actor.strip(), cutoff_at,
                    record.state_revision, record.idempotency_key,
                ),
            )
            connection.execute(
                "UPDATE aipol_participants SET stage='withdrawn',state_revision=? WHERE id=?",
                (record.state_revision, participant["id"]),
            )
        finalization = _maybe_finalize_m2(
            connection, experiment_id, actor=actor.strip()
        )
        _queue_experiment_audit(
            connection, actor=actor, action="experiment.attrition.marked",
            experiment_id=experiment_id,
            payload={"attrited": len(pending), "cutoff_at": cutoff_at, "reason": reason.strip()},
        )
    return {
        "attrited": len(pending),
        "cutoff_at": cutoff_at,
        "cohort_finalized_at": finalization["finalized_at"] if finalization else None,
    }


def _m2_aggregate_snapshot(connection, experiment_id: str) -> dict:
    experiment = get_experiment(experiment_id, connection)
    v2 = experiment["procedure_config"].get("version") == PROCEDURE_CONFIG["version"]
    rows = connection.execute(
        "SELECT p.pseudonym,m.choice,m.stance,m.reason,m.submitted_at FROM aipol_measurements m "
        "JOIN aipol_participants p ON p.id=m.participant_id "
        "WHERE p.experiment_id=? AND p.participant_type='real' AND m.measurement_id='M2' "
        "ORDER BY p.pseudonym",
        (experiment_id,),
    ).fetchall()
    counts: dict[str, int] = {"A": 0, "B": 0, "C": 0, "null": 0}
    for row in rows:
        counts[row["choice"] if row["choice"] in ("A", "B", "C") else "null"] += 1
    cutoff_at = max((row["submitted_at"] for row in rows), default=None)
    stance_counts = {"accept": 0, "conditional": 0, "reject": 0}
    if v2:
        for row in rows:
            if row["stance"] in stance_counts:
                stance_counts[row["stance"]] += 1
    payload = {
        "measurement_id": "M2",
        "participant_count": len(rows),
        "counts": counts,
        "cutoff_at": cutoff_at,
        "response_fingerprints": [
            content_hash(
                {
                    "participant": row["pseudonym"],
                    "choice": row["choice"],
                    **(
                        {
                            "stance": row["stance"],
                            "reason_hash": content_hash(row["reason"] or ""),
                        }
                        if v2 else {}
                    ),
                }
            )
            for row in rows
        ],
    }
    if v2:
        payload["stance_counts"] = stance_counts
    return {**payload, "aggregate_hash": content_hash(payload)}


def _validated_m2_finalization(
    connection: sqlite3.Connection,
    experiment_id: str,
    *,
    required: bool = False,
) -> dict | None:
    row = connection.execute(
        "SELECT * FROM aipol_m2_finalizations WHERE experiment_id=?", (experiment_id,)
    ).fetchone()
    if not row:
        if required:
            raise ExperimentError("M2 cohort-finalized barrier가 아직 없습니다")
        return None
    aggregate = _m2_aggregate_snapshot(connection, experiment_id)
    if not hmac.compare_digest(row["aggregate_hash"], aggregate["aggregate_hash"]):
        raise ImmutableRecordConflict("M2 aggregate no longer matches its finalized barrier")
    registered_count = connection.execute(
        "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? AND participant_type='real'",
        (experiment_id,),
    ).fetchone()[0]
    expected_attrited = registered_count - aggregate["participant_count"]
    envelope = {
        "id": row["id"],
        "experiment_id": experiment_id,
        "aggregate_hash": aggregate["aggregate_hash"],
        "finalized_at": row["finalized_at"],
        "finalized_by": row["finalized_by"],
        "cohort_registered_count": registered_count,
        "cohort_m2_count": aggregate["participant_count"],
        "cohort_attrited_count": expected_attrited,
    }
    barrier_hash = content_hash(envelope)
    if (
        row["cohort_registered_count"] != registered_count
        or row["cohort_m2_count"] != aggregate["participant_count"]
        or row["cohort_attrited_count"] != expected_attrited
        or not hmac.compare_digest(str(row["barrier_hash"]), barrier_hash)
    ):
        raise ImmutableRecordConflict("M2 cohort-finalized envelope no longer matches its barrier")
    _validate_approval_event(
        connection,
        experiment_id=experiment_id,
        object_type="m2_finalization",
        object_id=row["id"],
        digest=barrier_hash,
        approval_id=row["approval_id"],
        approved_by=row["finalized_by"],
        approved_at=row["approved_at"],
    )
    return {**dict(row), "aggregate": aggregate, "barrier_envelope": envelope}


def _maybe_finalize_m2(
    connection: sqlite3.Connection,
    experiment_id: str,
    *,
    actor: str,
) -> dict | None:
    existing = _validated_m2_finalization(connection, experiment_id)
    if existing:
        return existing
    experiment = get_experiment(experiment_id, connection)
    if experiment["registration_open"]:
        return None
    pending = connection.execute(
        "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? AND participant_type='real' "
        "AND stage NOT IN ('E2','M3','complete','withdrawn')",
        (experiment_id,),
    ).fetchone()[0]
    if pending:
        return None
    aggregate = _m2_aggregate_snapshot(connection, experiment_id)
    if not aggregate["participant_count"] or not aggregate["cutoff_at"]:
        return None
    finalized_at = datetime.now(timezone.utc).isoformat()
    finalization_id = _id("m2f")
    registered_count = connection.execute(
        "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? AND participant_type='real'",
        (experiment_id,),
    ).fetchone()[0]
    cohort_attrited_count = registered_count - aggregate["participant_count"]
    envelope = {
        "id": finalization_id,
        "experiment_id": experiment_id,
        "aggregate_hash": aggregate["aggregate_hash"],
        "finalized_at": finalized_at,
        "finalized_by": actor,
        "cohort_registered_count": registered_count,
        "cohort_m2_count": aggregate["participant_count"],
        "cohort_attrited_count": cohort_attrited_count,
    }
    barrier_hash = content_hash(envelope)
    approval_id = f"m2-finalization:{finalization_id}"
    approved_at = _server_approval(
        connection,
        experiment,
        object_type="m2_finalization",
        object_id=finalization_id,
        digest=barrier_hash,
        approval_id=approval_id,
        approved_by=actor,
    )
    connection.execute(
        "INSERT INTO aipol_m2_finalizations(id,experiment_id,aggregate_hash,finalized_at,finalized_by,"
        "cohort_registered_count,cohort_m2_count,cohort_attrited_count,barrier_hash,approval_id,approved_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            finalization_id, experiment_id, aggregate["aggregate_hash"], finalized_at, actor,
            registered_count, aggregate["participant_count"], cohort_attrited_count,
            barrier_hash, approval_id, approved_at,
        ),
    )
    _queue_experiment_audit(
        connection,
        actor=actor,
        action="experiment.m2.finalized",
        experiment_id=experiment_id,
        payload={
            "aggregate_hash": aggregate["aggregate_hash"],
            "barrier_hash": barrier_hash,
            "finalized_at": finalized_at,
            "cohort_registered_count": registered_count,
            "cohort_m2_count": aggregate["participant_count"],
            "cohort_attrited_count": cohort_attrited_count,
        },
    )
    return {
        "experiment_id": experiment_id,
        "aggregate_hash": aggregate["aggregate_hash"],
        "finalized_at": finalized_at,
        "finalized_by": actor,
        "barrier_hash": barrier_hash,
        "aggregate": aggregate,
    }


def m2_aggregate_snapshot(experiment_id: str) -> dict:
    with db._conn() as connection:
        experiment = get_experiment(experiment_id, connection)
        if experiment["registration_open"]:
            raise ExperimentError("등록 마감 뒤에만 M2 집계를 고정할 수 있습니다")
        pending = connection.execute(
            "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? AND participant_type='real' "
            "AND stage NOT IN ('E2','M3','complete','withdrawn')",
            (experiment_id,),
        ).fetchone()[0]
        if pending:
            raise ExperimentError(f"M2가 고정되지 않은 실제 참가자가 {pending}명 있습니다")
        finalization = _validated_m2_finalization(connection, experiment_id, required=True)
        return {
            **finalization["aggregate"],
            "cohort_finalized_at": finalization["finalized_at"],
            "cohort_finalized_by": finalization["finalized_by"],
        }


def release_e2(
    experiment_id: str,
    *,
    candidate_role: str,
    selection_reason: str,
    selected_by: str,
) -> dict:
    """M2 마감 집계와 사람의 후보 선택을 append-only로 남긴 뒤 E2를 공개한다."""
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["registration_open"]:
            raise ExperimentError("먼저 실제 참가자 등록을 마감해야 합니다")
        total = connection.execute(
            "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? AND participant_type='real'",
            (experiment_id,),
        ).fetchone()[0]
        if total == 0:
            raise ExperimentError("E2를 공개할 실제 참가자가 없습니다")
        pending = connection.execute(
            "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? AND participant_type='real' "
            "AND stage NOT IN ('E2','M3','complete','withdrawn')",
            (experiment_id,),
        ).fetchone()[0]
        if pending:
            raise ExperimentError(f"M2가 고정되지 않은 실제 참가자가 {pending}명 있습니다")
        if experiment["e2_released"]:
            raise ImmutableRecordConflict("E2 후보는 이미 선택·공개되었습니다")
        if candidate_role not in ("primary", "fallback") or not selection_reason.strip() or not selected_by.strip():
            raise ExperimentError("E2 후보 역할·선택 사유·인증 진행자가 필요합니다")
        candidate = connection.execute(
            "SELECT * FROM aipol_ai_candidates WHERE experiment_id=? AND candidate_role=?",
            (experiment_id, candidate_role),
        ).fetchone()
        if not candidate:
            raise ExperimentError("선택한 역할의 사람 승인 AI 후보가 없습니다")
        candidate_approval_hash = _validate_ai_candidate_row(candidate, connection)
        finalization = _validated_m2_finalization(connection, experiment_id, required=True)
        aggregate = finalization["aggregate"]
        if not aggregate["participant_count"] or not aggregate["cutoff_at"]:
            raise ExperimentError("M2 응답이 없어 E2를 공개할 수 없습니다")
        if candidate_role == "primary":
            if candidate["m2_aggregate_hash"] != aggregate["aggregate_hash"]:
                raise ExperimentError("primary AI 후보의 M2 집계 해시가 마감 집계와 다릅니다")
            generated = datetime.fromisoformat(candidate["generated_at"].replace("Z", "+00:00"))
            finalized_at = datetime.fromisoformat(
                finalization["finalized_at"].replace("Z", "+00:00")
            )
            if generated <= finalized_at:
                raise ExperimentError("primary AI 후보는 M2 cohort-finalized barrier 뒤 생성되어야 합니다")
        selected_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO aipol_e2_selections(id,experiment_id,candidate_id,candidate_role,"
            "m2_aggregate_hash,m2_cutoff_at,selection_reason,selected_by,selected_at,"
            "candidate_content_hash,candidate_approval_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                _id("es"), experiment_id, candidate["id"], candidate_role,
                aggregate["aggregate_hash"], finalization["finalized_at"], selection_reason.strip(),
                selected_by.strip(), selected_at, candidate["content_hash"], candidate_approval_hash,
            ),
        )
        connection.execute(
            "UPDATE aipol_experiments SET e2_released=1,e2_selected_candidate_id=?,"
            "e2_m2_aggregate_hash=? WHERE id=?",
            (candidate["id"], aggregate["aggregate_hash"], experiment_id),
        )
        _queue_experiment_audit(
            connection, actor=selected_by, action="experiment.e2.released",
            experiment_id=experiment_id,
            payload={
                "candidate_role": candidate_role,
                "aggregate_hash": aggregate["aggregate_hash"],
                "candidate_approval_hash": candidate_approval_hash,
            },
        )
    return get_experiment(experiment_id)


def set_artifact(
    experiment_id: str,
    *,
    kind: str,
    artifact_id: str,
    artifact_version: str,
    content: dict,
    approval_id: str,
    approved_by: str,
    registered_by: str,
    fallback_used: bool = False,
) -> dict:
    artifact_kind = ArtifactKind(kind)
    if artifact_kind is ArtifactKind.AI_OPINION:
        raise ExperimentError("AI 의견은 primary/fallback 후보 등록 API를 사용해야 합니다")
    if artifact_kind is ArtifactKind.PERSONAL_COMPARISON:
        launch_url = str(content.get("launch_url") or "")
        parsed = urlparse(launch_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ExperimentError("개인 조건 비교 도구는 승인된 HTTPS 주소가 필요합니다")
        launch_origin = str(content.get("launch_origin") or "")
        if launch_origin != _canonical_https_origin(launch_origin):
            raise ExperimentError("개인 조건 비교 도구에는 exact HTTPS launch origin이 필요합니다")
        _clean_calculator_launch_url(launch_url, launch_origin)
        if not content.get("calculation_version") or not content.get("limitations"):
            raise ExperimentError("개인 조건 비교 도구의 계산 버전과 한계 안내가 필요합니다")
        if not content.get("canonical_document_hash") or not content.get("build_hash"):
            raise ExperimentError("개인 조건 비교 도구의 정본 문서 해시와 build_hash가 필요합니다")
        if not content.get("receipt_contract_hash"):
            raise ExperimentError("개인 조건 비교 도구에는 receipt 계약 해시가 필요합니다")
        if content.get("integration_contract_version") != CALCULATOR_INTEGRATION_VERSION:
            raise ExperimentError("개인 조건 비교 도구에는 승인된 integration contract가 필요합니다")
        integration_test_hash = str(content.get("integration_test_hash") or "")
        if len(integration_test_hash) != 64 or any(
            ch not in "0123456789abcdef" for ch in integration_test_hash.lower()
        ):
            raise ExperimentError("calculator integration_test_hash must be SHA-256")
    elif not str(content.get("title") or "").strip() or not str(content.get("body") or "").strip():
        raise ExperimentError("전문가·AI 자료에는 제목과 본문이 필요합니다")
    digest = content_hash(content)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["freeze_manifest"] and artifact_kind is not ArtifactKind.FINAL_AI_OPINION:
            raise ExperimentError("동결 뒤에는 필수 E1a/E1b 콘텐츠를 추가할 수 없습니다")
        if artifact_kind is ArtifactKind.FINAL_AI_OPINION:
            if experiment["procedure_config"].get("version") != PROCEDURE_CONFIG["version"]:
                raise ExperimentError("D′ 자료는 v2 절차에서만 등록할 수 있습니다")
            aggregate = _audience_feedback_aggregate_snapshot(
                connection, experiment_id, require_complete=True
            )
            if content.get("audience_feedback_aggregate_hash") != aggregate["aggregate_hash"]:
                raise ExperimentError("D′의 청중 의견 집계 해시가 마감 집계와 다릅니다")
            if content.get("m2_aggregate_hash") != experiment.get("e2_m2_aggregate_hash"):
                raise ExperimentError("D′의 M2 집계 해시가 공개된 D의 근거와 다릅니다")
            expert = connection.execute(
                "SELECT content_hash FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, ArtifactKind.EXPERT_EXPLANATION.value),
            ).fetchone()
            if not expert or content.get("expert_artifact_hash") != expert["content_hash"]:
                raise ExperimentError("D′의 전문가 논평 근거 해시가 승인 자료와 다릅니다")
            provenance_fields = ("model", "deployment", "prompt_version", "generated_at")
            if any(not isinstance(content.get(key), str) or not content[key].strip() for key in provenance_fields):
                raise ExperimentError("D′에는 모델·배포·프롬프트 버전·생성시각이 필요합니다")
            try:
                generated_at = datetime.fromisoformat(
                    content["generated_at"].replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise ExperimentError("D′ generated_at은 ISO 8601 형식이어야 합니다") from exc
            if generated_at.tzinfo is None or generated_at.utcoffset() is None:
                raise ExperimentError("D′ generated_at에는 시간대가 포함되어야 합니다")
            evidence_refs = content.get("evidence_refs")
            if (
                not isinstance(evidence_refs, list)
                or not evidence_refs
                or not all(isinstance(item, str) and item.strip() for item in evidence_refs)
            ):
                raise ExperimentError("D′에는 하나 이상의 근거 식별자가 필요합니다")
        if approved_by != registered_by:
            raise ExperimentError("approved_by는 서명된 승인자 계정과 일치해야 합니다")
        if artifact_kind is ArtifactKind.PERSONAL_COMPARISON:
            canonical = connection.execute(
                "SELECT * FROM aipol_canonical_documents WHERE experiment_id=? AND category='calculation'",
                (experiment_id,),
            ).fetchone()
            if not canonical or content["canonical_document_hash"] != canonical["content_hash"]:
                raise ExperimentError("계산 정본 문서와 연결된 비교 도구만 등록할 수 있습니다")
            evidence = json.loads(canonical["evidence"])
            launch_origin = content["launch_origin"]
            _clean_calculator_launch_url(content["launch_url"], launch_origin)
            if (
                launch_origin != content["launch_origin"]
                or content["launch_origin"] != evidence["approved_origin"]
                or content["build_hash"] != evidence["build_hash"]
            ):
                raise ExperimentError("비교 도구 origin/build가 계산 정본과 다릅니다")
            if content["receipt_contract_hash"] != evidence["receipt_contract_hash"]:
                raise ExperimentError("비교 도구 receipt 계약이 계산 정본과 일치하지 않습니다")
            if (
                content["integration_contract_version"] != evidence["integration_contract_version"]
                or content["integration_test_hash"] != evidence["integration_test_hash"]
            ):
                raise ExperimentError("비교 도구 integration contract/test evidence가 계산 정본과 일치하지 않습니다")
        approved_at = _server_approval(
            connection, experiment, object_type="artifact", object_id=artifact_kind.value,
            digest=digest, approval_id=approval_id, approved_by=approved_by,
        )
        artifact = ExperimentArtifact(
            artifact_id, artifact_version, artifact_kind, digest,
            ArtifactApproval(approval_id, approved_by, approved_at, digest), fallback_used,
        )
        artifact.require_human_approval()
        try:
            connection.execute(
                "INSERT INTO aipol_artifacts(id,experiment_id,kind,artifact_id,artifact_version,"
                "content_hash,content,approval_id,approved_by,approved_at,fallback_used,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _id("ar"), experiment_id, artifact.kind.value, artifact.artifact_id,
                    artifact.artifact_version, artifact.content_hash, _json(content), approval_id,
                    approved_by, approved_at, int(fallback_used), time.time(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            row = connection.execute(
                "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, artifact.kind.value),
            ).fetchone()
            if not row or _parse_artifact(row, connection) != artifact:
                raise IdempotencyConflict("세션 공통 자료는 등록 뒤 교체할 수 없습니다") from exc
        _queue_experiment_audit(
            connection, actor=registered_by, action="experiment.artifact.approved",
            experiment_id=experiment_id,
            payload={"kind": artifact.kind.value, "content_hash": digest, "approval_id": approval_id},
        )
    return artifact_public(experiment_id, artifact.kind.value, include_content=True)


def _audience_feedback_aggregate_snapshot(
    connection: sqlite3.Connection,
    experiment_id: str,
    *,
    require_complete: bool,
) -> dict:
    experiment = get_experiment(experiment_id, connection)
    if experiment["procedure_config"].get("version") != PROCEDURE_CONFIG["version"]:
        raise ExperimentError("청중 의견 집계는 v2 절차에서만 사용할 수 있습니다")
    pending = connection.execute(
        "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? "
        "AND participant_type='real' AND stage NOT IN ('E3','M3','complete','withdrawn')",
        (experiment_id,),
    ).fetchone()[0]
    if require_complete and pending:
        raise ExperimentError(f"청중 의견이 고정되지 않은 실제 참가자가 {pending}명 있습니다")
    rows = connection.execute(
        "SELECT f.response,f.abstained,f.submitted_at,p.pseudonym "
        "FROM aipol_audience_feedback f JOIN aipol_participants p ON p.id=f.participant_id "
        "WHERE p.experiment_id=? AND p.participant_type='real' ORDER BY p.pseudonym",
        (experiment_id,),
    ).fetchall()
    fingerprints = [
        content_hash({
            "participant_pseudonym": row["pseudonym"],
            "response_hash": content_hash(row["response"]) if row["response"] else None,
            "abstained": bool(row["abstained"]),
            "submitted_at": row["submitted_at"],
        })
        for row in rows
    ]
    envelope = {
        "experiment_id": experiment_id,
        "participant_count": len(rows),
        "abstained_count": sum(bool(row["abstained"]) for row in rows),
        "response_fingerprints": fingerprints,
    }
    return {**envelope, "aggregate_hash": content_hash(envelope), "pending_count": pending}


def audience_feedback_aggregate_snapshot(experiment_id: str) -> dict:
    with db._conn() as connection:
        return _audience_feedback_aggregate_snapshot(
            connection, experiment_id, require_complete=True
        )


def _ai_candidate_approval_envelope(
    *,
    candidate_role: str,
    artifact_id: str,
    artifact_version: str,
    content: dict,
    model: str,
    deployment: str,
    prompt_version: str,
    generated_at: str,
    evidence_refs: list[str],
    m2_aggregate_hash: str | None,
) -> dict:
    """Canonical object covered by the human AI-candidate approval."""
    return {
        "candidate_role": candidate_role,
        "artifact_id": artifact_id,
        "artifact_version": artifact_version,
        "content": content,
        "model": model,
        "deployment": deployment,
        "prompt_version": prompt_version,
        "generated_at": generated_at,
        "evidence_refs": evidence_refs,
        "m2_aggregate_hash": m2_aggregate_hash,
    }


def _validate_ai_candidate_row(
    row: sqlite3.Row | dict,
    connection: sqlite3.Connection | None = None,
) -> str:
    value = dict(row)
    try:
        envelope = _ai_candidate_approval_envelope(
            candidate_role=value["candidate_role"],
            artifact_id=value["artifact_id"],
            artifact_version=value["artifact_version"],
            content=json.loads(value["content"]) if isinstance(value["content"], str) else value["content"],
            model=value["model"],
            deployment=value["deployment"],
            prompt_version=value["prompt_version"],
            generated_at=value["generated_at"],
            evidence_refs=(
                json.loads(value["evidence_refs"])
                if isinstance(value["evidence_refs"], str)
                else value["evidence_refs"]
            ),
            m2_aggregate_hash=value.get("m2_aggregate_hash"),
        )
        digest = content_hash(envelope)
        if not hmac.compare_digest(digest, str(value["content_hash"])):
            raise ImmutableRecordConflict("AI candidate provenance does not match its approval hash")
        ArtifactApproval(
            value["approval_id"], value["approved_by"], value["approved_at"], digest
        ).validate(digest)
        if connection is not None:
            _validate_approval_event(
                connection,
                experiment_id=value["experiment_id"],
                object_type="ai_candidate",
                object_id=value["candidate_role"],
                digest=digest,
                approval_id=value["approval_id"],
                approved_by=value["approved_by"],
                approved_at=value["approved_at"],
            )
        return digest
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ImmutableRecordConflict("AI candidate provenance record is malformed") from exc


def set_ai_candidate(
    experiment_id: str,
    *,
    candidate_role: str,
    artifact_id: str,
    artifact_version: str,
    content: dict,
    model: str,
    deployment: str,
    prompt_version: str,
    generated_at: str,
    evidence_refs: list[str],
    m2_aggregate_hash: str | None,
    approval_id: str,
    approved_by: str,
    registered_by: str,
) -> dict:
    if candidate_role not in ("primary", "fallback"):
        raise ExperimentError("AI candidate_role은 primary 또는 fallback이어야 합니다")
    if (
        not isinstance(content, dict)
        or set(content) != {"title", "body"}
        or not str(content.get("title") or "").strip()
        or not str(content.get("body") or "").strip()
    ):
        raise ExperimentError("AI 후보에는 제목과 본문이 필요합니다")
    if not all(value.strip() for value in (
        artifact_id, artifact_version, model, deployment, prompt_version,
        generated_at, approval_id, approved_by, registered_by,
    )):
        raise ExperimentError("AI 후보의 모델·배포·프롬프트·승인 provenance가 필요합니다")
    try:
        generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExperimentError("AI generated_at은 ISO 8601이어야 합니다") from exc
    if generated.tzinfo is None or generated.utcoffset() is None:
        raise ExperimentError("AI generated_at에는 시간대가 필요합니다")
    generated = generated.astimezone(timezone.utc)
    if generated > datetime.now(timezone.utc) + timedelta(seconds=5):
        raise ExperimentError("AI generated_at은 현재 시각보다 미래일 수 없습니다")
    if not isinstance(evidence_refs, list) or not evidence_refs or not all(
        isinstance(item, str) and item.strip() for item in evidence_refs
    ):
        raise ExperimentError("AI evidence_refs에는 한 개 이상의 근거 식별자가 필요합니다")
    evidence_refs = [item.strip() for item in evidence_refs]
    if len(evidence_refs) != len(set(evidence_refs)):
        raise ExperimentError("AI evidence_refs는 중복될 수 없습니다")
    if candidate_role == "primary":
        if (
            not m2_aggregate_hash
            or len(m2_aggregate_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in m2_aggregate_hash.lower())
        ):
            raise ExperimentError("primary AI 후보에는 M2 aggregate SHA-256이 필요합니다")
    elif m2_aggregate_hash is not None:
        raise ExperimentError("fallback AI 후보에는 M2 aggregate hash를 넣지 않습니다")
    artifact_id = artifact_id.strip()
    artifact_version = artifact_version.strip()
    model = model.strip()
    deployment = deployment.strip()
    prompt_version = prompt_version.strip()
    generated_at = generated.isoformat()
    approval_id = approval_id.strip()
    approved_by = approved_by.strip()
    registered_by = registered_by.strip()
    envelope = _ai_candidate_approval_envelope(
        candidate_role=candidate_role,
        artifact_id=artifact_id,
        artifact_version=artifact_version,
        content=content,
        model=model,
        deployment=deployment,
        prompt_version=prompt_version,
        generated_at=generated_at,
        evidence_refs=evidence_refs,
        m2_aggregate_hash=m2_aggregate_hash,
    )
    digest = content_hash(envelope)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if approved_by != registered_by:
            raise ExperimentError("approved_by는 서명된 승인자 계정과 일치해야 합니다")
        if candidate_role == "fallback" and experiment["freeze_manifest"]:
            raise ExperimentError("동결 뒤에는 필수 fallback AI 후보를 추가할 수 없습니다")
        if candidate_role == "primary":
            if experiment["registration_open"]:
                raise ExperimentError("primary AI 후보는 참가 등록 마감 뒤에만 생성할 수 있습니다")
            pending = connection.execute(
                "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? "
                "AND participant_type='real' AND stage NOT IN ('E2','M3','complete','withdrawn')",
                (experiment_id,),
            ).fetchone()[0]
            if pending:
                raise ExperimentError("primary AI 후보 생성 전에 M2 장벽을 완료해야 합니다")
            finalization = _validated_m2_finalization(connection, experiment_id, required=True)
            aggregate = finalization["aggregate"]
            if not aggregate["participant_count"] or not aggregate["cutoff_at"]:
                raise ExperimentError("primary AI 후보에는 최소 한 건의 M2 응답이 필요합니다")
            if m2_aggregate_hash != aggregate["aggregate_hash"]:
                raise ExperimentError("primary AI 후보가 마감된 M2 집계와 결합되지 않았습니다")
            finalized_at = datetime.fromisoformat(
                finalization["finalized_at"].replace("Z", "+00:00")
            )
            if generated <= finalized_at.astimezone(timezone.utc):
                raise ExperimentError("primary AI 후보는 M2 cohort-finalized barrier 뒤에 생성되어야 합니다")
        approved_at = _server_approval(
            connection, experiment, object_type="ai_candidate", object_id=candidate_role,
            digest=digest, approval_id=approval_id, approved_by=approved_by,
        )
        approved = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        if generated > approved.astimezone(timezone.utc):
            raise ExperimentError("AI generated_at은 서버 승인 시각보다 늦을 수 없습니다")
        ArtifactApproval(approval_id, approved_by, approved_at, digest).validate(digest)
        try:
            connection.execute(
                "INSERT INTO aipol_ai_candidates(id,experiment_id,candidate_role,artifact_id,"
                "artifact_version,content,content_hash,model,deployment,prompt_version,generated_at,"
                "evidence_refs,m2_aggregate_hash,approval_id,approved_by,approved_at,registered_by,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _id("ac"), experiment_id, candidate_role, artifact_id, artifact_version,
                    _json(content), digest, model, deployment, prompt_version, generated_at,
                    _json(evidence_refs), m2_aggregate_hash, approval_id, approved_by, approved_at,
                    registered_by, time.time(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ImmutableRecordConflict("AI primary/fallback 후보는 역할별 한 번만 등록할 수 있습니다") from exc
        _queue_experiment_audit(
            connection, actor=registered_by, action="experiment.ai_candidate.approved",
            experiment_id=experiment_id,
            payload={"candidate_role": candidate_role, "content_hash": digest, "approval_id": approval_id},
        )
    return ai_candidate_public(experiment_id, candidate_role, include_content=True)


def ai_candidate_public(experiment_id: str, candidate_role: str, *, include_content: bool) -> dict:
    with db._conn() as connection:
        get_experiment(experiment_id, connection)
        row = connection.execute(
            "SELECT * FROM aipol_ai_candidates WHERE experiment_id=? AND candidate_role=?",
            (experiment_id, candidate_role),
        ).fetchone()
        if not row:
            raise KeyError(candidate_role)
        result = dict(row)
        _validate_ai_candidate_row(result, connection)
    result["evidence_refs"] = json.loads(result["evidence_refs"])
    if include_content:
        result["content"] = json.loads(result["content"])
    else:
        result.pop("content", None)
    return result


def artifact_public(experiment_id: str, kind: str, *, include_content: bool) -> dict | None:
    with db._conn() as connection:
        experiment = get_experiment(experiment_id, connection)
        if kind == ArtifactKind.AI_OPINION.value:
            row = connection.execute(
                "SELECT c.* FROM aipol_ai_candidates c JOIN aipol_experiments e "
                "ON e.e2_selected_candidate_id=c.id WHERE e.id=?",
                (experiment_id,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, kind),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        if kind == ArtifactKind.AI_OPINION.value:
            approval_digest = _validate_ai_candidate_row(result, connection)
            _validate_selected_ai_binding(connection, experiment, result, approval_digest)
            if result["candidate_role"] == "fallback":
                _require_freeze_artifact_digest(experiment, "E2_fallback", result["content_hash"])
            result["fallback_used"] = result["candidate_role"] == "fallback"
            result["evidence_refs"] = json.loads(result["evidence_refs"])
        else:
            artifact = _parse_artifact(result, connection)
            binding_key = {
                ArtifactKind.PERSONAL_COMPARISON.value: "E1a",
                ArtifactKind.EXPERT_EXPLANATION.value: "E1b",
            }.get(kind)
            if experiment.get("freeze_manifest") and binding_key:
                _require_freeze_artifact_digest(experiment, binding_key, artifact.content_hash)
    if include_content:
        result["content"] = json.loads(result["content"])
    else:
        result.pop("content", None)
    return result


def _synthetic_review_experiment(experiment: dict) -> bool:
    manifest = experiment.get("freeze_manifest")
    return bool(
        isinstance(manifest, dict)
        and manifest.get("status") == "frozen"
        and manifest.get("collection_enabled") is False
    )


def _synthetic_review_mode(experiment: dict, participant: dict) -> bool:
    """Return true only for synthetic rehearsals sealed against real collection."""
    return bool(
        participant.get("participant_type") == ParticipantType.SYNTHETIC.value
        and _synthetic_review_experiment(experiment)
    )


def _synthetic_review_ttl_seconds() -> int:
    try:
        configured = int(os.environ.get("AIPOL_SYNTHETIC_REVIEW_TTL_SECONDS", "604800"))
    except ValueError as exc:
        raise RuntimeError("AIPOL_SYNTHETIC_REVIEW_TTL_SECONDS must be an integer") from exc
    return min(2_592_000, max(900, configured))


def _synthetic_review_artifact(
    connection: sqlite3.Connection,
    experiment: dict,
    participant: dict,
    stage: str,
) -> tuple[sqlite3.Row, ExperimentArtifact]:
    """Load an approved artifact without opening any real-collection gate."""
    if not _synthetic_review_mode(experiment, participant):
        raise CollectionDisabled("synthetic review mode is not enabled")
    if stage == "E2":
        row = connection.execute(
            "SELECT * FROM aipol_ai_candidates WHERE experiment_id=? AND candidate_role='fallback'",
            (experiment["id"],),
        ).fetchone()
        if not row:
            raise ExperimentError("합성 검토용 승인 AI 대안이 없습니다")
        return row, _parse_ai_candidate(row, connection)
    kind = {
        "E1a": ArtifactKind.PERSONAL_COMPARISON.value,
        "E1b": ArtifactKind.EXPERT_EXPLANATION.value,
        "E3": ArtifactKind.FINAL_AI_OPINION.value,
    }.get(stage)
    if not kind:
        raise ExperimentError("합성 검토 자료 단계가 올바르지 않습니다")
    row = connection.execute(
        "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
        (experiment["id"], kind),
    ).fetchone()
    if not row:
        raise ExperimentError("합성 검토용 승인 자료가 없습니다")
    return row, _parse_artifact(row, connection)


def _synthetic_review_artifact_public(
    connection: sqlite3.Connection,
    experiment: dict,
    participant: dict,
    stage: str,
) -> dict:
    row, artifact = _synthetic_review_artifact(connection, experiment, participant, stage)
    value = dict(row)
    return {
        "artifact_id": artifact.artifact_id,
        "artifact_version": artifact.artifact_version,
        "content_hash": artifact.content_hash,
        "content": json.loads(value["content"]),
        "approval_id": artifact.approval.approval_id,
        "approved_by": artifact.approval.approved_by,
        "approved_at": artifact.approval.approved_at,
        "fallback_used": artifact.fallback_used,
    }


def register_participant(
    experiment_id: str,
    participant_type: str = "real",
    *,
    admission_code: str = "",
    registration_nonce: str = "",
    idempotency_key: str = "",
    audit_actor: str = "",
) -> dict:
    participant_type_enum = ParticipantType(participant_type)
    recovery_code: str | None = None
    review_expires_at: str | None = None
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if participant_type_enum is ParticipantType.SYNTHETIC:
            manifest = experiment.get("freeze_manifest")
            if not isinstance(manifest, dict) or manifest.get("status") != "frozen":
                raise CollectionDisabled("합성 참가자는 동결 완료된 실험에만 등록할 수 있습니다")
        if participant_type_enum is ParticipantType.REAL:
            if not experiment["registration_open"]:
                raise CollectionDisabled("실제 참가자 등록이 마감되었습니다")
            if not 16 <= len(registration_nonce) <= 128 or not 8 <= len(idempotency_key) <= 128:
                raise ExperimentError("등록 nonce와 멱등 키가 필요합니다")
            credential_key_id = experiment["credential_key_id"]
            nonce_hash = _secret_hash(
                f"registration-nonce:{experiment_id}", registration_nonce,
                key_id=credential_key_id,
            )
            previous = connection.execute(
                "SELECT r.*,p.stage,p.state_revision,p.token_hash FROM aipol_registration_nonces r "
                "JOIN aipol_participants p ON p.id=r.participant_id "
                "WHERE r.experiment_id=? AND (r.nonce_hash=? OR r.idempotency_key=?)",
                (experiment_id, nonce_hash, idempotency_key),
            ).fetchall()
            if previous:
                if len(previous) != 1 or previous[0]["nonce_hash"] != nonce_hash or previous[0]["idempotency_key"] != idempotency_key:
                    raise IdempotencyConflict("등록 nonce 또는 멱등 키가 다른 요청에 사용되었습니다")
                replay_token = _participant_token(
                    experiment_id, registration_nonce, key_id=credential_key_id
                )
                if not hmac.compare_digest(
                    _token_hash(replay_token), str(previous[0]["token_hash"])
                ):
                    raise IdempotencyConflict(
                        "registration token was rotated; use the latest recovery kit"
                    )
                return {
                    "participant_token": replay_token,
                    "stage": previous[0]["stage"],
                    "state_revision": previous[0]["state_revision"],
                    "_registration_replayed": True,
                }
            supplied_code = _secret_hash(
                f"admission-seat:{experiment_id}", admission_code.strip(),
                key_id=credential_key_id,
            )
            seat = connection.execute(
                "SELECT s.id,c.id AS claim_id FROM aipol_admission_seats s "
                "LEFT JOIN aipol_admission_claims c ON c.seat_id=s.id "
                "WHERE s.experiment_id=? AND s.code_hash=?",
                (experiment_id, supplied_code),
            ).fetchone()
            if not seat or seat["claim_id"]:
                raise ParticipantAuthenticationError("참가 자격이 유효하지 않거나 이미 사용되었습니다")
            registered = connection.execute(
                "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? AND participant_type='real'",
                (experiment_id,),
            ).fetchone()[0]
            if registered >= experiment["capacity"]:
                raise CollectionDisabled("참가 정원이 마감되었습니다")
        session = _new_session(experiment)
        pseudonym = _id("participant")
        order = tuple(option["policy_option_id"] for option in experiment["policy_options"])
        session.register_participant(pseudonym, participant_type_enum, option_order=order)
        raw_token = (
            _participant_token(
                experiment_id, registration_nonce, key_id=experiment["credential_key_id"]
            )
            if participant_type_enum is ParticipantType.REAL
            else f"S{secrets.token_hex(16).upper()}"
        )
        participant_id = _id("ap")
        created_at = time.time()
        connection.execute(
            "INSERT INTO aipol_participants(id,experiment_id,pseudonym,token_hash,participant_type,"
            "option_order,stage,state_revision,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                participant_id, experiment_id, pseudonym, _token_hash(raw_token),
                participant_type_enum.value, _json(order), ExperimentStage.CONSENT.value, 0, created_at,
            ),
        )
        if participant_type_enum is ParticipantType.REAL:
            connection.execute(
                "INSERT INTO aipol_registration_nonces VALUES(?,?,?,?,?,?)",
                (
                    _id("rn"), experiment_id, nonce_hash, idempotency_key,
                    participant_id, time.time(),
                ),
            )
            connection.execute(
                "INSERT INTO aipol_admission_claims(id,experiment_id,seat_id,participant_id,claimed_at) "
                "VALUES(?,?,?,?,?)",
                (
                    _id("claim"), experiment_id, seat["id"], participant_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            recovery_code = _issue_recovery_code(
                connection,
                experiment_id=experiment_id,
                participant_id=participant_id,
                credential_key_id=experiment["credential_key_id"],
            )
        else:
            issued_at = datetime.fromtimestamp(created_at, timezone.utc)
            review_expires_at = (
                issued_at + timedelta(seconds=_synthetic_review_ttl_seconds())
            ).isoformat()
            connection.execute(
                "INSERT INTO aipol_synthetic_review_grants VALUES(?,?,?,?,?,?)",
                (
                    _id("srg"), experiment_id, participant_id, audit_actor,
                    issued_at.isoformat(), review_expires_at,
                ),
            )
            _queue_experiment_audit(
                connection, actor=audit_actor, action="experiment.synthetic.registered",
                experiment_id=experiment_id, payload={"participant_id": participant_id},
            )
    result = {"participant_token": raw_token, "stage": "consent", "state_revision": 0}
    if participant_type_enum is ParticipantType.REAL:
        result["_registration_replayed"] = False
        result["recovery_code"] = recovery_code
    else:
        result["review_id"] = participant_id
        result["expires_at"] = review_expires_at
    return result


def revoke_synthetic_review(
    experiment_id: str,
    review_id: str,
    *,
    actor: str,
    reason: str,
) -> dict:
    cleaned_reason = reason.strip()
    if not 4 <= len(cleaned_reason) <= 500:
        raise ExperimentError("합성 검토 링크 폐기 사유는 4~500자여야 합니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        get_experiment(experiment_id, connection)
        participant = connection.execute(
            "SELECT * FROM aipol_participants WHERE id=? AND experiment_id=?",
            (review_id, experiment_id),
        ).fetchone()
        if not participant or participant["participant_type"] != ParticipantType.SYNTHETIC.value:
            raise KeyError(review_id)
        existing = connection.execute(
            "SELECT * FROM aipol_synthetic_review_revocations WHERE participant_id=?",
            (review_id,),
        ).fetchone()
        if existing:
            return {
                "review_id": review_id,
                "revoked_at": existing["revoked_at"],
                "revoked": True,
            }
        revoked_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO aipol_synthetic_review_revocations VALUES(?,?,?,?,?,?)",
            (_id("srr"), experiment_id, review_id, actor, cleaned_reason, revoked_at),
        )
        _queue_experiment_audit(
            connection,
            actor=actor,
            action="experiment.synthetic_review.revoked",
            experiment_id=experiment_id,
            payload={"review_id": review_id, "reason": cleaned_reason},
        )
    return {"review_id": review_id, "revoked_at": revoked_at, "revoked": True}


def recover_participant(experiment_id: str, recovery_code: str) -> dict:
    """Atomically consume a recovery kit and rotate the participant bearer token."""
    code = _validate_recovery_code(recovery_code)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        code_hash = _secret_hash(
            f"participant-recovery:{experiment_id}", code,
            key_id=experiment["credential_key_id"],
        )
        row = connection.execute(
            "SELECT c.id AS recovery_code_id,p.* FROM aipol_participant_recovery_codes c "
            "JOIN aipol_participants p ON p.id=c.participant_id "
            "LEFT JOIN aipol_participant_recoveries r ON r.recovery_code_id=c.id "
            "WHERE c.experiment_id=? AND c.code_hash=? AND r.id IS NULL",
            (experiment_id, code_hash),
        ).fetchone()
        if not row or row["participant_type"] != ParticipantType.REAL.value:
            raise ParticipantAuthenticationError("recovery code is invalid or already consumed")
        participant = dict(row)
        prior_token_hash = str(participant["token_hash"])
        while True:
            raw_token = secrets.token_urlsafe(32)
            replacement_token_hash = _token_hash(raw_token)
            if not connection.execute(
                "SELECT 1 FROM aipol_participants WHERE experiment_id=? AND token_hash=?",
                (experiment_id, replacement_token_hash),
            ).fetchone():
                break
        updated = connection.execute(
            "UPDATE aipol_participants SET token_hash=? WHERE id=? AND token_hash=?",
            (replacement_token_hash, participant["id"], prior_token_hash),
        )
        if updated.rowcount != 1:
            raise StateRevisionConflict("participant token changed during recovery")
        recovered_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO aipol_participant_recoveries(id,recovery_code_id,participant_id,"
            "prior_token_hash,replacement_token_hash,recovered_at) VALUES(?,?,?,?,?,?)",
            (
                _id("prr"), participant["recovery_code_id"], participant["id"],
                prior_token_hash, replacement_token_hash, recovered_at,
            ),
        )
        next_recovery_code = _issue_recovery_code(
            connection,
            experiment_id=experiment_id,
            participant_id=participant["id"],
            credential_key_id=experiment["credential_key_id"],
        )
        return {
            "participant_token": raw_token,
            "stage": participant["stage"],
            "state_revision": participant["state_revision"],
            "recovery_code": next_recovery_code,
        }


def participant_current(experiment_id: str, participant_token: str) -> dict:
    with db._conn() as connection:
        experiment, participant = _load_participant(connection, experiment_id, participant_token)
        session = _hydrate(connection, experiment, participant)
        stage, revision = session.participant_state(participant["pseudonym"])
        result = {
            "experiment_id": experiment_id,
            "title": experiment["title"],
            "stage": stage.value,
            "state_revision": revision,
            "participant_type": participant["participant_type"],
            "option_order": json.loads(participant["option_order"]),
            "procedure_version": experiment["procedure_config"].get("version", ""),
        }
        synthetic_review = _synthetic_review_mode(experiment, participant)
        if synthetic_review:
            result["synthetic_review"] = True
        if stage is ExperimentStage.CONSENT:
            result["consent_version"] = experiment["consent_version"]
            result["consent_text"] = experiment["consent_text"]
        elif stage is ExperimentStage.E1A:
            result["artifact"] = (
                _synthetic_review_artifact_public(
                    connection, experiment, participant, "E1a"
                )
                if synthetic_review
                else _required_artifact_public(
                    experiment_id, ArtifactKind.PERSONAL_COMPARISON.value
                )
            )
            result["artifact"]["stores_raw_inputs"] = False
            if synthetic_review:
                return result
            canonical_row = connection.execute(
                "SELECT * FROM aipol_canonical_documents WHERE experiment_id=? AND category='calculation'",
                (experiment_id,),
            ).fetchone()
            if not canonical_row:
                raise CollectionDisabled("calculation canonical document is missing")
            canonical = _validate_canonical_row(connection, canonical_row)
            _validate_canonical_freeze_binding(experiment, canonical)
            evidence = canonical["evidence"]
            artifact_content = result["artifact"]["content"]
            launch_origin = _canonical_https_origin(str(artifact_content.get("launch_origin") or ""))
            _clean_calculator_launch_url(str(artifact_content.get("launch_url") or ""), launch_origin)
            if (
                artifact_content.get("launch_origin") != launch_origin
                or launch_origin != evidence["approved_origin"]
                or artifact_content.get("build_hash") != evidence["build_hash"]
                or artifact_content.get("receipt_contract_hash") != evidence["receipt_contract_hash"]
                or artifact_content.get("integration_contract_version")
                != evidence["integration_contract_version"]
                or artifact_content.get("integration_test_hash") != evidence["integration_test_hash"]
            ):
                raise ImmutableRecordConflict("calculator artifact no longer matches its canonical evidence")
            _require_freeze_artifact_digest(
                experiment, "receipt_contract", evidence["receipt_contract_hash"]
            )
            _require_freeze_artifact_digest(
                experiment, "calculator_integration", evidence["integration_test_hash"]
            )
            receipt_context = _calculator_context({
                "experiment_id": experiment_id,
                "experiment_version": experiment["experiment_version"],
                "session_id": experiment["session_id"],
                "participant_pseudonym": participant["pseudonym"],
                "artifact_id": result["artifact"]["artifact_id"],
                "artifact_hash": result["artifact"]["content_hash"],
                "contract_hash": result["artifact"]["content"]["receipt_contract_hash"],
            })
            launch_url = artifact_content["launch_url"]
            result["receipt_context"] = receipt_context
            result["calculator_integration"] = {
                "contract_version": CALCULATOR_INTEGRATION_VERSION,
                "allowed_origin": launch_origin,
                "launch_url": launch_url,
                "launch_origin": launch_origin,
                "context_fragment_key": "aipol_context",
                "max_context_bytes": CALCULATOR_CONTEXT_MAX_BYTES,
            }
        elif stage in (ExperimentStage.M1, ExperimentStage.M2, ExperimentStage.M3):
            result["measurement_id"] = stage.value
            result["question_id"] = experiment["measurement_spec"]["question_id"]
            result["question_text"] = experiment["question_text"]
            options = {option["policy_option_id"]: option for option in experiment["policy_options"]}
            result["policy_options"] = [options[key] for key in result["option_order"]]
            if stage is ExperimentStage.M3:
                artifact_stage = (
                    "E3"
                    if experiment["procedure_config"].get("version") == PROCEDURE_CONFIG["version"]
                    else "E2"
                )
                ai = (
                    _synthetic_review_artifact_public(
                        connection, experiment, participant, artifact_stage
                    )
                    if synthetic_review
                    else artifact_public(
                        experiment_id,
                        (
                            ArtifactKind.FINAL_AI_OPINION.value
                            if artifact_stage == "E3"
                            else ArtifactKind.AI_OPINION.value
                        ),
                        include_content=False,
                    )
                )
                if ai:
                    result["secondary_evaluation"] = {
                        "artifact_id": ai["artifact_id"],
                        "separate_from_main_choice": True,
                        "scale": {"min": 1, "max": 5},
                    }
        elif stage is ExperimentStage.E1B:
            result["artifact"] = (
                _synthetic_review_artifact_public(
                    connection, experiment, participant, "E1b"
                )
                if synthetic_review
                else _required_artifact_public(
                    experiment_id, ArtifactKind.EXPERT_EXPLANATION.value
                )
            )
        elif stage is ExperimentStage.E2:
            if participant["participant_type"] == "real" and not experiment["e2_released"]:
                result["waiting_for_e2_release"] = True
            else:
                result["artifact"] = (
                    _synthetic_review_artifact_public(
                        connection, experiment, participant, "E2"
                    )
                    if synthetic_review
                    else _required_artifact_public(
                        experiment_id, ArtifactKind.AI_OPINION.value
                    )
                )
        elif stage is ExperimentStage.A1:
            result["audience_feedback"] = {
                "max_length": 2_000,
                "abstention_allowed": True,
                "raw_response_public": False,
            }
        elif stage is ExperimentStage.E3:
            if synthetic_review:
                try:
                    result["artifact"] = _synthetic_review_artifact_public(
                        connection, experiment, participant, "E3"
                    )
                except ExperimentError:
                    result["waiting_for_e3_release"] = True
            else:
                final_artifact = artifact_public(
                    experiment_id, ArtifactKind.FINAL_AI_OPINION.value, include_content=True
                )
                if final_artifact is None:
                    result["waiting_for_e3_release"] = True
                else:
                    result["artifact"] = _required_artifact_public(
                        experiment_id, ArtifactKind.FINAL_AI_OPINION.value
                    )
        return result


def record_consent(
    experiment_id: str,
    participant_token: str,
    *,
    consent_version: str,
    affirmed: bool,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    payload = {"operation": "consent", "consent_version": consent_version, "affirmed": affirmed}

    def apply(connection, experiment, participant, session):
        if consent_version != experiment["consent_version"]:
            raise ExperimentError("현재 동의문 버전과 다릅니다")
        record = session.record_consent(
            participant["pseudonym"], consent_version=consent_version, affirmed=affirmed,
            expected_revision=expected_revision, idempotency_key=idempotency_key,
        )
        connection.execute(
            "INSERT INTO aipol_consents(id,participant_id,experiment_version,session_id,consent_version,"
            "affirmed,consented_at,state_revision,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                _id("co"), participant["id"], record.experiment_version, record.session_id,
                record.consent_version, int(record.affirmed), record.consented_at.isoformat(), record.state_revision,
                record.idempotency_key,
            ),
        )
        next_stage = session.participant_state(participant["pseudonym"])[0].value
        return {"stage": next_stage, "state_revision": record.state_revision}

    return _write_action(experiment_id, participant_token, idempotency_key, payload, apply)


def record_exposure_open(
    experiment_id: str,
    participant_token: str,
    stage: str,
    *,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    """브라우저가 자료를 렌더한 시점을 완료 확인과 별도 append-only로 기록한다."""
    kinds = {
        "E1a": ArtifactKind.PERSONAL_COMPARISON.value,
        "E1b": ArtifactKind.EXPERT_EXPLANATION.value,
        "E2": ArtifactKind.AI_OPINION.value,
        "E3": ArtifactKind.FINAL_AI_OPINION.value,
    }
    if stage not in kinds or not idempotency_key:
        raise ExperimentError("유효한 노출 단계와 멱등 키가 필요합니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment, participant = _load_participant(connection, experiment_id, participant_token)
        session = _hydrate(connection, experiment, participant)
        current_stage, revision = session.participant_state(participant["pseudonym"])
        if current_stage.value != stage or revision != expected_revision:
            raise StateRevisionConflict("현재 단계 또는 state_revision이 노출 시작 요청과 다릅니다")
        if stage == "E2" and participant["participant_type"] == "real" and not experiment["e2_released"]:
            raise ExperimentError("진행자가 E2를 공개하지 않았습니다")
        synthetic_review = _synthetic_review_mode(experiment, participant)
        if synthetic_review:
            artifact, _ = _synthetic_review_artifact(
                connection, experiment, participant, stage
            )
        elif stage == "E2":
            artifact = connection.execute(
                "SELECT c.* FROM aipol_ai_candidates c "
                "JOIN aipol_experiments e ON e.e2_selected_candidate_id=c.id WHERE e.id=?",
                (experiment_id,),
            ).fetchone()
        else:
            artifact = connection.execute(
                "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, kinds[stage]),
            ).fetchone()
        if not artifact:
            raise ExperimentError("현재 단계의 승인 자료가 없습니다")
        if synthetic_review:
            pass
        elif stage == "E2":
            candidate = dict(artifact)
            approval_digest = _validate_ai_candidate_row(candidate, connection)
            _validate_selected_ai_binding(connection, experiment, candidate, approval_digest)
            if candidate["candidate_role"] == "fallback":
                _require_freeze_artifact_digest(experiment, "E2_fallback", candidate["content_hash"])
        else:
            parsed_artifact = _parse_artifact(artifact, connection)
            if stage in ("E1a", "E1b"):
                _require_freeze_artifact_digest(
                    experiment, stage, parsed_artifact.content_hash
                )
        existing = connection.execute(
            (
                "SELECT *, 'E3' AS stage FROM aipol_v2_exposure_opens WHERE participant_id=?"
                if stage == "E3"
                else "SELECT * FROM aipol_exposure_opens WHERE participant_id=? AND stage=?"
            ),
            (participant["id"],) if stage == "E3" else (participant["id"], stage),
        ).fetchone()
        if existing:
            if existing["artifact_id"] != artifact["artifact_id"] or existing["state_revision"] != revision:
                raise IdempotencyConflict("기존 노출 시작 기록과 현재 자료가 다릅니다")
            return {"stage": stage, "opened_at": existing["opened_at"], "state_revision": revision}
        opened_at = datetime.now(timezone.utc).isoformat()
        if stage == "E3":
            connection.execute(
                "INSERT INTO aipol_v2_exposure_opens VALUES(?,?,?,?,?,?,?)",
                (
                    _id("e3o"), participant["id"], artifact["artifact_id"],
                    artifact["content_hash"], opened_at, revision, idempotency_key,
                ),
            )
        else:
            connection.execute(
                "INSERT INTO aipol_exposure_opens VALUES(?,?,?,?,?,?,?,?)",
                (
                    _id("eo"), participant["id"], stage, artifact["artifact_id"],
                    artifact["content_hash"], opened_at, revision, idempotency_key,
                ),
            )
    return {"stage": stage, "opened_at": opened_at, "state_revision": revision}


def _verify_completion_receipt(
    connection: sqlite3.Connection,
    experiment: dict,
    participant: dict,
    artifact: ExperimentArtifact,
    receipt: dict | None,
) -> None:
    if _synthetic_review_mode(experiment, participant):
        if receipt is not None:
            raise ExperimentError("합성 검토에서는 외부 계산기 영수증을 제출하지 않습니다")
        return
    if not isinstance(receipt, dict) or not receipt:
        raise ExperimentError("E1a 완료에는 외부 계산기의 서명된 one-time receipt가 필요합니다")
    if _completion_receipt_verifier is None:
        raise CollectionDisabled("계산기 completion receipt verifier가 연결되지 않았습니다")
    canonical = connection.execute(
        "SELECT * FROM aipol_canonical_documents WHERE experiment_id=? AND category='calculation'",
        (experiment["id"],),
    ).fetchone()
    if not canonical:
        raise CollectionDisabled("계산 정본 receipt 계약이 없습니다")
    document = _validate_canonical_row(connection, canonical)
    _validate_canonical_freeze_binding(experiment, document)
    evidence = document["evidence"]
    contract = evidence["receipt_contract"]
    contract_hash = _receipt_contract_hash(contract)
    _require_freeze_artifact_digest(experiment, "receipt_contract", contract_hash)
    _require_freeze_artifact_digest(
        experiment, "calculator_integration", evidence["integration_test_hash"]
    )
    artifact_content = connection.execute(
        "SELECT content FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
        (experiment["id"], ArtifactKind.PERSONAL_COMPARISON.value),
    ).fetchone()
    if not artifact_content:
        raise CollectionDisabled("approved calculator artifact is missing")
    live_content = json.loads(artifact_content["content"])
    if (
        live_content.get("receipt_contract_hash") != contract_hash
        or live_content.get("integration_test_hash") != evidence["integration_test_hash"]
    ):
        raise ImmutableRecordConflict("calculator artifact does not match frozen receipt integration")
    context = {
        "experiment_id": experiment["id"],
        "experiment_version": experiment["experiment_version"],
        "session_id": experiment["session_id"],
        "participant_pseudonym": participant["pseudonym"],
        "artifact_id": artifact.artifact_id,
        "artifact_hash": artifact.content_hash,
        "contract_hash": contract_hash,
    }
    receipt_id = _completion_receipt_verifier.verify(receipt, contract, context)
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        raise ExperimentError("receipt verifier가 유효한 외부 receipt id를 반환하지 않았습니다")
    try:
        connection.execute(
            "INSERT INTO aipol_calculator_receipts(id,experiment_id,participant_id,receipt_id,"
            "contract_hash,verified_at,verifier_id,receipt_hash) VALUES(?,?,?,?,?,?,?,?)",
            (
                _id("cr"), experiment["id"], participant["id"], receipt_id.strip(),
                contract_hash, datetime.now(timezone.utc).isoformat(),
                _completion_receipt_verifier.verifier_id, content_hash(receipt),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise IdempotencyConflict("calculator completion receipt는 한 번만 사용할 수 있습니다") from exc


def record_exposure(
    experiment_id: str,
    participant_token: str,
    stage: str,
    *,
    read_ack: bool,
    expected_revision: int,
    idempotency_key: str,
    completion_receipt: dict | None = None,
) -> dict:
    if stage not in ("E1a", "E1b", "E2", "E3"):
        raise ExperimentError("노출 단계가 올바르지 않습니다")
    payload = {
        "operation": "exposure", "stage": stage, "read_ack": read_ack,
        "completion_receipt_hash": content_hash(completion_receipt) if completion_receipt else None,
    }

    def apply(connection, experiment, participant, session):
        if (
            stage == "E2"
            and participant["participant_type"] == ParticipantType.REAL.value
            and not experiment["e2_released"]
        ):
            raise ExperimentError("M2 마감과 사람 승인 뒤 진행자가 E2를 공개해야 합니다")
        synthetic_review = _synthetic_review_mode(experiment, participant)
        if synthetic_review:
            _, artifact = _synthetic_review_artifact(
                connection, experiment, participant, stage
            )
        elif stage == "E1a":
            row = connection.execute(
                "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, ArtifactKind.PERSONAL_COMPARISON.value),
            ).fetchone()
            if not row:
                raise CollectionDisabled("승인된 개인 조건 비교 도구가 아직 없습니다")
            artifact = _parse_artifact(row, connection)
            _require_freeze_artifact_digest(experiment, "E1a", artifact.content_hash)
        elif stage == "E1b":
            row = connection.execute(
                "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, ArtifactKind.EXPERT_EXPLANATION.value),
            ).fetchone()
            if not row:
                raise ExperimentError("승인된 세션 공통 자료가 아직 없습니다")
            artifact = _parse_artifact(row, connection)
            _require_freeze_artifact_digest(experiment, "E1b", artifact.content_hash)
        elif stage == "E2":
            row = connection.execute(
                "SELECT c.* FROM aipol_ai_candidates c JOIN aipol_experiments e "
                "ON e.e2_selected_candidate_id=c.id WHERE e.id=?",
                (experiment_id,),
            ).fetchone()
            if not row:
                raise ExperimentError("선택·승인된 세션 공통 AI 자료가 아직 없습니다")
            artifact = _parse_ai_candidate(row, connection)
            approval_digest = _validate_ai_candidate_row(row, connection)
            _validate_selected_ai_binding(connection, experiment, dict(row), approval_digest)
            if row["candidate_role"] == "fallback":
                _require_freeze_artifact_digest(experiment, "E2_fallback", artifact.content_hash)
        else:
            row = connection.execute(
                "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                (experiment_id, ArtifactKind.FINAL_AI_OPINION.value),
            ).fetchone()
            if not row:
                raise ExperimentError("사람 승인된 D′ 자료가 아직 없습니다")
            artifact = _parse_artifact(row, connection)
        if stage == "E1a":
            _verify_completion_receipt(connection, experiment, participant, artifact, completion_receipt)
        elif completion_receipt is not None:
            raise ExperimentError("completion receipt는 E1a에서만 제출할 수 있습니다")
        opened = connection.execute(
            (
                "SELECT * FROM aipol_v2_exposure_opens WHERE participant_id=?"
                if stage == "E3"
                else "SELECT * FROM aipol_exposure_opens WHERE participant_id=? AND stage=?"
            ),
            (participant["id"],) if stage == "E3" else (participant["id"], stage),
        ).fetchone()
        if not opened or opened["artifact_id"] != artifact.artifact_id:
            raise ExperimentError("자료 노출 시작 기록 뒤에만 확인 완료할 수 있습니다")
        record = session.record_exposure(
            participant["pseudonym"], artifact, read_ack=read_ack,
            opened_at=datetime.fromisoformat(opened["opened_at"]),
            expected_revision=expected_revision, idempotency_key=idempotency_key,
        )
        if stage == "E3":
            connection.execute(
                "INSERT INTO aipol_v2_exposures VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _id("e3x"), participant["id"], record.artifact_id,
                    record.artifact_version, record.content_hash, record.stage_sequence,
                    record.opened_at.isoformat(), record.completed_at.isoformat(), 1,
                    record.approval_id, record.state_revision, record.idempotency_key,
                ),
            )
        else:
            connection.execute(
                "INSERT INTO aipol_exposures(id,participant_id,stage,artifact_id,artifact_version,content_hash,"
                "stage_sequence,opened_at,completed_at,read_ack,fallback_used,approval_id,state_revision,"
                "idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _id("ex"), participant["id"], stage, record.artifact_id, record.artifact_version,
                    record.content_hash, record.stage_sequence, record.opened_at.isoformat(),
                    record.completed_at.isoformat(), 1, int(record.fallback_used), record.approval_id,
                    record.state_revision, record.idempotency_key,
                ),
            )
        return {"stage": session.participant_state(participant["pseudonym"])[0].value,
                "state_revision": record.state_revision}

    return _write_action(experiment_id, participant_token, idempotency_key, payload, apply)


def submit_audience_feedback(
    experiment_id: str,
    participant_token: str,
    *,
    response: str | None,
    abstained: bool,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    """Persist private v2 audience feedback without exposing raw text in read models."""
    cleaned = response.strip() if isinstance(response, str) else None
    payload = {"operation": "audience_feedback", "response": cleaned, "abstained": abstained}

    def apply(connection, experiment, participant, session):
        if experiment["procedure_config"].get("version") != PROCEDURE_CONFIG["version"]:
            raise InvalidTransition("청중 의견은 v2 절차에서만 제출할 수 있습니다")
        record = session.submit_audience_feedback(
            participant["pseudonym"], response=cleaned, abstained=abstained,
            expected_revision=expected_revision, idempotency_key=idempotency_key,
        )
        connection.execute(
            "INSERT INTO aipol_audience_feedback VALUES(?,?,?,?,?,?,?)",
            (
                _id("af"), participant["id"], record.response, int(record.abstained),
                record.submitted_at.isoformat(), record.state_revision, record.idempotency_key,
            ),
        )
        return {"stage": ExperimentStage.E3.value, "state_revision": record.state_revision}

    return _write_action(experiment_id, participant_token, idempotency_key, payload, apply)


def submit_measurement(
    experiment_id: str,
    participant_token: str,
    measurement_id: str,
    *,
    choice: str | None,
    reason: str | None,
    confidence: int | None,
    expected_revision: int,
    idempotency_key: str,
    secondary_evaluation: dict | None = None,
    stance: str | None = None,
) -> dict:
    payload = {
        "operation": "measurement", "measurement_id": measurement_id, "choice": choice,
        "reason": reason, "confidence": confidence, "secondary_evaluation": secondary_evaluation,
        "stance": stance,
    }
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, int)):
        raise ExperimentError("confidence는 1~5 정수 또는 null이어야 합니다")

    def apply(connection, experiment, participant, session):
        if secondary_evaluation is not None and measurement_id != "M3":
            raise ExperimentError("D/D′ 별도 평가는 M3에서만 제출할 수 있습니다")
        record = session.submit_measurement(
            participant["pseudonym"], measurement_id, choice=choice, reason=reason,
            confidence=confidence, expected_revision=expected_revision,
            idempotency_key=idempotency_key, stance=stance,
        )
        connection.execute(
            "INSERT INTO aipol_measurements(id,participant_id,experiment_version,session_id,measurement_id,"
            "participant_type,choice,stance,reason,confidence,question_id,measurement_spec_hash,option_set_version,"
            "option_order,preceding_exposure_hash,submitted_at,state_revision,idempotency_key) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                _id("me"), participant["id"], record.experiment_version, record.session_id,
                record.measurement_id, record.participant_type.value, record.choice, record.stance, record.reason,
                record.confidence, record.question_id, record.measurement_spec_hash,
                record.option_set_version, _json(record.option_order), record.preceding_exposure_hash,
                record.submitted_at.isoformat(), record.state_revision, record.idempotency_key,
            ),
        )
        if secondary_evaluation is not None:
            is_v2 = experiment["procedure_config"].get("version") == PROCEDURE_CONFIG["version"]
            if is_v2:
                ai = connection.execute(
                    "SELECT artifact_id FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
                    (experiment_id, ArtifactKind.FINAL_AI_OPINION.value),
                ).fetchone()
            elif _synthetic_review_mode(experiment, participant):
                ai = connection.execute(
                    "SELECT artifact_id FROM aipol_ai_candidates "
                    "WHERE experiment_id=? AND candidate_role='fallback'",
                    (experiment_id,),
                ).fetchone()
            else:
                ai = connection.execute(
                    "SELECT c.artifact_id FROM aipol_ai_candidates c JOIN aipol_experiments e "
                    "ON e.e2_selected_candidate_id=c.id WHERE e.id=?",
                    (experiment_id,),
                ).fetchone()
            if not ai or secondary_evaluation.get("artifact_id") != ai["artifact_id"]:
                raise ExperimentError("현재 절차의 세션 공통 D/D′ 자료와 다른 평가입니다")
            acceptance = secondary_evaluation.get("acceptance")
            if isinstance(acceptance, bool) or not isinstance(acceptance, int) or not 1 <= acceptance <= 5:
                raise ExperimentError("D/D′ 수용도는 1~5 정수여야 합니다")
            secondary_reason = secondary_evaluation.get("reason")
            if secondary_reason is not None and not isinstance(secondary_reason, str):
                raise ExperimentError("D/D′ 평가 이유는 문자열 또는 null이어야 합니다")
            if isinstance(secondary_reason, str) and len(secondary_reason) > 2_000:
                raise ExperimentError("D/D′ 평가 이유는 2,000자 이하여야 합니다")
            connection.execute(
                "INSERT INTO aipol_secondary_evaluations VALUES(?,?,?,?,?,?,?)",
                (
                    _id("se"), participant["id"], "M3", ai["artifact_id"], acceptance,
                    secondary_reason, record.submitted_at.isoformat(),
                ),
            )
        next_stage = session.participant_state(participant["pseudonym"])[0].value
        return {"stage": next_stage, "state_revision": record.state_revision}

    return _write_action(experiment_id, participant_token, idempotency_key, payload, apply)


def withdraw_participant(
    experiment_id: str,
    participant_token: str,
    *,
    reason: str | None,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    payload = {"operation": "withdraw", "reason": reason}

    def apply(connection, experiment, participant, session):
        record = session.withdraw_participant(
            participant["pseudonym"], reason=reason, expected_revision=expected_revision,
            idempotency_key=idempotency_key,
        )
        connection.execute(
            "INSERT INTO aipol_withdrawals(id,participant_id,withdrawn_from,reason,withdrawn_at,"
            "actor,cutoff_at,state_revision,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                _id("wd"), participant["id"], record.withdrawn_from.value, record.reason,
                record.withdrawn_at.isoformat(), "participant", None,
                record.state_revision, record.idempotency_key,
            ),
        )
        return {"stage": "withdrawn", "state_revision": record.state_revision}

    return _write_action(experiment_id, participant_token, idempotency_key, payload, apply)


def admin_summary(experiment_id: str, participant_type: str = "real") -> dict:
    kind = ParticipantType(participant_type).value
    experiment = get_experiment(experiment_id)
    with db._conn() as connection:
        stages = {
            row["stage"]: row["n"] for row in connection.execute(
                "SELECT stage,COUNT(*) n FROM aipol_participants WHERE experiment_id=? "
                "AND participant_type=? GROUP BY stage", (experiment_id, kind)
            )
        }
        rows = [dict(row) for row in connection.execute(
            "SELECT p.pseudonym,m.measurement_id,m.choice FROM aipol_measurements m "
            "JOIN aipol_participants p ON p.id=m.participant_id "
            "WHERE p.experiment_id=? AND p.participant_type=?", (experiment_id, kind)
        )]
        funnel = {
            "registered": connection.execute(
                "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? AND participant_type=?",
                (experiment_id, kind),
            ).fetchone()[0],
            "consented": connection.execute(
                "SELECT COUNT(*) FROM aipol_consents c JOIN aipol_participants p ON p.id=c.participant_id "
                "WHERE p.experiment_id=? AND p.participant_type=?", (experiment_id, kind),
            ).fetchone()[0],
        }
        for stage in ("E1a", "E1b", "E2"):
            funnel[stage] = connection.execute(
                "SELECT COUNT(*) FROM aipol_exposures e JOIN aipol_participants p ON p.id=e.participant_id "
                "WHERE p.experiment_id=? AND p.participant_type=? AND e.stage=?",
                (experiment_id, kind, stage),
            ).fetchone()[0]
        funnel["withdrawn"] = connection.execute(
            "SELECT COUNT(*) FROM aipol_withdrawals w JOIN aipol_participants p ON p.id=w.participant_id "
            "WHERE p.experiment_id=? AND p.participant_type=?", (experiment_id, kind),
        ).fetchone()[0]
    by_person: dict[str, dict[str, str | None]] = {}
    for row in rows:
        by_person.setdefault(row["pseudonym"], {})[row["measurement_id"]] = row["choice"]
    transitions = {}
    for first, second in (("M1", "M2"), ("M2", "M3"), ("M1", "M3")):
        matrix: dict[str, int] = {}
        for values in by_person.values():
            if first in values and second in values:
                key = f"{values[first]}->{values[second]}"
                matrix[key] = matrix.get(key, 0) + 1
        transitions[f"{first}_{second}"] = matrix
    return {
        "experiment_id": experiment_id,
        "collection_enabled": experiment["collection_enabled"],
        "participant_type": kind,
        "stage_counts": stages,
        "funnel": {
            **funnel,
            "M1": sum(1 for row in rows if row["measurement_id"] == "M1"),
            "M2": sum(1 for row in rows if row["measurement_id"] == "M2"),
            "M3": sum(1 for row in rows if row["measurement_id"] == "M3"),
            "complete": stages.get("complete", 0),
        },
        "measurement_counts": {
            measurement: sum(1 for row in rows if row["measurement_id"] == measurement)
            for measurement in ("M1", "M2", "M3")
        },
        "transitions": transitions,
        "participant_results_public": False,
    }


def _new_session(experiment: dict) -> PensionExperimentSession:
    return PensionExperimentSession(
        experiment_version=experiment["experiment_version"],
        session_id=experiment["session_id"],
        measurement_spec=_parse_spec(experiment["measurement_spec"]),
        policy_options=_parse_options(experiment["policy_options"]),
        freeze_manifest=_parse_manifest(experiment["freeze_manifest"]),
        procedure_config=experiment["procedure_config"],
    )


def _load_participant(connection, experiment_id: str, participant_token: str):
    if not participant_token:
        raise ParticipantAuthenticationError("참여 토큰이 필요합니다")
    experiment = get_experiment(experiment_id, connection)
    participant = connection.execute(
        "SELECT * FROM aipol_participants WHERE experiment_id=? AND token_hash=?",
        (experiment_id, _token_hash(participant_token)),
    ).fetchone()
    if not participant:
        raise ParticipantAuthenticationError("참여 토큰이 유효하지 않습니다")
    participant = dict(participant)
    if participant["participant_type"] == ParticipantType.SYNTHETIC.value:
        grant = connection.execute(
            "SELECT expires_at FROM aipol_synthetic_review_grants WHERE participant_id=?",
            (participant["id"],),
        ).fetchone()
        revoked = connection.execute(
            "SELECT 1 FROM aipol_synthetic_review_revocations WHERE participant_id=?",
            (participant["id"],),
        ).fetchone()
        try:
            expired = not grant or datetime.now(timezone.utc) >= datetime.fromisoformat(
                str(grant["expires_at"])
            )
        except (TypeError, ValueError) as exc:
            raise ImmutableRecordConflict("synthetic review grant expiry is malformed") from exc
        if revoked or expired:
            raise ParticipantAuthenticationError("합성 검토 링크가 만료되었거나 폐기되었습니다")
    return experiment, participant


def _hydrate(connection, experiment: dict, participant: dict) -> PensionExperimentSession:
    session = _new_session(experiment)
    session.register_participant(
        participant["pseudonym"], ParticipantType(participant["participant_type"]),
        option_order=tuple(json.loads(participant["option_order"])),
    )
    expert = connection.execute(
        "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
        (experiment["id"], ArtifactKind.EXPERT_EXPLANATION.value),
    ).fetchone()
    synthetic_review = _synthetic_review_mode(experiment, participant)
    if synthetic_review:
        ai = connection.execute(
            "SELECT * FROM aipol_ai_candidates "
            "WHERE experiment_id=? AND candidate_role='fallback'",
            (experiment["id"],),
        ).fetchone()
    else:
        ai = connection.execute(
            "SELECT c.* FROM aipol_ai_candidates c JOIN aipol_experiments e "
            "ON e.e2_selected_candidate_id=c.id WHERE e.id=?",
            (experiment["id"],),
        ).fetchone()
    if expert:
        expert_artifact = _parse_artifact(expert, connection)
        if experiment.get("freeze_manifest") and not synthetic_review:
            _require_freeze_artifact_digest(experiment, "E1b", expert_artifact.content_hash)
        session.set_expert_artifact(expert_artifact)
    if ai:
        ai_artifact = _parse_ai_candidate(ai, connection)
        if not synthetic_review:
            approval_digest = _validate_ai_candidate_row(ai, connection)
            _validate_selected_ai_binding(connection, experiment, dict(ai), approval_digest)
            if ai["candidate_role"] == "fallback":
                _require_freeze_artifact_digest(experiment, "E2_fallback", ai_artifact.content_hash)
        session.set_session_ai_artifact(ai_artifact)
    final_ai = connection.execute(
        "SELECT * FROM aipol_artifacts WHERE experiment_id=? AND kind=?",
        (experiment["id"], ArtifactKind.FINAL_AI_OPINION.value),
    ).fetchone()
    if final_ai:
        session.set_session_final_ai_artifact(_parse_artifact(final_ai, connection))

    events = []
    consent = connection.execute(
        "SELECT * FROM aipol_consents WHERE participant_id=?", (participant["id"],)
    ).fetchone()
    if consent:
        events.append((consent["state_revision"], "consent", dict(consent)))
    for exposure in connection.execute(
        "SELECT * FROM aipol_exposures WHERE participant_id=?", (participant["id"],)
    ):
        events.append((exposure["state_revision"], "exposure", dict(exposure)))
    for exposure in connection.execute(
        "SELECT *, 'E3' AS stage, 0 AS fallback_used FROM aipol_v2_exposures WHERE participant_id=?",
        (participant["id"],),
    ):
        events.append((exposure["state_revision"], "exposure", dict(exposure)))
    for measurement in connection.execute(
        "SELECT * FROM aipol_measurements WHERE participant_id=?", (participant["id"],)
    ):
        events.append((measurement["state_revision"], "measurement", dict(measurement)))
    feedback = connection.execute(
        "SELECT * FROM aipol_audience_feedback WHERE participant_id=?", (participant["id"],)
    ).fetchone()
    if feedback:
        events.append((feedback["state_revision"], "audience_feedback", dict(feedback)))
    withdrawal = connection.execute(
        "SELECT * FROM aipol_withdrawals WHERE participant_id=?", (participant["id"],)
    ).fetchone()
    if withdrawal:
        events.append((withdrawal["state_revision"], "withdrawal", dict(withdrawal)))
    for revision, event_type, value in sorted(events):
        if event_type == "consent":
            session.record_consent(
                participant["pseudonym"], consent_version=value["consent_version"],
                affirmed=bool(value["affirmed"]),
                expected_revision=revision - 1, idempotency_key=value["idempotency_key"],
            )
        elif event_type == "exposure":
            if value["stage"] == "E1a":
                artifact = ExperimentArtifact(
                    value["artifact_id"], value["artifact_version"],
                    ArtifactKind.PERSONAL_COMPARISON, value["content_hash"],
                )
            elif value["stage"] == "E1b":
                artifact = _parse_artifact(expert, connection)
            elif value["stage"] == "E2":
                artifact = _parse_ai_candidate(ai, connection)
            else:
                artifact = _parse_artifact(final_ai, connection)
            session.record_exposure(
                participant["pseudonym"], artifact, read_ack=True,
                opened_at=datetime.fromisoformat(value["opened_at"]),
                expected_revision=revision - 1, idempotency_key=value["idempotency_key"],
            )
        elif event_type == "measurement":
            session.submit_measurement(
                participant["pseudonym"], value["measurement_id"], choice=value["choice"],
                reason=value["reason"], confidence=value["confidence"],
                expected_revision=revision - 1, idempotency_key=value["idempotency_key"],
                stance=value.get("stance"),
            )
        elif event_type == "audience_feedback":
            session.submit_audience_feedback(
                participant["pseudonym"], response=value["response"],
                abstained=bool(value["abstained"]), expected_revision=revision - 1,
                idempotency_key=value["idempotency_key"],
            )
        else:
            session.withdraw_participant(
                participant["pseudonym"], reason=value["reason"],
                expected_revision=revision - 1, idempotency_key=value["idempotency_key"],
            )
    state, current_revision = session.participant_state(participant["pseudonym"])
    if state.value != participant["stage"] or current_revision != participant["state_revision"]:
        raise ExperimentError("저장된 참가자 상태와 append-only 원장이 일치하지 않습니다")
    return session


def _write_action(experiment_id, participant_token, idempotency_key, payload, apply):
    request_hash = content_hash(payload)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment, participant = _load_participant(connection, experiment_id, participant_token)
        previous = connection.execute(
            "SELECT request_hash,response FROM aipol_idempotency WHERE participant_id=? AND idempotency_key=?",
            (participant["id"], idempotency_key),
        ).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise IdempotencyConflict("같은 idempotency_key에 다른 payload가 제출되었습니다")
            return json.loads(previous["response"])
        session = _hydrate(connection, experiment, participant)
        result = apply(connection, experiment, participant, session)
        new_stage, new_revision = session.participant_state(participant["pseudonym"])
        updated = connection.execute(
            "UPDATE aipol_participants SET stage=?,state_revision=? WHERE id=? AND state_revision=?",
            (new_stage.value, new_revision, participant["id"], participant["state_revision"]),
        )
        if updated.rowcount != 1:
            raise StateRevisionConflict("동시에 제출된 다른 요청이 먼저 반영되었습니다")
        if payload.get("operation") == "measurement" and payload.get("measurement_id") == "M2":
            _maybe_finalize_m2(
                connection, experiment_id, actor="server:participant-m2-transition"
            )
        connection.execute(
            "INSERT INTO aipol_idempotency VALUES(?,?,?,?,?)",
            (participant["id"], idempotency_key, request_hash, _json(result), time.time()),
        )
        return result


def _required_artifact_public(experiment_id: str, kind: str) -> dict:
    artifact = artifact_public(experiment_id, kind, include_content=True)
    if not artifact:
        raise ExperimentError("승인된 세션 공통 자료가 아직 없습니다")
    return {
        "artifact_id": artifact["artifact_id"],
        "artifact_version": artifact["artifact_version"],
        "content_hash": artifact["content_hash"],
        "content": artifact["content"],
        "approval_id": artifact["approval_id"],
        "approved_by": artifact["approved_by"],
        "approved_at": artifact["approved_at"],
        "fallback_used": bool(artifact["fallback_used"]),
    }


init()
