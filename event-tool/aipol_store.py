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
    InvalidTransition,
    MeasurementSpec,
    LEGACY_PROCEDURE_CONFIG,
    ParticipantType,
    PensionExperimentSession,
    PolicyOptionDefinition,
    PROCEDURE_CONFIG,
    REQUIRED_FREEZE_APPROVALS,
    StateRevisionConflict,
    V2_PROCEDURE_CONFIG,
    content_hash,
)
try:
    from policy_lab.domains.pension.experiment import V4_PROCEDURE_CONFIG
except ImportError:  # older v1-v3 domain module; v4 callers remain fail-closed
    V4_PROCEDURE_CONFIG = {"version": "aipol-pension-3-measurements-v4"}
from policy_lab.domains.pension.public_results import (  # noqa: E402
    DeidentifiedMeasurement,
    DeidentifiedOptionAssessment,
    PublicResultError,
    V4_M3_OPTIONS,
    build_t10_results,
    build_t3_m1_results,
    build_t5_results,
    canonical_content_hash,
)
from policy_lab.domains.pension.research_segments import (  # noqa: E402
    AGE_BAND_IDS,
    APPROVED_REASON_TOPIC_CODES,
    EXPECTED_CONTRIBUTION_YEARS_BAND_IDS,
    EXPECTED_RETIREMENT_AGE_BAND_IDS,
    MONTHLY_PERSONAL_INCOME_BAND_IDS,
    PROFILE_FIELDS,
    RULES_VERSION as RESEARCH_SEGMENT_RULES_VERSION,
    ResearchSegmentError,
    project_research_segments,
    validate_research_profile,
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
  event_kind TEXT NOT NULL DEFAULT 'legacy_unclassified',
  source_bundle_version_id TEXT,
  constraint_set_version_id TEXT,
  taxonomy_version_id TEXT,
  source_bundle_hash TEXT,
  constraint_set_hash TEXT,
  taxonomy_hash TEXT,
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
  source_bundle_version_id TEXT,
  source_bundle_hash TEXT,
  constraint_set_version_id TEXT,
  constraint_set_hash TEXT,
  taxonomy_version_id TEXT,
  taxonomy_hash TEXT,
  issue_aggregation_hash TEXT,
  generation_input_hash TEXT,
  ai_draft_hash TEXT,
  approved_d_hash TEXT,
  expert_diff_hash TEXT,
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

CREATE TABLE IF NOT EXISTS aipol_m1_issue_interests (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  taxonomy_version_id TEXT NOT NULL,
  taxonomy_hash TEXT NOT NULL CHECK(length(taxonomy_hash)=64),
  topic_codes_json TEXT NOT NULL,
  submitted_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_audience_discussion_acks (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  acknowledged_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_public_audience_inputs (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK(sequence > 0),
  statement TEXT NOT NULL CHECK(length(trim(statement)) > 0 AND length(statement) <= 2000),
  selected_by TEXT NOT NULL,
  selected_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(experiment_id, sequence),
  UNIQUE(experiment_id, idempotency_key),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
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

CREATE TABLE IF NOT EXISTS aipol_policy_option_acks (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  acknowledged_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(participant_id, idempotency_key),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_m2_option_assessments (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  option_id TEXT NOT NULL CHECK(option_id IN ('A','B','C')),
  stance TEXT NOT NULL CHECK(stance IN ('accept','conditional','reject')),
  reason TEXT CHECK(reason IS NULL OR length(reason) <= 2000),
  created_at TEXT NOT NULL,
  UNIQUE(participant_id, option_id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_m2_reason_classification_drafts (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  option_id TEXT NOT NULL CHECK(option_id IN ('A','B','C')),
  reason_hash TEXT NOT NULL CHECK(length(reason_hash)=64),
  topic_codes TEXT NOT NULL,
  taxonomy_version_id TEXT,
  taxonomy_hash TEXT CHECK(taxonomy_hash IS NULL OR length(taxonomy_hash)=64),
  classified_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(participant_id, option_id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_m2_reason_classifications (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  option_id TEXT NOT NULL CHECK(option_id IN ('A','B','C')),
  reason_hash TEXT NOT NULL CHECK(length(reason_hash)=64),
  topic_codes TEXT NOT NULL,
  taxonomy_version_id TEXT,
  taxonomy_hash TEXT CHECK(taxonomy_hash IS NULL OR length(taxonomy_hash)=64),
  draft_id TEXT NOT NULL UNIQUE,
  draft_hash TEXT NOT NULL CHECK(length(draft_hash)=64),
  classified_by TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  approval_id TEXT NOT NULL UNIQUE,
  approved_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(participant_id, option_id),
  CHECK(classified_by <> approved_by),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id),
  FOREIGN KEY(draft_id) REFERENCES aipol_m2_reason_classification_drafts(id)
);

CREATE TABLE IF NOT EXISTS aipol_research_profiles (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  decision TEXT NOT NULL CHECK(decision IN ('accepted','declined')),
  age_band_id TEXT,
  monthly_personal_income_band_id TEXT,
  expected_contribution_years_band_id TEXT,
  expected_retirement_age_band_id TEXT,
  consent_version TEXT NOT NULL,
  consented_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(participant_id, idempotency_key),
  CHECK(
    (decision='accepted' AND age_band_id IS NOT NULL AND monthly_personal_income_band_id IS NOT NULL
      AND expected_contribution_years_band_id IS NOT NULL AND expected_retirement_age_band_id IS NOT NULL)
    OR
    (decision='declined' AND age_band_id IS NULL AND monthly_personal_income_band_id IS NULL
      AND expected_contribution_years_band_id IS NULL AND expected_retirement_age_band_id IS NULL)
  ),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

-- v4 demographics are a separate append-only receipt.  Only approved band
-- identifiers are persisted; raw age/income values never have a column here.
CREATE TABLE IF NOT EXISTS aipol_demographics (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  gender_band_id TEXT NOT NULL,
  age_band_id TEXT NOT NULL,
  monthly_personal_income_band_id TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_t6_snapshots (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL UNIQUE,
  rules_version TEXT NOT NULL,
  payload TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  frozen_at TEXT NOT NULL,
  frozen_by TEXT NOT NULL,
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_t6_acks (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL UNIQUE,
  snapshot_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  acknowledged_at TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(participant_id, idempotency_key),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id),
  FOREIGN KEY(snapshot_id) REFERENCES aipol_t6_snapshots(id)
);

CREATE TABLE IF NOT EXISTS aipol_m3_option_assessments (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  option_id TEXT NOT NULL CHECK(option_id IN ('A','B','C','D_PRIME')),
  stance TEXT NOT NULL CHECK(stance IN ('accept','conditional','reject')),
  reason TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(participant_id, option_id),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id)
);

CREATE TABLE IF NOT EXISTS aipol_public_result_snapshots (
  id TEXT PRIMARY KEY,
  experiment_id TEXT NOT NULL,
  result_stage TEXT NOT NULL CHECK(result_stage IN ('T3','T5','T10')),
  participant_type TEXT NOT NULL CHECK(participant_type IN ('real','synthetic')),
  scope_key TEXT NOT NULL,
  cutoff_at TEXT NOT NULL,
  rules_version TEXT NOT NULL CHECK(length(trim(rules_version)) > 0),
  snapshot_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  released_by TEXT NOT NULL,
  released_at TEXT NOT NULL,
  UNIQUE(experiment_id,result_stage,participant_type,scope_key),
  FOREIGN KEY(experiment_id) REFERENCES aipol_experiments(id)
);

CREATE TABLE IF NOT EXISTS aipol_public_result_acks (
  id TEXT PRIMARY KEY,
  participant_id TEXT NOT NULL,
  snapshot_id TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  acknowledged_at TEXT NOT NULL,
  state_revision INTEGER NOT NULL,
  idempotency_key TEXT NOT NULL,
  UNIQUE(participant_id,snapshot_id),
  UNIQUE(participant_id,idempotency_key),
  FOREIGN KEY(participant_id) REFERENCES aipol_participants(id),
  FOREIGN KEY(snapshot_id) REFERENCES aipol_public_result_snapshots(id)
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

-- v4 canonical inputs.  A version is append-only: content and approval state
-- are never updated in place, and approval must be performed by another user.
CREATE TABLE IF NOT EXISTS aipol_v4_artifacts (
  id TEXT PRIMARY KEY,
  artifact_type TEXT NOT NULL CHECK(artifact_type IN ('source_bundle','constraint_set','issue_taxonomy')),
  version_id TEXT NOT NULL,
  content_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
  status TEXT NOT NULL CHECK(status IN ('draft','approved','rejected')),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT,
  approval_id TEXT,
  UNIQUE(artifact_type, version_id),
  CHECK(status='draft' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL AND approval_id IS NOT NULL)),
  CHECK(approved_by IS NULL OR approved_by <> created_by)
);
CREATE TRIGGER IF NOT EXISTS aipol_v4_artifacts_immutable_content
BEFORE UPDATE ON aipol_v4_artifacts
WHEN OLD.id <> NEW.id OR OLD.artifact_type <> NEW.artifact_type
  OR OLD.version_id <> NEW.version_id OR OLD.content_json <> NEW.content_json
  OR OLD.content_hash <> NEW.content_hash OR OLD.created_by <> NEW.created_by
  OR OLD.created_at <> NEW.created_at
  OR OLD.status <> 'draft' OR NEW.status NOT IN ('approved','rejected')
BEGIN SELECT RAISE(ABORT, 'immutable artifact version'); END;
CREATE TRIGGER IF NOT EXISTS aipol_v4_artifacts_no_delete
BEFORE DELETE ON aipol_v4_artifacts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
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
CREATE TRIGGER IF NOT EXISTS aipol_m1_issue_interests_no_update
BEFORE UPDATE ON aipol_m1_issue_interests BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m1_issue_interests_no_delete
BEFORE DELETE ON aipol_m1_issue_interests BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_audience_discussion_acks_no_update
BEFORE UPDATE ON aipol_audience_discussion_acks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_audience_discussion_acks_no_delete
BEFORE DELETE ON aipol_audience_discussion_acks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_public_audience_inputs_no_update
BEFORE UPDATE ON aipol_public_audience_inputs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_public_audience_inputs_no_delete
BEFORE DELETE ON aipol_public_audience_inputs BEGIN SELECT RAISE(ABORT, 'append-only'); END;
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
CREATE TRIGGER IF NOT EXISTS aipol_policy_option_acks_no_update
BEFORE UPDATE ON aipol_policy_option_acks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_policy_option_acks_no_delete
BEFORE DELETE ON aipol_policy_option_acks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m2_option_assessments_no_update
BEFORE UPDATE ON aipol_m2_option_assessments BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m2_option_assessments_no_delete
BEFORE DELETE ON aipol_m2_option_assessments BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m2_reason_classification_drafts_no_update
BEFORE UPDATE ON aipol_m2_reason_classification_drafts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m2_reason_classification_drafts_no_delete
BEFORE DELETE ON aipol_m2_reason_classification_drafts BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m2_reason_classifications_no_update
BEFORE UPDATE ON aipol_m2_reason_classifications BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m2_reason_classifications_no_delete
BEFORE DELETE ON aipol_m2_reason_classifications BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_research_profiles_no_update
BEFORE UPDATE ON aipol_research_profiles BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_research_profiles_no_delete
BEFORE DELETE ON aipol_research_profiles BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_demographics_no_update
BEFORE UPDATE ON aipol_demographics BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_demographics_no_delete
BEFORE DELETE ON aipol_demographics BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_t6_snapshots_no_update
BEFORE UPDATE ON aipol_t6_snapshots BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_t6_snapshots_no_delete
BEFORE DELETE ON aipol_t6_snapshots BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_t6_acks_no_update
BEFORE UPDATE ON aipol_t6_acks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_t6_acks_no_delete
BEFORE DELETE ON aipol_t6_acks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m3_option_assessments_no_update
BEFORE UPDATE ON aipol_m3_option_assessments BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_m3_option_assessments_no_delete
BEFORE DELETE ON aipol_m3_option_assessments BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_public_result_snapshots_no_update
BEFORE UPDATE ON aipol_public_result_snapshots BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_public_result_snapshots_no_delete
BEFORE DELETE ON aipol_public_result_snapshots BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_public_result_acks_no_update
BEFORE UPDATE ON aipol_public_result_acks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
CREATE TRIGGER IF NOT EXISTS aipol_public_result_acks_no_delete
BEFORE DELETE ON aipol_public_result_acks BEGIN SELECT RAISE(ABORT, 'append-only'); END;
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
        if "event_kind" not in columns:
            # Existing rows cannot be proven to belong to either v4 namespace.
            connection.execute(
                "ALTER TABLE aipol_experiments ADD COLUMN event_kind TEXT NOT NULL DEFAULT 'legacy_unclassified'"
            )
        for column in (
            "source_bundle_version_id", "constraint_set_version_id", "taxonomy_version_id",
            "source_bundle_hash", "constraint_set_hash", "taxonomy_hash",
        ):
            if column not in columns:
                connection.execute(f"ALTER TABLE aipol_experiments ADD COLUMN {column} TEXT")
        # Upgrade databases created by the initial v4 migration: approval changes
        # status metadata, while the version payload itself remains immutable.
        connection.execute("DROP TRIGGER IF EXISTS aipol_v4_artifacts_no_update")
        connection.execute("DROP TRIGGER IF EXISTS aipol_v4_artifacts_immutable_content")
        connection.execute(
            "CREATE TRIGGER aipol_v4_artifacts_immutable_content BEFORE UPDATE ON aipol_v4_artifacts "
            "WHEN OLD.id <> NEW.id OR OLD.artifact_type <> NEW.artifact_type "
            "OR OLD.version_id <> NEW.version_id OR OLD.content_json <> NEW.content_json "
            "OR OLD.content_hash <> NEW.content_hash OR OLD.created_by <> NEW.created_by "
            "OR OLD.created_at <> NEW.created_at OR OLD.status <> 'draft' "
            "OR NEW.status NOT IN ('approved','rejected') "
            "BEGIN SELECT RAISE(ABORT, 'immutable artifact version'); END"
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
        ai_candidate_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(aipol_ai_candidates)")
        }
        for column in (
            "source_bundle_version_id", "source_bundle_hash",
            "constraint_set_version_id", "constraint_set_hash",
            "taxonomy_version_id", "taxonomy_hash", "issue_aggregation_hash",
            "generation_input_hash", "ai_draft_hash", "approved_d_hash", "expert_diff_hash",
        ):
            if column not in ai_candidate_columns:
                connection.execute(f"ALTER TABLE aipol_ai_candidates ADD COLUMN {column} TEXT")
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
        for table in (
            "aipol_m2_reason_classification_drafts",
            "aipol_m2_reason_classifications",
        ):
            classification_columns = {
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            if "taxonomy_version_id" not in classification_columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN taxonomy_version_id TEXT")
            if "taxonomy_hash" not in classification_columns:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN taxonomy_hash TEXT "
                    "CHECK(taxonomy_hash IS NULL OR length(taxonomy_hash)=64)"
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


_V4_ARTIFACT_TYPES = {"source_bundle", "constraint_set", "issue_taxonomy"}


def _row_v4_artifact(row: sqlite3.Row | dict) -> dict:
    result = dict(row)
    result["content_json"] = json.loads(result["content_json"])
    return result


def create_v4_artifact(*, artifact_type: str, version_id: str,
                       content_json: object, created_by: str) -> dict:
    """Store a draft canonical input; approval is a separate RBAC operation."""
    if artifact_type not in _V4_ARTIFACT_TYPES or not isinstance(version_id, str) or not version_id.strip():
        raise ExperimentError("artifact_type과 version_id가 유효하지 않습니다")
    if not created_by.strip():
        raise ExperimentError("artifact creator가 필요합니다")
    try:
        serialized = _json(content_json)
        digest = content_hash(content_json)
    except (TypeError, ValueError) as exc:
        raise ExperimentError("content_json은 JSON으로 직렬화할 수 있어야 합니다") from exc
    artifact_id = _id("v4a")
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as connection:
        try:
            connection.execute(
                "INSERT INTO aipol_v4_artifacts(id,artifact_type,version_id,content_json,content_hash,status,created_by,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (artifact_id, artifact_type, version_id.strip(), serialized, digest, "draft", created_by.strip(), now),
            )
        except sqlite3.IntegrityError as exc:
            raise ExperimentError("같은 artifact type/version_id가 이미 존재합니다") from exc
        return _row_v4_artifact(connection.execute(
            "SELECT * FROM aipol_v4_artifacts WHERE id=?", (artifact_id,)
        ).fetchone())


def list_v4_artifacts(*, artifact_type: str | None = None) -> list[dict]:
    if artifact_type is not None and artifact_type not in _V4_ARTIFACT_TYPES:
        raise ExperimentError("artifact_type이 유효하지 않습니다")
    with db._conn() as connection:
        if artifact_type is None:
            rows = connection.execute("SELECT * FROM aipol_v4_artifacts ORDER BY created_at DESC").fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM aipol_v4_artifacts WHERE artifact_type=? ORDER BY created_at DESC",
                (artifact_type,),
            ).fetchall()
        return [_row_v4_artifact(row) for row in rows]


def get_v4_artifact(*, artifact_type: str, version_id: str,
                    connection: sqlite3.Connection | None = None) -> dict:
    owns = connection is None
    connection = connection or db._conn()
    try:
        row = connection.execute(
            "SELECT * FROM aipol_v4_artifacts WHERE artifact_type=? AND version_id=?",
            (artifact_type, version_id),
        ).fetchone()
        if not row:
            raise ExperimentError("요청한 v4 artifact version이 없습니다")
        return _row_v4_artifact(row)
    finally:
        if owns:
            connection.close()


def _v4_issue_taxonomy(experiment: dict, connection: sqlite3.Connection) -> dict:
    """Return the approved, event-bound taxonomy after validating its public shape."""
    version_id = experiment.get("taxonomy_version_id")
    expected_hash = experiment.get("taxonomy_hash")
    if not isinstance(version_id, str) or not version_id or not isinstance(expected_hash, str):
        raise ImmutableRecordConflict("v4 행사에 승인된 쟁점 taxonomy가 결속되지 않았습니다")
    artifact = get_v4_artifact(
        artifact_type="issue_taxonomy", version_id=version_id, connection=connection
    )
    if artifact["status"] != "approved" or artifact["content_hash"] != expected_hash:
        raise ImmutableRecordConflict("행사에 결속된 쟁점 taxonomy 승인본이 일치하지 않습니다")
    content = artifact.get("content_json")
    topics = content.get("topics") if isinstance(content, dict) else None
    if not isinstance(topics, list) or not topics:
        raise ImmutableRecordConflict("승인된 쟁점 taxonomy에 topics가 없습니다")
    public_topics: list[dict] = []
    seen: set[str] = set()
    for topic in topics:
        if not isinstance(topic, dict):
            raise ImmutableRecordConflict("쟁점 taxonomy topic 형식이 유효하지 않습니다")
        code = topic.get("code")
        label = topic.get("label")
        if (
            not isinstance(code, str) or not code.strip()
            or not isinstance(label, str) or not label.strip()
            or code in seen
        ):
            raise ImmutableRecordConflict("쟁점 taxonomy code/label이 유효하지 않습니다")
        seen.add(code)
        public_topic = {"code": code, "label": label}
        description = topic.get("description")
        if isinstance(description, str) and description.strip():
            public_topic["description"] = description
        public_topics.append(public_topic)
    mode = content.get("classification_mode", "multi_label")
    if mode not in {"single_label", "multi_label"}:
        raise ImmutableRecordConflict("쟁점 taxonomy 분류 방식이 유효하지 않습니다")
    return {
        "version_id": version_id,
        "content_hash": expected_hash,
        "classification_mode": mode,
        "topics": public_topics,
    }


def _v4_classification_scope(experiment: dict, connection: sqlite3.Connection) -> dict:
    """Bind v4 reason classification to one event namespace and taxonomy."""
    event_kind = experiment.get("event_kind")
    if event_kind == "live":
        participant_type = ParticipantType.REAL.value
    elif event_kind == "review":
        participant_type = ParticipantType.SYNTHETIC.value
    else:
        raise ImmutableRecordConflict("v4 행사의 live/review 구분이 확정되지 않았습니다")
    return {
        "event_kind": event_kind,
        "participant_type": participant_type,
        "taxonomy": _v4_issue_taxonomy(experiment, connection),
    }


def _decide_v4_artifact(*, artifact_type: str, version_id: str, status: str,
                        approved_by: str, approval_id: str) -> dict:
    if status not in {"approved", "rejected"} or not approved_by.strip() or not approval_id.strip():
        raise ExperimentError("승인 상태, 승인자, approval_id가 필요합니다")
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as connection:
        artifact = get_v4_artifact(artifact_type=artifact_type, version_id=version_id, connection=connection)
        if artifact["status"] != "draft":
            raise ExperimentError("draft artifact만 승인/거부할 수 있습니다")
        if artifact["created_by"] == approved_by.strip():
            raise ExperimentError("artifact 작성자와 승인자는 달라야 합니다")
        try:
            connection.execute(
                "UPDATE aipol_v4_artifacts SET status=?,approved_by=?,approved_at=?,approval_id=? WHERE id=?",
                (status, approved_by.strip(), now, approval_id.strip(), artifact["id"]),
            )
        except sqlite3.IntegrityError as exc:
            raise ExperimentError("artifact 승인 메타데이터가 유효하지 않습니다") from exc
        return _row_v4_artifact(connection.execute(
            "SELECT * FROM aipol_v4_artifacts WHERE id=?", (artifact["id"],)
        ).fetchone())


def approve_v4_artifact(**kwargs) -> dict:
    return _decide_v4_artifact(status="approved", **kwargs)


def reject_v4_artifact(**kwargs) -> dict:
    return _decide_v4_artifact(status="rejected", **kwargs)


def _approved_v4_bindings(*, source_bundle_version_id: str,
                          constraint_set_version_id: str,
                          taxonomy_version_id: str,
                          connection: sqlite3.Connection) -> dict:
    requested = {
        "source_bundle": source_bundle_version_id,
        "constraint_set": constraint_set_version_id,
        "issue_taxonomy": taxonomy_version_id,
    }
    result = {}
    for artifact_type, version_id in requested.items():
        artifact = get_v4_artifact(artifact_type=artifact_type, version_id=version_id, connection=connection)
        if artifact["status"] != "approved":
            raise ExperimentError(f"승인된 {artifact_type} artifact version이 필요합니다")
        result[artifact_type] = (artifact["version_id"], artifact["content_hash"])
    return result


def _parse_spec(value: dict) -> MeasurementSpec:
    return MeasurementSpec(**value)


def _public_policy_option_label(policy_option_id: str) -> str:
    return "D′" if policy_option_id == "D_PRIME" else policy_option_id


def _public_policy_option(option: dict) -> dict:
    public_option = dict(option)
    public_option["label"] = _public_policy_option_label(public_option["policy_option_id"])
    return public_option


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
    event_kind: str = "live",
    source_bundle_version_id: str | None = None,
    constraint_set_version_id: str | None = None,
    taxonomy_version_id: str | None = None,
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
    if event_kind not in {"live", "review"}:
        raise ExperimentError("event_kind은 live 또는 review여야 합니다")
    if procedure_version == "v1":
        procedure_config = LEGACY_PROCEDURE_CONFIG
    elif procedure_version == "v2":
        procedure_config = V2_PROCEDURE_CONFIG
    elif procedure_version == "v3":
        procedure_config = PROCEDURE_CONFIG
    elif procedure_version == "v4":
        procedure_config = V4_PROCEDURE_CONFIG
    else:
        raise ExperimentError("procedure_version은 v1, v2, v3 또는 v4여야 합니다")
    if procedure_version == "v4":
        if not all((source_bundle_version_id, constraint_set_version_id, taxonomy_version_id)):
            raise ExperimentError("v4 행사에는 승인된 세 artifact version id가 필요합니다")
    elif any((source_bundle_version_id, constraint_set_version_id, taxonomy_version_id)):
        raise ExperimentError("artifact version id는 v4 행사에서만 사용할 수 있습니다")
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
    if event_kind == "live":
        while len(admission_credentials) < capacity:
            candidate = _new_admission_code()
            if candidate not in admission_credentials:
                admission_credentials.append(candidate)
    with db._conn() as connection:
        bindings = ({"source_bundle": (None, None), "constraint_set": (None, None), "issue_taxonomy": (None, None)}
                    if procedure_version != "v4" else _approved_v4_bindings(
                        source_bundle_version_id=source_bundle_version_id,
                        constraint_set_version_id=constraint_set_version_id,
                        taxonomy_version_id=taxonomy_version_id,
                        connection=connection))
        source_binding = bindings["source_bundle"]
        constraint_binding = bindings["constraint_set"]
        taxonomy_binding = bindings["issue_taxonomy"]
        connection.execute(
            "INSERT INTO aipol_experiments(id,title,experiment_version,session_id,measurement_spec,"
            "question_text,policy_options,freeze_manifest,consent_version,consent_text,"
            "admission_code_hash,capacity,created_by,credential_key_id,procedure_config,event_kind,created_at,"
            "source_bundle_version_id,constraint_set_version_id,taxonomy_version_id,source_bundle_hash,"
            "constraint_set_hash,taxonomy_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                event_kind,
                time.time(),
                source_binding[0], constraint_binding[0], taxonomy_binding[0],
                source_binding[1], constraint_binding[1], taxonomy_binding[1],
            ),
        )
        if admission_credentials:
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
        result.setdefault("event_kind", "legacy_unclassified")
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
            and result["event_kind"] == "live"
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
    is_v2_procedure = _procedure_version(experiment) == V2_PROCEDURE_CONFIG["version"]
    is_current_procedure = _uses_current_procedure(experiment)
    is_v4_procedure = _uses_v4_procedure(experiment)
    uses_structured_m2 = is_current_procedure or is_v4_procedure
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
    assessment_payloads: dict[str, list[dict[str, str]]] = {}
    if uses_structured_m2:
        assessment_rows = connection.execute(
            "SELECT p.pseudonym,a.option_id,a.stance,a.reason "
            "FROM aipol_m2_option_assessments a "
            "JOIN aipol_participants p ON p.id=a.participant_id "
            "WHERE p.experiment_id=? AND p.participant_type='real' "
            "ORDER BY p.pseudonym,CASE a.option_id WHEN 'A' THEN 1 WHEN 'B' THEN 2 ELSE 3 END",
            (experiment_id,),
        ).fetchall()
        for assessment in assessment_rows:
            assessment_payloads.setdefault(assessment["pseudonym"], []).append({
                "option_id": assessment["option_id"],
                "stance": assessment["stance"],
                "reason_hash": content_hash(assessment["reason"] or ""),
            })
        for row in rows:
            assessments = assessment_payloads.get(row["pseudonym"], [])
            if [assessment["option_id"] for assessment in assessments] != ["A", "B", "C"]:
                raise ImmutableRecordConflict("M2 structured option assessments are incomplete")
            selected = next(
                assessment for assessment in assessments
                if assessment["option_id"] == row["choice"]
            )
            if (
                selected["stance"] != row["stance"]
                or selected["reason_hash"] != content_hash(row["reason"] or "")
            ):
                raise ImmutableRecordConflict(
                    "M2 selected assessment no longer matches the measurement snapshot"
                )
    if is_v2_procedure or uses_structured_m2:
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
                        {"option_assessments": assessment_payloads[row["pseudonym"]]}
                        if uses_structured_m2
                        else {
                            "stance": row["stance"],
                            "reason_hash": content_hash(row["reason"] or ""),
                        }
                        if is_v2_procedure
                        else {}
                    ),
                }
            )
            for row in rows
        ],
    }
    if is_v2_procedure or uses_structured_m2:
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


def _research_profile_public_contract() -> dict:
    return {
        "rules_version": RESEARCH_SEGMENT_RULES_VERSION,
        "consent_text": (
            "조건별 연구 분석을 위해 정확한 나이·소득·가입기간·은퇴예상연령이 아닌 "
            "아래 네 구간 ID만 저장하는 데 동의합니다. 구간 정보는 개인 계산 입력과 분리되며 "
            "작은 집단은 공개 결과에서 숨깁니다."
        ),
        "fields": {
            "age_band_id": list(AGE_BAND_IDS),
            "monthly_personal_income_band_id": list(MONTHLY_PERSONAL_INCOME_BAND_IDS),
            "expected_contribution_years_band_id": list(EXPECTED_CONTRIBUTION_YEARS_BAND_IDS),
            "expected_retirement_age_band_id": list(EXPECTED_RETIREMENT_AGE_BAND_IDS),
        },
        "stores_exact_values": False,
    }


def record_research_profile(
    experiment_id: str,
    participant_token: str,
    *,
    profile: dict | None,
    consented: bool,
    consent_version: str,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    """Store only four pre-banded values after explicit participant consent."""
    if consent_version != RESEARCH_SEGMENT_RULES_VERSION:
        raise ExperimentError("현재 연구 구간 동의 버전과 일치하지 않습니다")
    canonical: tuple[str, ...] = ()
    if consented:
        try:
            canonical = validate_research_profile(profile)  # type: ignore[arg-type]
        except ResearchSegmentError as exc:
            raise ExperimentError(str(exc)) from exc
    elif profile not in (None, {}):
        raise ExperimentError("동의하지 않은 경우 연구 구간 값을 제출할 수 없습니다")
    canonical_profile = dict(zip(PROFILE_FIELDS, canonical, strict=True)) if consented else {}
    decision = "accepted" if consented else "declined"
    payload = {
        "operation": "research_profile",
        "profile": canonical_profile,
        "consented": consented,
        "consent_version": consent_version,
    }

    def apply(connection, experiment, participant, session):
        stage, revision = session.participant_state(participant["pseudonym"])
        if not _uses_current_procedure(experiment):
            raise InvalidTransition("연구 구간 프로필은 v3 절차에서만 제출할 수 있습니다")
        if participant["participant_type"] != ParticipantType.REAL.value:
            raise InvalidTransition("합성 검토에는 실제 참가자 연구 프로필을 저장하지 않습니다")
        if stage is not ExperimentStage.E1A or revision != expected_revision:
            raise StateRevisionConflict("E1a 현재 상태에서만 연구 구간 프로필을 제출할 수 있습니다")
        existing = connection.execute(
            "SELECT * FROM aipol_research_profiles WHERE participant_id=?",
            (participant["id"],),
        ).fetchone()
        if existing:
            existing_profile = (
                {field: existing[field] for field in PROFILE_FIELDS}
                if existing["decision"] == "accepted" else {}
            )
            if (
                existing_profile != canonical_profile
                or existing["decision"] != decision
                or existing["consent_version"] != consent_version
            ):
                raise ImmutableRecordConflict("이미 제출한 연구 구간 프로필은 변경할 수 없습니다")
            return {"stage": stage.value, "state_revision": revision, "profile_recorded": True}
        connection.execute(
            "INSERT INTO aipol_research_profiles("
            "id,participant_id,decision,age_band_id,monthly_personal_income_band_id,"
            "expected_contribution_years_band_id,expected_retirement_age_band_id,"
            "consent_version,consented_at,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                _id("rp"), participant["id"], decision,
                *(canonical if consented else (None, None, None, None)), consent_version,
                datetime.now(timezone.utc).isoformat(), idempotency_key,
            ),
        )
        return {
            "stage": stage.value, "state_revision": revision,
            "research_profile_decision": decision,
        }

    return _write_action(experiment_id, participant_token, idempotency_key, payload, apply)


def list_pending_m2_reason_classifications(experiment_id: str, *, classifier: str) -> list[dict]:
    """Return raw reasons only to the authenticated classifier after collection closes."""
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["registration_open"]:
            raise CollectionDisabled("수집 마감 뒤에만 M2 사유를 분류할 수 있습니다")
        taxonomy = None
        if _uses_v4_procedure(experiment):
            scope = _v4_classification_scope(experiment, connection)
            taxonomy = scope["taxonomy"]
            rows = connection.execute(
                "SELECT p.pseudonym,a.option_id,a.reason FROM aipol_m2_option_assessments a "
                "JOIN aipol_participants p ON p.id=a.participant_id "
                "JOIN aipol_demographics g ON g.participant_id=p.id "
                "JOIN aipol_measurements m ON m.participant_id=p.id AND m.measurement_id='M2' "
                "LEFT JOIN aipol_m2_reason_classification_drafts d "
                "ON d.participant_id=a.participant_id AND d.option_id=a.option_id "
                "WHERE p.experiment_id=? AND p.participant_type=? AND d.id IS NULL "
                "ORDER BY p.pseudonym,a.option_id",
                (experiment_id, scope["participant_type"]),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT p.pseudonym,a.option_id,a.reason FROM aipol_m2_option_assessments a "
                "JOIN aipol_participants p ON p.id=a.participant_id "
                "JOIN aipol_research_profiles r ON r.participant_id=p.id AND r.decision='accepted' "
                "LEFT JOIN aipol_m2_reason_classification_drafts d "
                "ON d.participant_id=a.participant_id AND d.option_id=a.option_id "
                "WHERE p.experiment_id=? AND p.participant_type='real' AND d.id IS NULL "
                "ORDER BY p.pseudonym,a.option_id",
                (experiment_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = {
                "participant_pseudonym": row["pseudonym"], "option_id": row["option_id"],
                "reason": row["reason"], "reason_hash": content_hash(row["reason"]),
            }
            if taxonomy is not None:
                item["taxonomy"] = taxonomy
            result.append(item)
        _queue_experiment_audit(
            connection, actor=classifier, action="experiment.m2_reason_classification.pending_read",
            experiment_id=experiment_id, payload={"record_count": len(result)},
        )
        return result


def register_m2_reason_classification_draft(
    experiment_id: str, *, participant_pseudonym: str, option_id: str,
    reason_hash: str, topic_codes: list[str], classified_by: str,
) -> dict:
    if option_id not in ("A", "B", "C"):
        raise ExperimentError("분류할 정책안은 A, B, C 중 하나여야 합니다")
    if (
        not isinstance(topic_codes, list)
        or any(not isinstance(code, str) for code in topic_codes)
        or len(topic_codes) != len(set(topic_codes))
    ):
        raise ExperimentError("사유 분류는 중복 없는 사전 승인 주제 코드만 포함해야 합니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["registration_open"]:
            raise CollectionDisabled("수집 마감 뒤에만 M2 사유 분류 초안을 등록할 수 있습니다")
        taxonomy = None
        if _uses_v4_procedure(experiment):
            scope = _v4_classification_scope(experiment, connection)
            taxonomy = scope["taxonomy"]
            allowed_codes = [topic["code"] for topic in taxonomy["topics"]]
            if (
                not topic_codes
                or any(code not in allowed_codes for code in topic_codes)
                or taxonomy["classification_mode"] == "single_label" and len(topic_codes) != 1
            ):
                raise ExperimentError("v4 사유 분류는 행사에 승인된 taxonomy 주제를 포함해야 합니다")
            canonical_topics = [code for code in allowed_codes if code in topic_codes]
            row = connection.execute(
                "SELECT p.id,a.reason FROM aipol_participants p "
                "JOIN aipol_demographics g ON g.participant_id=p.id "
                "JOIN aipol_measurements m ON m.participant_id=p.id AND m.measurement_id='M2' "
                "JOIN aipol_m2_option_assessments a ON a.participant_id=p.id "
                "WHERE p.experiment_id=? AND p.pseudonym=? AND p.participant_type=? "
                "AND a.option_id=?",
                (experiment_id, participant_pseudonym, scope["participant_type"], option_id),
            ).fetchone()
        else:
            if set(topic_codes) - set(APPROVED_REASON_TOPIC_CODES):
                raise ExperimentError("사유 분류는 중복 없는 사전 승인 주제 코드만 포함해야 합니다")
            canonical_topics = sorted(topic_codes)
            row = connection.execute(
                "SELECT p.id,a.reason FROM aipol_participants p "
                "JOIN aipol_research_profiles r ON r.participant_id=p.id AND r.decision='accepted' "
                "JOIN aipol_m2_option_assessments a "
                "ON a.participant_id=p.id WHERE p.experiment_id=? AND p.pseudonym=? "
                "AND p.participant_type='real' AND a.option_id=?",
                (experiment_id, participant_pseudonym, option_id),
            ).fetchone()
        if not row or reason_hash != content_hash(row["reason"]):
            raise ImmutableRecordConflict("분류 초안의 reason_hash가 원문과 일치하지 않습니다")
        draft_id = _id("m2d")
        created_at = datetime.now(timezone.utc).isoformat()
        connection.execute(
            "INSERT INTO aipol_m2_reason_classification_drafts("
            "id,participant_id,option_id,reason_hash,topic_codes,taxonomy_version_id,taxonomy_hash,"
            "classified_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                draft_id, row["id"], option_id, reason_hash, _json(canonical_topics),
                taxonomy["version_id"] if taxonomy else None,
                taxonomy["content_hash"] if taxonomy else None,
                classified_by, created_at,
            ),
        )
        draft_envelope = {
            "draft_id": draft_id, "participant_pseudonym": participant_pseudonym,
            "option_id": option_id, "reason_hash": reason_hash,
            "topic_codes": canonical_topics, "classified_by": classified_by,
        }
        if taxonomy is not None:
            draft_envelope.update({
                "taxonomy_version_id": taxonomy["version_id"],
                "taxonomy_hash": taxonomy["content_hash"],
            })
        draft_hash = content_hash(draft_envelope)
        _queue_experiment_audit(
            connection, actor=classified_by, action="experiment.m2_reason_classification.drafted",
            experiment_id=experiment_id, payload={**draft_envelope, "draft_hash": draft_hash},
        )
    return {**draft_envelope, "draft_hash": draft_hash, "created_at": created_at}


def list_pending_m2_reason_classification_approvals(
    experiment_id: str, *, approver: str,
) -> list[dict]:
    """Return immutable classifier drafts awaiting a separate human approval.

    Raw reasons are deliberately excluded. The approver sees the reason hash,
    frozen taxonomy binding and proposed topic codes covered by ``draft_hash``.
    """
    with db._conn() as connection:
        experiment = get_experiment(experiment_id, connection)
        if experiment["registration_open"]:
            raise CollectionDisabled("수집 마감 뒤에만 M2 사유 분류를 승인할 수 있습니다")
        taxonomy = None
        if _uses_v4_procedure(experiment):
            taxonomy = _v4_classification_scope(experiment, connection)["taxonomy"]
        rows = connection.execute(
            "SELECT d.*,p.pseudonym FROM aipol_m2_reason_classification_drafts d "
            "JOIN aipol_participants p ON p.id=d.participant_id "
            "LEFT JOIN aipol_m2_reason_classifications c ON c.draft_id=d.id "
            "WHERE p.experiment_id=? AND c.id IS NULL ORDER BY d.created_at,d.id",
            (experiment_id,),
        ).fetchall()
        result = []
        for row in rows:
            envelope = {
                "draft_id": row["id"],
                "participant_pseudonym": row["pseudonym"],
                "option_id": row["option_id"],
                "reason_hash": row["reason_hash"],
                "topic_codes": json.loads(row["topic_codes"]),
                "classified_by": row["classified_by"],
            }
            if taxonomy is not None:
                if (
                    row["taxonomy_version_id"] != taxonomy["version_id"]
                    or row["taxonomy_hash"] != taxonomy["content_hash"]
                ):
                    raise ImmutableRecordConflict(
                        "분류 초안의 taxonomy가 행사 승인본과 일치하지 않습니다"
                    )
                envelope.update({
                    "taxonomy_version_id": taxonomy["version_id"],
                    "taxonomy_hash": taxonomy["content_hash"],
                })
            result.append({
                **envelope,
                "draft_hash": content_hash(envelope),
                "created_at": row["created_at"],
                "self_approval_blocked": row["classified_by"] == approver,
            })
        return result


def approve_m2_reason_classification(
    experiment_id: str, *, draft_id: str, draft_hash: str,
    approval_id: str, approved_by: str,
) -> dict:
    """Approve an immutable classifier draft with a separately authenticated actor."""
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        draft = connection.execute(
            "SELECT d.*,p.pseudonym FROM aipol_m2_reason_classification_drafts d "
            "JOIN aipol_participants p ON p.id=d.participant_id "
            "WHERE d.id=? AND p.experiment_id=?",
            (draft_id, experiment_id),
        ).fetchone()
        if not draft:
            raise ExperimentError("승인할 분류 초안을 찾을 수 없습니다")
        envelope = {
            "draft_id": draft["id"], "participant_pseudonym": draft["pseudonym"],
            "option_id": draft["option_id"], "reason_hash": draft["reason_hash"],
            "topic_codes": json.loads(draft["topic_codes"]),
            "classified_by": draft["classified_by"],
        }
        taxonomy = None
        if _uses_v4_procedure(experiment):
            taxonomy = _v4_classification_scope(experiment, connection)["taxonomy"]
            if (
                draft["taxonomy_version_id"] != taxonomy["version_id"]
                or draft["taxonomy_hash"] != taxonomy["content_hash"]
            ):
                raise ImmutableRecordConflict("분류 초안의 taxonomy가 행사 승인본과 일치하지 않습니다")
            allowed_codes = [topic["code"] for topic in taxonomy["topics"]]
            codes = envelope["topic_codes"]
            if (
                not codes
                or any(code not in allowed_codes for code in codes)
                or taxonomy["classification_mode"] == "single_label" and len(codes) != 1
            ):
                raise ImmutableRecordConflict("분류 초안의 주제 코드가 행사 승인본과 일치하지 않습니다")
            envelope.update({
                "taxonomy_version_id": taxonomy["version_id"],
                "taxonomy_hash": taxonomy["content_hash"],
            })
        if draft_hash != content_hash(envelope):
            raise ImmutableRecordConflict("승인 요청의 draft_hash가 분류 초안과 일치하지 않습니다")
        if draft["classified_by"] == approved_by:
            raise ExperimentError("분류 초안 작성자는 자신의 분류를 승인할 수 없습니다")
        approved_at = datetime.now(timezone.utc).isoformat()
        record_id = _id("m2c")
        connection.execute(
            "INSERT INTO aipol_approval_events(id,experiment_id,object_type,object_id,content_hash,"
            "approval_id,editor_by,approver_by,approved_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                _id("av"), experiment_id, "m2_reason_classification", record_id, draft_hash,
                approval_id, draft["classified_by"], approved_by, approved_at, time.time(),
            ),
        )
        connection.execute(
            "INSERT INTO aipol_m2_reason_classifications("
            "id,participant_id,option_id,reason_hash,topic_codes,taxonomy_version_id,taxonomy_hash,"
            "draft_id,draft_hash,classified_by,approved_by,approval_id,approved_at,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record_id, draft["participant_id"], draft["option_id"], draft["reason_hash"],
                draft["topic_codes"], draft["taxonomy_version_id"], draft["taxonomy_hash"],
                draft["id"], draft_hash, draft["classified_by"],
                approved_by, approval_id, approved_at, approved_at,
            ),
        )
        _queue_experiment_audit(
            connection, actor=approved_by, action="experiment.m2_reason_classification.approved",
            experiment_id=experiment_id,
            payload={"draft_id": draft_id, "draft_hash": draft_hash, "approval_id": approval_id},
        )
    return {"id": record_id, **envelope, "draft_hash": draft_hash,
            "approved_by": approved_by, "approval_id": approval_id, "approved_at": approved_at}


def v4_issue_aggregation_snapshot(experiment_id: str) -> dict:
    """Return reproducible M1-interest and M2-reason counts with explicit denominators."""
    with db._conn() as connection:
        experiment = get_experiment(experiment_id, connection)
        if not _uses_v4_procedure(experiment):
            raise ExperimentError("쟁점 집계 v1은 v4 행사에서만 사용할 수 있습니다")
        if experiment["registration_open"]:
            raise CollectionDisabled("수집 마감 뒤에만 쟁점 집계를 조회할 수 있습니다")
        scope = _v4_classification_scope(experiment, connection)
        taxonomy = scope["taxonomy"]
        topic_order = [topic["code"] for topic in taxonomy["topics"]]
        allowed_codes = set(topic_order)

        m1_rows = connection.execute(
            "SELECT p.id,i.taxonomy_version_id,i.taxonomy_hash,i.topic_codes_json "
            "FROM aipol_participants p "
            "JOIN aipol_demographics g ON g.participant_id=p.id "
            "JOIN aipol_measurements m ON m.participant_id=p.id AND m.measurement_id='M1' "
            "JOIN aipol_m1_issue_interests i ON i.participant_id=p.id "
            "WHERE p.experiment_id=? AND p.participant_type=? ORDER BY p.id",
            (experiment_id, scope["participant_type"]),
        ).fetchall()
        declared_by_topic = {code: set() for code in topic_order}
        for row in m1_rows:
            if (
                row["taxonomy_version_id"] != taxonomy["version_id"]
                or row["taxonomy_hash"] != taxonomy["content_hash"]
            ):
                raise ImmutableRecordConflict("1차 관심 쟁점의 taxonomy 결속이 일치하지 않습니다")
            try:
                codes = json.loads(row["topic_codes_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ImmutableRecordConflict("1차 관심 쟁점 기록이 손상되었습니다") from exc
            if (
                not isinstance(codes, list)
                or not codes
                or len(codes) != len(set(codes))
                or any(code not in allowed_codes for code in codes)
                or taxonomy["classification_mode"] == "single_label" and len(codes) != 1
            ):
                raise ImmutableRecordConflict("1차 관심 쟁점 기록이 승인된 taxonomy와 다릅니다")
            for code in codes:
                declared_by_topic[code].add(row["id"])

        m2_rows = connection.execute(
            "SELECT p.id FROM aipol_participants p "
            "JOIN aipol_demographics g ON g.participant_id=p.id "
            "JOIN aipol_measurements m ON m.participant_id=p.id AND m.measurement_id='M2' "
            "WHERE p.experiment_id=? AND p.participant_type=? ORDER BY p.id",
            (experiment_id, scope["participant_type"]),
        ).fetchall()
        valid_m2_ids = {row["id"] for row in m2_rows}
        classified_people_by_topic = {code: set() for code in topic_order}
        classified_records_by_topic = {code: 0 for code in topic_order}
        approved_reason_records = 0
        for participant_id in sorted(valid_m2_ids):
            assessments = connection.execute(
                "SELECT option_id,reason FROM aipol_m2_option_assessments "
                "WHERE participant_id=? ORDER BY option_id",
                (participant_id,),
            ).fetchall()
            if {row["option_id"] for row in assessments} != {"A", "B", "C"}:
                raise ImmutableRecordConflict("v4 M2 안별 사유가 완전하지 않습니다")
            reasons = {row["option_id"]: row["reason"] for row in assessments}
            classifications = connection.execute(
                "SELECT option_id,reason_hash,topic_codes,taxonomy_version_id,taxonomy_hash "
                "FROM aipol_m2_reason_classifications WHERE participant_id=? ORDER BY option_id",
                (participant_id,),
            ).fetchall()
            for row in classifications:
                if row["option_id"] not in reasons:
                    raise ImmutableRecordConflict("승인된 M2 사유 분류의 정책안이 유효하지 않습니다")
                if row["reason_hash"] != content_hash(reasons[row["option_id"]]):
                    raise ImmutableRecordConflict("승인된 M2 사유 분류가 원문 해시와 일치하지 않습니다")
                if (
                    row["taxonomy_version_id"] != taxonomy["version_id"]
                    or row["taxonomy_hash"] != taxonomy["content_hash"]
                ):
                    raise ImmutableRecordConflict("승인된 M2 사유 분류의 taxonomy가 일치하지 않습니다")
                try:
                    codes = json.loads(row["topic_codes"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ImmutableRecordConflict("승인된 M2 사유 분류가 손상되었습니다") from exc
                if (
                    not isinstance(codes, list)
                    or not codes
                    or len(codes) != len(set(codes))
                    or any(code not in allowed_codes for code in codes)
                    or taxonomy["classification_mode"] == "single_label" and len(codes) != 1
                ):
                    raise ImmutableRecordConflict("승인된 M2 사유 분류가 taxonomy 계약을 위반합니다")
                approved_reason_records += 1
                for code in codes:
                    classified_people_by_topic[code].add(participant_id)
                    classified_records_by_topic[code] += 1

        expected_reason_records = len(valid_m2_ids) * 3
        topics = [
            {
                **topic,
                "declared_interest_participant_count": len(declared_by_topic[topic["code"]]),
                "classified_reason_participant_count": len(
                    classified_people_by_topic[topic["code"]]
                ),
                "classified_reason_record_count": classified_records_by_topic[topic["code"]],
            }
            for topic in taxonomy["topics"]
        ]
        payload = {
            "aggregation_rules_version": "aipol-v4-issue-aggregation-v1",
            "taxonomy": taxonomy,
            "population": {
                "event_kind": scope["event_kind"],
                "participant_type": scope["participant_type"],
            },
            "denominators": {
                "declared_interest_respondents": len(m1_rows),
                "valid_m2_respondents": len(valid_m2_ids),
                "expected_reason_records": expected_reason_records,
                "approved_reason_records": approved_reason_records,
                "missing_reason_records": expected_reason_records - approved_reason_records,
            },
            "definitions": {
                "declared_interest_participant_count": (
                    "유효 M1 응답자 중 해당 쟁점을 관심 쟁점으로 직접 선택한 고유 참가자 수"
                ),
                "classified_reason_participant_count": (
                    "유효 M2 응답자 중 승인된 사유 분류에서 해당 쟁점이 한 번 이상 나온 고유 참가자 수"
                ),
                "classified_reason_record_count": (
                    "승인된 A/B/C 사유 레코드 중 해당 쟁점으로 분류된 레코드 수"
                ),
            },
            "multi_label_totals_may_exceed_denominator": (
                taxonomy["classification_mode"] == "multi_label"
            ),
            "classification_complete": approved_reason_records == expected_reason_records,
            "topics": topics,
        }
        return {**payload, "content_hash": content_hash(payload)}


def acknowledge_t6_snapshot(
    experiment_id: str,
    participant_token: str,
    *,
    content_hash_value: str,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    payload = {
        "operation": "t6_ack",
        "content_hash": content_hash_value,
    }

    def apply(connection, experiment, participant, session):
        stage, revision = session.participant_state(participant["pseudonym"])
        if stage is not ExperimentStage.E2 or revision != expected_revision:
            raise StateRevisionConflict("E2의 T6 결과 화면에서만 확인할 수 있습니다")
        if participant["participant_type"] != ParticipantType.REAL.value:
            raise InvalidTransition("합성 검토는 실제 T6 snapshot 확인 원장에 기록하지 않습니다")
        if _pending_public_result(connection, experiment, participant) is not None:
            raise InvalidTransition("먼저 T5 공개 결과를 확인해야 합니다")
        snapshot = _validated_t6_snapshot(connection, experiment_id, required=True)
        if content_hash_value != snapshot["content_hash"]:
            raise ImmutableRecordConflict("표시된 T6 결과 해시와 확인 요청이 다릅니다")
        connection.execute(
            "INSERT INTO aipol_t6_acks(id,participant_id,snapshot_id,content_hash,"
            "acknowledged_at,idempotency_key) VALUES(?,?,?,?,?,?)",
            (
                _id("t6a"), participant["id"], snapshot["snapshot_id"], content_hash_value,
                datetime.now(timezone.utc).isoformat(), idempotency_key,
            ),
        )
        return {
            "stage": stage.value, "state_revision": revision,
            "acknowledged_result": "T6",
        }

    return _write_action(experiment_id, participant_token, idempotency_key, payload, apply)


def _build_t6_snapshot(
    connection, experiment_id: str, finalization: dict, *, selected_candidate=None
) -> dict:
    participants = connection.execute(
        "SELECT p.id,r.age_band_id,r.monthly_personal_income_band_id,"
        "r.expected_contribution_years_band_id,r.expected_retirement_age_band_id "
        "FROM aipol_participants p "
        "JOIN aipol_measurements m ON m.participant_id=p.id AND m.measurement_id='M2' "
        "JOIN aipol_research_profiles r ON r.participant_id=p.id AND r.decision='accepted' "
        "WHERE p.experiment_id=? AND p.participant_type='real' ORDER BY p.id",
        (experiment_id,),
    ).fetchall()
    responses = []
    for participant in participants:
        assessments = connection.execute(
            "SELECT option_id,stance FROM aipol_m2_option_assessments "
            "WHERE participant_id=? ORDER BY option_id",
            (participant["id"],),
        ).fetchall()
        if {row["option_id"] for row in assessments} != {"A", "B", "C"}:
            raise ImmutableRecordConflict("M2 안별 판단이 완전하지 않아 T6를 생성할 수 없습니다")
        topics: dict[str, list[str]] = {}
        classifications = connection.execute(
            "SELECT option_id,reason_hash,topic_codes FROM aipol_m2_reason_classifications "
            "WHERE participant_id=? ORDER BY option_id",
            (participant["id"],),
        ).fetchall()
        if {row["option_id"] for row in classifications} != {"A", "B", "C"}:
            raise CollectionDisabled(
                "M2 자유서술의 AI 분류와 사람 승인이 완전하지 않아 T6를 공개할 수 없습니다"
            )
        reasons = {row["option_id"]: row["reason"] for row in connection.execute(
            "SELECT option_id,reason FROM aipol_m2_option_assessments WHERE participant_id=?",
            (participant["id"],),
        )}
        for row in classifications:
            if row["reason_hash"] != content_hash(reasons[row["option_id"]]):
                raise ImmutableRecordConflict("M2 사유 분류가 원문 해시와 일치하지 않습니다")
            try:
                codes = json.loads(row["topic_codes"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ImmutableRecordConflict("승인된 M2 사유 분류가 손상되었습니다") from exc
            if not isinstance(codes, list):
                raise ImmutableRecordConflict("승인된 M2 사유 분류 형식이 올바르지 않습니다")
            topics[row["option_id"]] = codes
        responses.append({
            "profile": {field: participant[field] for field in PROFILE_FIELDS},
            "stances": {
                row["option_id"]: {
                    "stance": row["stance"],
                    "reason_topic_codes": topics[row["option_id"]],
                }
                for row in assessments
            },
        })
    try:
        projection = project_research_segments(responses)
    except ResearchSegmentError as exc:
        raise ImmutableRecordConflict(str(exc)) from exc
    candidate = selected_candidate or connection.execute(
        "SELECT c.* FROM aipol_ai_candidates c JOIN aipol_experiments e "
        "ON e.e2_selected_candidate_id=c.id WHERE e.id=?",
        (experiment_id,),
    ).fetchone()
    if not candidate:
        raise CollectionDisabled("T6 AI 설명에 결박할 승인된 D 후보가 없습니다")
    # T6 is a deterministic projection of the frozen M2 ledger.  Do not reuse
    # the separately approved D candidate body as though it were an analysis
    # of the segment table: fallback D can pre-date the event and a primary D
    # body has a different contract.  We retain the candidate linkage only as
    # provenance for the following D exposure.
    analysis_narrative = {
        "analysis_type": "deterministic-approved-topic-projection",
        "text": (
            "마감된 M2 판단과 별도 사람 승인을 거친 주제 코드만 사전 고정 규칙으로 "
            "집계했습니다. 이 설명은 잠정 의견 D의 본문을 재사용한 AI 해석이 아닙니다."
        ),
        "rules_version": RESEARCH_SEGMENT_RULES_VERSION,
        "m2_aggregate_hash": finalization["aggregate"]["aggregate_hash"],
    }
    d_candidate_provenance = {
        "artifact_id": candidate["artifact_id"],
        "content_hash": candidate["content_hash"],
        "model": candidate["model"],
        "deployment": candidate["deployment"],
        "prompt_version": candidate["prompt_version"],
        "generated_at": candidate["generated_at"],
        "evidence_refs": json.loads(candidate["evidence_refs"]),
        "approval_id": candidate["approval_id"],
        "approved_by": candidate["approved_by"],
        "approved_at": candidate["approved_at"],
        "fallback_used": candidate["candidate_role"] == "fallback",
    }
    envelope = {
        "snapshot_type": "T6",
        "measurement_id": "M2",
        "rules_version": RESEARCH_SEGMENT_RULES_VERSION,
        "m2_aggregate_hash": finalization["aggregate"]["aggregate_hash"],
        "cutoff_at": finalization["finalized_at"],
        "projection": projection,
        "analysis_narrative": analysis_narrative,
        "d_candidate_provenance": d_candidate_provenance,
    }
    return {**envelope, "content_hash": content_hash(envelope)}


def _validated_t6_snapshot(connection, experiment_id: str, *, required: bool = True) -> dict | None:
    row = connection.execute(
        "SELECT * FROM aipol_t6_snapshots WHERE experiment_id=?", (experiment_id,)
    ).fetchone()
    if not row:
        if required:
            raise CollectionDisabled("T6 조건별 분석 결과가 아직 동결되지 않았습니다")
        return None
    try:
        payload = json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ImmutableRecordConflict("T6 snapshot payload가 손상되었습니다") from exc
    if (
        row["rules_version"] != RESEARCH_SEGMENT_RULES_VERSION
        or payload.get("rules_version") != RESEARCH_SEGMENT_RULES_VERSION
        or row["content_hash"] != content_hash({k: v for k, v in payload.items() if k != "content_hash"})
        or payload.get("content_hash") != row["content_hash"]
    ):
        raise ImmutableRecordConflict("T6 snapshot 해시 또는 규칙 버전이 일치하지 않습니다")
    finalization = _validated_m2_finalization(connection, experiment_id, required=True)
    rebuilt = _build_t6_snapshot(connection, experiment_id, finalization)
    if rebuilt != payload:
        raise ImmutableRecordConflict("T6 snapshot이 append-only 원장과 일치하지 않습니다")
    return {"snapshot_id": row["id"], **payload, "frozen_at": row["frozen_at"]}


def _freeze_t6_snapshot(
    connection, experiment_id: str, *, frozen_by: str, finalization: dict, selected_candidate
) -> dict:
    existing = _validated_t6_snapshot(connection, experiment_id, required=False)
    if existing:
        return existing
    payload = _build_t6_snapshot(
        connection, experiment_id, finalization, selected_candidate=selected_candidate
    )
    snapshot_id = _id("t6")
    frozen_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        "INSERT INTO aipol_t6_snapshots(id,experiment_id,rules_version,payload,content_hash,frozen_at,frozen_by) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            snapshot_id, experiment_id, RESEARCH_SEGMENT_RULES_VERSION, _json(payload),
            payload["content_hash"], frozen_at, frozen_by,
        ),
    )
    _queue_experiment_audit(
        connection, actor=frozen_by, action="experiment.t6.frozen",
        experiment_id=experiment_id,
        payload={"snapshot_id": snapshot_id, "content_hash": payload["content_hash"]},
    )
    return {"snapshot_id": snapshot_id, **payload, "frozen_at": frozen_at}


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
        t6_snapshot = None
        if _uses_current_procedure(experiment):
            t6_snapshot = _freeze_t6_snapshot(
                connection, experiment_id, frozen_by=selected_by.strip(),
                finalization=finalization, selected_candidate=candidate,
            )
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
                "t6_snapshot_hash": t6_snapshot["content_hash"] if t6_snapshot else None,
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
            if not _uses_deliberation_procedure(experiment):
                raise ExperimentError("D′ 자료는 v2/v3 절차에서만 등록할 수 있습니다")
            if _uses_current_procedure(experiment):
                _validate_policy_lever_values(
                    experiment, content.get("lever_values"), label="D′"
                )
                if _synthetic_review_experiment(experiment):
                    d_candidate = connection.execute(
                        "SELECT artifact_id,content_hash FROM aipol_ai_candidates "
                        "WHERE experiment_id=? AND candidate_role='fallback'",
                        (experiment_id,),
                    ).fetchone()
                else:
                    d_candidate = connection.execute(
                        "SELECT c.artifact_id,c.content_hash FROM aipol_ai_candidates c "
                        "JOIN aipol_experiments e ON e.e2_selected_candidate_id=c.id "
                        "WHERE e.id=?",
                        (experiment_id,),
                    ).fetchone()
                if (
                    not d_candidate
                    or content.get("d_artifact_id") != d_candidate["artifact_id"]
                    or content.get("d_content_hash") != d_candidate["content_hash"]
                ):
                    raise ExperimentError("D′는 직전에 공개된 D의 artifact ID와 콘텐츠 해시를 근거로 포함해야 합니다")
            synthetic_review = _synthetic_review_experiment(experiment)
            if synthetic_review:
                if content.get("synthetic_review") is not True:
                    raise ExperimentError("합성 검토용 D′에는 synthetic_review=true가 필요합니다")
                if any(content.get(key) is not None for key in (
                    "m2_aggregate_hash", "public_audience_input_hash",
                )):
                    raise ExperimentError("합성 검토용 D′는 실제 M2·청중 집계 해시를 참조할 수 없습니다")
            else:
                aggregate = _public_audience_input_snapshot(
                    connection, experiment_id, require_complete=True
                )
                if content.get("public_audience_input_hash") != aggregate["aggregate_hash"]:
                    raise ExperimentError("D′의 진행자 선별 공개 의견 해시가 마감 입력과 다릅니다")
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
            generated_at = generated_at.astimezone(timezone.utc)
            if generated_at > datetime.now(timezone.utc) + timedelta(seconds=5):
                raise ExperimentError("D′ generated_at은 현재 시각보다 미래일 수 없습니다")
            if _uses_current_procedure(experiment) and not _synthetic_review_experiment(experiment):
                barrier_rows = connection.execute(
                    "SELECT e.completed_at AS barrier_at FROM aipol_exposures e "
                    "JOIN aipol_participants p ON p.id=e.participant_id "
                    "WHERE p.experiment_id=? AND p.participant_type='real' AND e.stage='E1b' "
                    "UNION ALL "
                    "SELECT a.acknowledged_at FROM aipol_audience_discussion_acks a "
                    "JOIN aipol_participants p ON p.id=a.participant_id "
                    "WHERE p.experiment_id=? AND p.participant_type='real' "
                    "UNION ALL "
                    "SELECT selected_at FROM aipol_public_audience_inputs WHERE experiment_id=?",
                    (experiment_id, experiment_id, experiment_id),
                ).fetchall()
                latest_barrier = max(
                    datetime.fromisoformat(row["barrier_at"].replace("Z", "+00:00"))
                    .astimezone(timezone.utc)
                    for row in barrier_rows
                    if row["barrier_at"]
                )
                if generated_at <= latest_barrier:
                    raise ExperimentError(
                        "D′는 모든 실제 참가자의 전문가 설명 확인·청중 절차 확인과 "
                        "최종 공개 입력 뒤에 생성되어야 합니다"
                    )
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


def _public_audience_input_snapshot(
    connection: sqlite3.Connection,
    experiment_id: str,
    *,
    require_complete: bool,
) -> dict:
    experiment = get_experiment(experiment_id, connection)
    if not _uses_deliberation_procedure(experiment):
        raise ExperimentError("공개 청중 의견 입력은 v2/v3 절차에서만 사용할 수 있습니다")
    pending = connection.execute(
        "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? "
        "AND participant_type='real' AND stage NOT IN ('E3','M3','complete','withdrawn')",
        (experiment_id,),
    ).fetchone()[0]
    if require_complete and pending:
        raise ExperimentError(f"공개 청중 의견 절차를 확인하지 않은 실제 참가자가 {pending}명 있습니다")
    rows = connection.execute(
        "SELECT sequence,statement,selected_by,selected_at "
        "FROM aipol_public_audience_inputs WHERE experiment_id=? ORDER BY sequence",
        (experiment_id,),
    ).fetchall()
    if require_complete and not rows:
        raise ExperimentError("진행자가 선별한 공개 청중 의견이 하나 이상 필요합니다")
    inputs = [
        {
            "sequence": row["sequence"],
            "statement": row["statement"],
            "selected_by": row["selected_by"],
            "selected_at": row["selected_at"],
        }
        for row in rows
    ]
    envelope = {
        "experiment_id": experiment_id,
        "input_count": len(inputs),
        "inputs": inputs,
    }
    return {**envelope, "aggregate_hash": content_hash(envelope), "pending_count": pending}


def public_audience_input_snapshot(experiment_id: str) -> dict:
    with db._conn() as connection:
        return _public_audience_input_snapshot(
            connection, experiment_id, require_complete=False
        )


def register_public_audience_input(
    experiment_id: str,
    *,
    sequence: int,
    statement: str,
    selected_by: str,
    idempotency_key: str,
) -> dict:
    cleaned = statement.strip() if isinstance(statement, str) else ""
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ExperimentError("공개 청중 의견 순번은 1 이상의 정수여야 합니다")
    if not cleaned or len(cleaned) > 2_000:
        raise ExperimentError("공개 청중 의견은 1~2,000자여야 합니다")
    if not idempotency_key:
        raise ExperimentError("idempotency_key는 필수입니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if not _uses_deliberation_procedure(experiment):
            raise ExperimentError("공개 청중 의견 입력은 v2/v3 절차에서만 사용할 수 있습니다")
        existing = connection.execute(
            "SELECT * FROM aipol_public_audience_inputs WHERE experiment_id=? AND idempotency_key=?",
            (experiment_id, idempotency_key),
        ).fetchone()
        if existing:
            if (
                existing["sequence"] != sequence
                or existing["statement"] != cleaned
                or existing["selected_by"] != selected_by
            ):
                raise IdempotencyConflict("idempotency_key가 다른 공개 청중 의견과 충돌합니다")
            return dict(existing)
        discussion_started = connection.execute(
            "SELECT COUNT(*) FROM aipol_participants WHERE experiment_id=? "
            "AND stage IN ('A1','E3','M3','complete')",
            (experiment_id,),
        ).fetchone()[0]
        if not experiment["e2_released"] or not discussion_started:
            raise InvalidTransition("공개 청중 의견 절차가 시작된 뒤에만 진행자 선별 입력을 등록할 수 있습니다")
        selected_at = datetime.now(timezone.utc).isoformat()
        try:
            record_id = _id("pai")
            connection.execute(
                "INSERT INTO aipol_public_audience_inputs VALUES(?,?,?,?,?,?,?)",
                (record_id, experiment_id, sequence, cleaned, selected_by, selected_at, idempotency_key),
            )
        except sqlite3.IntegrityError as exc:
            raise ImmutableRecordConflict("공개 청중 의견 순번은 등록 후 교체할 수 없습니다") from exc
        _queue_experiment_audit(
            connection,
            actor=selected_by,
            action="experiment.public_audience_input.selected",
            experiment_id=experiment_id,
            payload={"sequence": sequence, "statement_hash": content_hash(cleaned)},
        )
        return {
            "id": record_id,
            "experiment_id": experiment_id,
            "sequence": sequence,
            "statement": cleaned,
            "selected_by": selected_by,
            "selected_at": selected_at,
            "idempotency_key": idempotency_key,
        }


_V4_D_CONTENT_KEYS = {
    "title", "body", "lever_values", "public_summary", "deliberation_process",
    "ai_draft", "approved_d", "expert_approval_diff", "approval_rationale",
}
_V4_D_FORBIDDEN_KEYS = {
    "chain_of_thought", "chainOfThought", "cot", "hidden_reasoning", "raw_reason",
    "raw_reasons", "raw_response", "participant_id", "participant_pseudonym",
    "participant_token", "prompt", "system_prompt", "output_private", "outputPrivateJson",
}


def _reject_private_d_fields(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _V4_D_FORBIDDEN_KEYS:
                raise ExperimentError("D안 공개 artifact에 비공개 추론·원문·식별정보를 넣을 수 없습니다")
            _reject_private_d_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_private_d_fields(nested)


def _prepare_v4_ai_candidate_content(
    *, experiment: dict, candidate_role: str, content: dict,
    m2_aggregate_hash: str | None, issue_snapshot: dict | None,
    connection: sqlite3.Connection,
) -> tuple[dict, dict]:
    """Canonicalize public D content and bind every approved generation input."""
    if set(content) != _V4_D_CONTENT_KEYS:
        raise ExperimentError("v4 D안에는 공개 요약·숙의 단계·AI 초안·전문가 수정·승인 사유가 필요합니다")
    for field in ("title", "body", "public_summary", "approval_rationale"):
        if not isinstance(content.get(field), str) or not content[field].strip():
            raise ExperimentError(f"v4 D안의 {field} 값이 필요합니다")
    process = content.get("deliberation_process")
    if not isinstance(process, list) or not process:
        raise ExperimentError("v4 D안에는 실제 실행에서 파생된 공개 숙의 단계가 필요합니다")
    for step in process:
        if (
            not isinstance(step, dict) or set(step) != {"stage", "summary"}
            or not isinstance(step.get("stage"), str) or not step["stage"].strip()
            or not isinstance(step.get("summary"), str) or not step["summary"].strip()
        ):
            raise ExperimentError("공개 숙의 단계는 stage와 summary로 구성해야 합니다")
    for field in ("ai_draft", "approved_d"):
        value = content.get(field)
        if not isinstance(value, dict) or set(value) != {"title", "body", "lever_values"}:
            raise ExperimentError(f"v4 D안의 {field} 구조가 유효하지 않습니다")
        if not str(value.get("title") or "").strip() or not str(value.get("body") or "").strip():
            raise ExperimentError(f"v4 D안의 {field} 제목과 본문이 필요합니다")
        _validate_policy_lever_values(experiment, value.get("lever_values"), label=field)
    if content["approved_d"] != {
        "title": content["title"], "body": content["body"],
        "lever_values": content["lever_values"],
    }:
        raise ExperimentError("공개 D안과 전문가 승인본이 일치해야 합니다")
    diff = content.get("expert_approval_diff")
    if not isinstance(diff, list):
        raise ExperimentError("전문가 수정 diff는 배열이어야 합니다")
    for item in diff:
        if (
            not isinstance(item, dict)
            or set(item) != {"field", "before", "after", "reason"}
            or not isinstance(item.get("field"), str) or not item["field"].strip()
            or not isinstance(item.get("reason"), str) or not item["reason"].strip()
        ):
            raise ExperimentError("전문가 수정 diff 항목이 유효하지 않습니다")
    _reject_private_d_fields(content)

    bound: dict[str, dict] = {}
    for artifact_type, version_field, hash_field in (
        ("source_bundle", "source_bundle_version_id", "source_bundle_hash"),
        ("constraint_set", "constraint_set_version_id", "constraint_set_hash"),
        ("issue_taxonomy", "taxonomy_version_id", "taxonomy_hash"),
    ):
        artifact = get_v4_artifact(
            artifact_type=artifact_type, version_id=experiment[version_field], connection=connection
        )
        if artifact["status"] != "approved" or artifact["content_hash"] != experiment[hash_field]:
            raise ImmutableRecordConflict(f"D안의 {artifact_type} 승인 입력이 행사 결속과 다릅니다")
        bound[artifact_type] = artifact
    source_documents = bound["source_bundle"]["content_json"].get("documents")
    constraints = bound["constraint_set"]["content_json"].get("constraints")
    if not isinstance(source_documents, list) or not source_documents:
        raise ExperimentError("승인된 사전자료 묶음에 공개 가능한 문서 메타데이터가 없습니다")
    if not isinstance(constraints, list) or not constraints:
        raise ExperimentError("승인된 제약조건 묶음이 비어 있습니다")
    public_sources = []
    for item in source_documents:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) and item[key].strip()
            for key in ("document_id", "title", "content_hash")
        ):
            raise ExperimentError("사전자료 공개 메타데이터가 유효하지 않습니다")
        public_sources.append({key: item[key] for key in ("document_id", "title", "content_hash")})
    public_constraints = []
    for item in constraints:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(key), str) and item[key].strip()
            for key in ("constraint_id", "description")
        ):
            raise ExperimentError("제약조건 공개 메타데이터가 유효하지 않습니다")
        public_constraints.append({key: item[key] for key in ("constraint_id", "description")})

    taxonomy = _v4_issue_taxonomy(experiment, connection)
    if candidate_role == "primary":
        if not issue_snapshot or not issue_snapshot.get("classification_complete"):
            raise ExperimentError("primary D안에는 완료된 승인 쟁점 집계가 필요합니다")
        issue_hash = issue_snapshot["content_hash"]
        public_issue_aggregation = issue_snapshot
    else:
        issue_hash = None
        public_issue_aggregation = {
            "status": "preapproved_fallback",
            "derived_from_participant_opinions": False,
            "notice": "행사 의견 집계 전 승인된 대체 D안입니다.",
        }
    canonical_content = {
        **content,
        "source_bundle": {
            "version_id": bound["source_bundle"]["version_id"],
            "content_hash": bound["source_bundle"]["content_hash"],
            "documents": public_sources,
        },
        "admin_constraints": {
            "version_id": bound["constraint_set"]["version_id"],
            "content_hash": bound["constraint_set"]["content_hash"],
            "constraints": public_constraints,
        },
        "issue_taxonomy": taxonomy,
        "issue_aggregation": public_issue_aggregation,
    }
    ai_draft_hash = content_hash(canonical_content["ai_draft"])
    approved_d_hash = content_hash(canonical_content["approved_d"])
    expert_diff_hash = content_hash(canonical_content["expert_approval_diff"])
    input_manifest = {
        "contract_version": "aipol-v4-d-generation-input-v1",
        "candidate_role": candidate_role,
        "source_bundle_version_id": bound["source_bundle"]["version_id"],
        "source_bundle_hash": bound["source_bundle"]["content_hash"],
        "constraint_set_version_id": bound["constraint_set"]["version_id"],
        "constraint_set_hash": bound["constraint_set"]["content_hash"],
        "taxonomy_version_id": taxonomy["version_id"],
        "taxonomy_hash": taxonomy["content_hash"],
        "m2_aggregate_hash": m2_aggregate_hash,
        "issue_aggregation_hash": issue_hash,
    }
    lineage = {
        **input_manifest,
        "generation_input_hash": content_hash(input_manifest),
        "ai_draft_hash": ai_draft_hash,
        "approved_d_hash": approved_d_hash,
        "expert_diff_hash": expert_diff_hash,
    }
    return canonical_content, lineage


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
    lineage: dict | None = None,
) -> dict:
    """Canonical object covered by the human AI-candidate approval."""
    envelope = {
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
    if lineage is not None:
        envelope["v4_lineage"] = lineage
    return envelope


def _validate_ai_candidate_row(
    row: sqlite3.Row | dict,
    connection: sqlite3.Connection | None = None,
) -> str:
    value = dict(row)
    try:
        candidate_content = (
            json.loads(value["content"])
            if isinstance(value["content"], str)
            else value["content"]
        )
        lineage = None
        lineage_fields = (
            "source_bundle_version_id", "source_bundle_hash",
            "constraint_set_version_id", "constraint_set_hash",
            "taxonomy_version_id", "taxonomy_hash", "issue_aggregation_hash",
            "generation_input_hash", "ai_draft_hash", "approved_d_hash", "expert_diff_hash",
        )
        if value.get("generation_input_hash"):
            lineage = {
                "contract_version": "aipol-v4-d-generation-input-v1",
                "candidate_role": value["candidate_role"],
                "source_bundle_version_id": value["source_bundle_version_id"],
                "source_bundle_hash": value["source_bundle_hash"],
                "constraint_set_version_id": value["constraint_set_version_id"],
                "constraint_set_hash": value["constraint_set_hash"],
                "taxonomy_version_id": value["taxonomy_version_id"],
                "taxonomy_hash": value["taxonomy_hash"],
                "m2_aggregate_hash": value.get("m2_aggregate_hash"),
                "issue_aggregation_hash": value.get("issue_aggregation_hash"),
                "generation_input_hash": value["generation_input_hash"],
                "ai_draft_hash": value["ai_draft_hash"],
                "approved_d_hash": value["approved_d_hash"],
                "expert_diff_hash": value["expert_diff_hash"],
            }
        elif any(value.get(field) for field in lineage_fields):
            raise ImmutableRecordConflict("AI candidate v4 lineage is incomplete")
        if connection is not None:
            experiment = get_experiment(value["experiment_id"], connection)
            if _uses_v4_procedure(experiment) and lineage is None:
                raise ImmutableRecordConflict("v4 D안 provenance lineage가 없습니다")
            if _uses_v4_procedure(experiment):
                source_bundle = candidate_content.get("source_bundle") or {}
                constraints = candidate_content.get("admin_constraints") or {}
                taxonomy = candidate_content.get("issue_taxonomy") or {}
                issue_aggregation = candidate_content.get("issue_aggregation") or {}
                expected_bindings = (
                    (source_bundle, "source_bundle_version_id", "source_bundle_hash"),
                    (constraints, "constraint_set_version_id", "constraint_set_hash"),
                    (taxonomy, "taxonomy_version_id", "taxonomy_hash"),
                )
                if any(
                    embedded.get("version_id") != value[version_field]
                    or embedded.get("content_hash") != value[hash_field]
                    for embedded, version_field, hash_field in expected_bindings
                ):
                    raise ImmutableRecordConflict("v4 D안 공개 입력 결속이 provenance와 다릅니다")
                if not hmac.compare_digest(
                    content_hash(candidate_content.get("ai_draft")), str(value["ai_draft_hash"])
                ):
                    raise ImmutableRecordConflict("v4 D안 AI 초안 hash가 다릅니다")
                if not hmac.compare_digest(
                    content_hash(candidate_content.get("approved_d")), str(value["approved_d_hash"])
                ):
                    raise ImmutableRecordConflict("v4 D안 전문가 승인본 hash가 다릅니다")
                if not hmac.compare_digest(
                    content_hash(candidate_content.get("expert_approval_diff")),
                    str(value["expert_diff_hash"]),
                ):
                    raise ImmutableRecordConflict("v4 D안 전문가 수정 diff hash가 다릅니다")
                if value["candidate_role"] == "primary":
                    if issue_aggregation.get("content_hash") != value["issue_aggregation_hash"]:
                        raise ImmutableRecordConflict("v4 D안 쟁점 집계 hash가 다릅니다")
                elif (
                    value.get("issue_aggregation_hash") is not None
                    or issue_aggregation.get("status") != "preapproved_fallback"
                    or issue_aggregation.get("derived_from_participant_opinions") is not False
                ):
                    raise ImmutableRecordConflict("v4 fallback D안의 사전승인 표지가 다릅니다")
                input_manifest = {
                    key: lineage[key]
                    for key in (
                        "contract_version", "candidate_role",
                        "source_bundle_version_id", "source_bundle_hash",
                        "constraint_set_version_id", "constraint_set_hash",
                        "taxonomy_version_id", "taxonomy_hash", "m2_aggregate_hash",
                        "issue_aggregation_hash",
                    )
                }
                if not hmac.compare_digest(
                    content_hash(input_manifest), str(value["generation_input_hash"])
                ):
                    raise ImmutableRecordConflict("v4 D안 생성 입력 manifest hash가 다릅니다")
        envelope = _ai_candidate_approval_envelope(
            candidate_role=value["candidate_role"],
            artifact_id=value["artifact_id"],
            artifact_version=value["artifact_version"],
            content=candidate_content,
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
            lineage=lineage,
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


def _v4_ai_candidate_provenance(value: dict) -> dict | None:
    if not value.get("generation_input_hash"):
        return None
    return {
        "contract_version": "aipol-v4-d-generation-input-v1",
        "source_bundle_version_id": value["source_bundle_version_id"],
        "source_bundle_hash": value["source_bundle_hash"],
        "constraint_set_version_id": value["constraint_set_version_id"],
        "constraint_set_hash": value["constraint_set_hash"],
        "taxonomy_version_id": value["taxonomy_version_id"],
        "taxonomy_hash": value["taxonomy_hash"],
        "m2_aggregate_hash": value["m2_aggregate_hash"],
        "issue_aggregation_hash": value["issue_aggregation_hash"],
        "generation_input_hash": value["generation_input_hash"],
        "ai_draft_hash": value["ai_draft_hash"],
        "approved_d_hash": value["approved_d_hash"],
        "expert_diff_hash": value["expert_diff_hash"],
        "model": value["model"],
        "deployment": value["deployment"],
        "prompt_version": value["prompt_version"],
        "generated_at": value["generated_at"],
        "approval_id": value["approval_id"],
        "approved_by": value["approved_by"],
        "approved_at": value["approved_at"],
    }


_V4_AI_CANDIDATE_LINEAGE_FIELDS = (
    "source_bundle_version_id",
    "source_bundle_hash",
    "constraint_set_version_id",
    "constraint_set_hash",
    "taxonomy_version_id",
    "taxonomy_hash",
    "issue_aggregation_hash",
    "generation_input_hash",
    "ai_draft_hash",
    "approved_d_hash",
    "expert_diff_hash",
)


def _omit_empty_v4_ai_candidate_lineage(value: dict) -> None:
    """Keep the exact legacy public contract stable for pre-v4 candidates."""
    if value.get("generation_input_hash"):
        return
    for field in _V4_AI_CANDIDATE_LINEAGE_FIELDS:
        value.pop(field, None)


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
    issue_snapshot = None
    with db._conn() as read_connection:
        initial_experiment = get_experiment(experiment_id, read_connection)
    if _uses_v4_procedure(initial_experiment) and candidate_role == "primary":
        issue_snapshot = v4_issue_aggregation_snapshot(experiment_id)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        lineage = None
        if _uses_v4_procedure(experiment):
            content, lineage = _prepare_v4_ai_candidate_content(
                experiment=experiment,
                candidate_role=candidate_role,
                content=content,
                m2_aggregate_hash=m2_aggregate_hash,
                issue_snapshot=issue_snapshot,
                connection=connection,
            )
        elif _uses_current_procedure(experiment):
            if set(content) != {"title", "body", "lever_values"}:
                raise ExperimentError("v3 AI 후보는 title/body/lever_values 계약을 유지합니다")
            _validate_policy_lever_values(experiment, content.get("lever_values"), label="D")
        elif set(content) != {"title", "body"}:
            raise ExperimentError("v1/v2 AI 후보는 기존 title/body 계약을 유지합니다")
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
            lineage=lineage,
        )
        digest = content_hash(envelope)
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
                "evidence_refs,m2_aggregate_hash,source_bundle_version_id,source_bundle_hash,"
                "constraint_set_version_id,constraint_set_hash,taxonomy_version_id,taxonomy_hash,"
                "issue_aggregation_hash,generation_input_hash,ai_draft_hash,approved_d_hash,"
                "expert_diff_hash,approval_id,approved_by,approved_at,registered_by,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    _id("ac"), experiment_id, candidate_role, artifact_id, artifact_version,
                    _json(content), digest, model, deployment, prompt_version, generated_at,
                    _json(evidence_refs), m2_aggregate_hash,
                    lineage.get("source_bundle_version_id") if lineage else None,
                    lineage.get("source_bundle_hash") if lineage else None,
                    lineage.get("constraint_set_version_id") if lineage else None,
                    lineage.get("constraint_set_hash") if lineage else None,
                    lineage.get("taxonomy_version_id") if lineage else None,
                    lineage.get("taxonomy_hash") if lineage else None,
                    lineage.get("issue_aggregation_hash") if lineage else None,
                    lineage.get("generation_input_hash") if lineage else None,
                    lineage.get("ai_draft_hash") if lineage else None,
                    lineage.get("approved_d_hash") if lineage else None,
                    lineage.get("expert_diff_hash") if lineage else None,
                    approval_id, approved_by, approved_at,
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
    provenance = _v4_ai_candidate_provenance(result)
    if provenance:
        result["provenance"] = provenance
    else:
        _omit_empty_v4_ai_candidate_lineage(result)
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
            provenance = _v4_ai_candidate_provenance(result)
            if provenance:
                result["provenance"] = provenance
            else:
                _omit_empty_v4_ai_candidate_lineage(result)
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
        experiment.get("event_kind") == "review"
        and
        isinstance(manifest, dict)
        and manifest.get("status") == "frozen"
        and experiment.get("collection_enabled") is False
    )


def _procedure_version(experiment: dict) -> str:
    return str((experiment.get("procedure_config") or {}).get("version") or "")


def _uses_deliberation_procedure(experiment: dict) -> bool:
    """Return true for the preserved v2 flow and the current v3 flow."""
    return _procedure_version(experiment) in {
        V2_PROCEDURE_CONFIG["version"],
        PROCEDURE_CONFIG["version"],
    }


def _uses_current_procedure(experiment: dict) -> bool:
    """Return true only for newly created v3 experiments."""
    return _procedure_version(experiment) == PROCEDURE_CONFIG["version"]


def _uses_v4_procedure(experiment: dict) -> bool:
    """Return true only for the canonical short v4 procedure."""
    return _procedure_version(experiment) == V4_PROCEDURE_CONFIG["version"]


def _validate_policy_lever_values(experiment: dict, lever_values: object, *, label: str) -> None:
    expected = {
        key
        for option in experiment["policy_options"]
        for key in (option.get("lever_values") or {})
    }
    if not isinstance(lever_values, dict) or not expected or set(lever_values) != expected:
        raise ExperimentError(f"{label}는 A/B/C 비교표와 동일한 정책 항목을 모두 포함해야 합니다")
    for key, value in lever_values.items():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ExperimentError(f"{label} 정책 항목 {key}의 값 형식이 유효하지 않습니다")
        if isinstance(value, str) and not value.strip():
            raise ExperimentError(f"{label} 정책 항목 {key}의 값이 비어 있습니다")

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
    result = {
        "artifact_id": artifact.artifact_id,
        "artifact_version": artifact.artifact_version,
        "content_hash": artifact.content_hash,
        "content": json.loads(value["content"]),
        "approval_id": artifact.approval.approval_id,
        "approved_by": artifact.approval.approved_by,
        "approved_at": artifact.approval.approved_at,
        "fallback_used": artifact.fallback_used,
    }
    if stage == "E2":
        provenance = _v4_ai_candidate_provenance(value)
        if provenance:
            result["provenance"] = provenance
    return result


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
        event_kind = experiment.get("event_kind", "legacy_unclassified")
        is_v4 = experiment.get("procedure_config", {}).get("version") == V4_PROCEDURE_CONFIG["version"]
        if event_kind == "legacy_unclassified":
            raise CollectionDisabled("event kind이 확인되지 않은 기존 행은 등록할 수 없습니다")
        if is_v4 and (
            (event_kind == "live" and participant_type_enum is not ParticipantType.REAL)
            or (event_kind == "review" and participant_type_enum is not ParticipantType.SYNTHETIC)
        ):
            raise CollectionDisabled("live 이벤트는 real, review 이벤트는 synthetic 참가자만 허용합니다")
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
                "SELECT r.*,p.stage,p.state_revision,p.token_hash,p.experiment_id AS participant_experiment_id "
                "FROM aipol_registration_nonces r JOIN aipol_participants p ON p.id=r.participant_id "
                "JOIN aipol_experiments e ON e.id=p.experiment_id AND e.id=r.experiment_id "
                "WHERE r.experiment_id=? AND (r.nonce_hash=? OR r.idempotency_key=?)",
                (experiment_id, nonce_hash, idempotency_key),
            ).fetchall()
            if previous:
                if (
                    len(previous) != 1
                    or previous[0]["participant_experiment_id"] != experiment_id
                    or previous[0]["nonce_hash"] != nonce_hash
                    or previous[0]["idempotency_key"] != idempotency_key
                ):
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


_RESULT_AFTER_MEASUREMENT = {"M1": "T3", "M2": "T5", "M3": "T10"}
_RESULT_NEXT_STAGE = {"T3": "E1a", "T5": "E2", "T10": "complete"}
_PUBLIC_RESULT_RULES_VERSION = "aipol-public-results-v1"
_PUBLIC_RESULT_K = 5
_PUBLIC_RESULT_MIN_COHORT = 10


def _public_result_min_cohort() -> int:
    if (
        os.environ.get("EVENT_ENV", "production").strip().lower() == "development"
        and os.environ.get("AIPOL_TEST_ALLOW_SMALL_PUBLIC_COHORT", "false").strip().lower() == "true"
    ):
        return 1
    return _PUBLIC_RESULT_MIN_COHORT


def _suppress_public_counts(values: list[int], *, k: int = _PUBLIC_RESULT_K) -> list[int | None]:
    released: list[int | None] = [value if value >= k else None for value in values]
    suppressed = [index for index, value in enumerate(released) if value is None]
    visible = [index for index, value in enumerate(released) if value is not None]
    if len(suppressed) == 1 and visible:
        secondary = min(visible, key=lambda index: (released[index], index))
        released[secondary] = None
    return released


def _privacy_protect_public_result(snapshot: dict, *, cohort_size: int) -> dict:
    """Suppress real-cohort cells before the immutable public hash is created."""
    minimum_cohort = _public_result_min_cohort()
    if cohort_size < minimum_cohort:
        raise PublicResultError(
            f"public result cohort must contain at least {minimum_cohort} participants"
        )
    protected = json.loads(json.dumps(snapshot))

    # All T5/T10 tables describe the same people.  Per-table suppression is
    # unsafe because visible choice, stance and transition margins can be
    # subtracted from one another to recover a rare cell.  If any positive
    # cell in the release unit is below k, suppress every quantitative cell in
    # that snapshot as a single unit.
    def has_rare_positive(value, key="") -> bool:
        if isinstance(value, dict):
            return any(has_rare_positive(item, child_key) for child_key, item in value.items())
        if isinstance(value, list):
            if key == "cells":
                return any(
                    isinstance(cell, int) and not isinstance(cell, bool) and 0 < cell < _PUBLIC_RESULT_K
                    for row in value for cell in row
                )
            return any(has_rare_positive(item, key) for item in value)
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and (key == "count" or key.endswith("_count"))
            and 0 < value < _PUBLIC_RESULT_K
        )

    release_suppressed = has_rare_positive(protected)

    def suppress_release_unit(value, key=""):
        if isinstance(value, dict):
            return {
                child_key: suppress_release_unit(item, child_key)
                for child_key, item in value.items()
            }
        if isinstance(value, list):
            if key == "cells":
                return [[None for _ in row] for row in value]
            return [suppress_release_unit(item, key) for item in value]
        if key == "rate" or key == "denominator" or key == "count" or key.endswith("_count"):
            return None
        return value

    if release_suppressed:
        protected = suppress_release_unit(protected)
        protected["privacy_rules"] = {
            "k": _PUBLIC_RESULT_K,
            "minimum_cohort": minimum_cohort,
            "suppressed_value": None,
            "secondary_suppression": True,
            "shared_release_unit": True,
            "release_suppressed": True,
        }
        unhashed = {key: value for key, value in protected.items() if key != "content_hash"}
        protected["content_hash"] = canonical_content_hash(unhashed)
        return protected

    # With no rare positive cell, retain the normal primary/secondary masking
    # for structural zeroes and a lone hidden cell.
    for key in ("m1", "m2", "m3"):
        distribution = protected.get(key)
        if not isinstance(distribution, dict):
            continue
        options = distribution.get("options") or []
        counts = _suppress_public_counts([int(item["count"]) for item in options])
        for item, count in zip(options, counts, strict=True):
            item["count"] = count
            item["rate"] = None if count is None else item["rate"]
        for field in ("abstention_count", "attrition_count"):
            if isinstance(distribution.get(field), int) and distribution[field] < _PUBLIC_RESULT_K:
                distribution[field] = None
    for key in ("m2_stances", "m3_stances"):
        for distribution in protected.get(key) or []:
            stances = distribution.get("stances") or []
            counts = _suppress_public_counts([int(item["count"]) for item in stances])
            for item, count in zip(stances, counts, strict=True):
                item["count"] = count
                item["rate"] = None if count is None else item["rate"]
            for field in ("abstention_count", "attrition_count"):
                if isinstance(distribution.get(field), int) and distribution[field] < _PUBLIC_RESULT_K:
                    distribution[field] = None
    for key in ("m1_to_m2", "m2_to_m3", "m1_to_m3"):
        matrix = protected.get(key)
        if not isinstance(matrix, dict):
            continue
        cells = matrix.get("cells") or []
        flat = [int(value) for row in cells for value in row]
        suppressed = _suppress_public_counts(flat)
        width = len(cells[0]) if cells else 0
        matrix["cells"] = [
            suppressed[index:index + width]
            for index in range(0, len(suppressed), width)
        ] if width else []
        for field in ("paired_abstention_count", "paired_attrition_count"):
            if isinstance(matrix.get(field), int) and matrix[field] < _PUBLIC_RESULT_K:
                matrix[field] = None
    protected["privacy_rules"] = {
        "k": _PUBLIC_RESULT_K,
        "minimum_cohort": minimum_cohort,
        "suppressed_value": None,
        "secondary_suppression": True,
        "shared_release_unit": True,
        "release_suppressed": release_suppressed,
    }
    unhashed = {key: value for key, value in protected.items() if key != "content_hash"}
    protected["content_hash"] = canonical_content_hash(unhashed)
    return protected


def _parse_result_cutoff(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ExperimentError("결과 cutoff는 시간대가 포함된 ISO-8601이어야 합니다") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExperimentError("결과 cutoff에는 시간대가 필요합니다")
    parsed = parsed.astimezone(timezone.utc)
    if parsed > datetime.now(timezone.utc):
        raise ExperimentError("미래 cutoff로 결과를 공개할 수 없습니다")
    return parsed


def _result_scope(participant: dict) -> str:
    return "real-cohort" if participant["participant_type"] == "real" else participant["id"]


def _result_snapshot_row(
    connection: sqlite3.Connection,
    experiment_id: str,
    result_stage: str,
    participant: dict,
) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM aipol_public_result_snapshots WHERE experiment_id=? "
        "AND result_stage=? AND participant_type=? AND scope_key=?",
        (experiment_id, result_stage, participant["participant_type"], _result_scope(participant)),
    ).fetchone()


def _validated_public_result(row: sqlite3.Row) -> dict:
    snapshot = json.loads(row["snapshot_json"])
    if not isinstance(snapshot, dict):
        raise ImmutableRecordConflict("공개 결과 snapshot 형식이 손상되었습니다")
    claimed = snapshot.get("content_hash")
    unhashed = {key: value for key, value in snapshot.items() if key != "content_hash"}
    calculated = canonical_content_hash(unhashed)
    if (
        claimed != row["content_hash"]
        or calculated != row["content_hash"]
        or snapshot.get("stage") != row["result_stage"]
        or snapshot.get("cutoff") != row["cutoff_at"]
        or snapshot.get("rules_version") != row["rules_version"]
    ):
        raise ImmutableRecordConflict("공개 결과 snapshot과 동결 해시가 일치하지 않습니다")
    rendered = json.dumps(snapshot, ensure_ascii=False).lower()
    if "participant_key" in rendered or '"reason"' in rendered:
        raise ImmutableRecordConflict("공개 결과에 비공개 원문 필드가 포함되었습니다")
    return snapshot


def _build_public_result(
    connection: sqlite3.Connection,
    experiment_id: str,
    result_stage: str,
    participant_type: str,
    scope_key: str,
    cutoff: datetime,
    rules_version: str,
) -> dict:
    experiment_row = connection.execute(
        "SELECT procedure_config FROM aipol_experiments WHERE id=?",
        (experiment_id,),
    ).fetchone()
    if experiment_row is None:
        raise ExperimentError("공개 결과를 만들 행사를 찾을 수 없습니다")
    procedure_config = json.loads(experiment_row["procedure_config"] or "{}")
    m3_options = (
        V4_M3_OPTIONS
        if procedure_config.get("version") == V4_PROCEDURE_CONFIG["version"]
        else None
    )
    participant_sql = (
        "SELECT id FROM aipol_participants WHERE experiment_id=? AND participant_type=? "
        "AND created_at<=?" + (" AND id=?" if participant_type == "synthetic" else "")
    )
    params: tuple[object, ...] = (experiment_id, participant_type, cutoff.timestamp())
    if participant_type == "synthetic":
        params += (scope_key,)
    participant_rows = connection.execute(participant_sql, params).fetchall()
    eligible = tuple(row["id"] for row in participant_rows)
    if not eligible:
        raise ExperimentError("cutoff 안에 공개할 참가자 cohort가 없습니다")
    placeholders = ",".join("?" for _ in eligible)
    measurements = [
        DeidentifiedMeasurement(
            row["participant_id"], row["measurement_id"], row["choice"],
            datetime.fromisoformat(row["submitted_at"]),
        )
        for row in connection.execute(
            f"SELECT participant_id,measurement_id,choice,submitted_at FROM aipol_measurements "
            f"WHERE participant_id IN ({placeholders})",
            eligible,
        ).fetchall()
    ]
    assessments: list[DeidentifiedOptionAssessment] = []
    if result_stage in ("T5", "T10"):
        measurement_id = "M2" if result_stage == "T5" else "M3"
        if result_stage == "T10" and m3_options is not None:
            # v4 records only the selected option's stance.  Rejections for
            # unselected options must never be inferred or manufactured.
            assessments = [
                DeidentifiedOptionAssessment(
                    row["participant_id"], measurement_id, row["choice"], row["stance"],
                    datetime.fromisoformat(row["submitted_at"]),
                )
                for row in connection.execute(
                    f"SELECT participant_id,choice,stance,submitted_at FROM aipol_measurements "
                    f"WHERE participant_id IN ({placeholders}) AND measurement_id='M3' "
                    "AND choice IS NOT NULL AND stance IS NOT NULL",
                    eligible,
                ).fetchall()
            ]
        else:
            table = (
                "aipol_m2_option_assessments"
                if result_stage == "T5"
                else "aipol_m3_option_assessments"
            )
            assessments = [
                DeidentifiedOptionAssessment(
                    row["participant_id"], measurement_id, row["option_id"], row["stance"],
                    datetime.fromisoformat(row["created_at"]),
                )
                for row in connection.execute(
                    f"SELECT participant_id,option_id,stance,created_at FROM {table} "
                    f"WHERE participant_id IN ({placeholders})",
                    eligible,
                ).fetchall()
            ]
    try:
        if result_stage == "T3":
            snapshot = build_t3_m1_results(
                measurements, eligible_participants=eligible, cutoff=cutoff,
                rules_version=rules_version,
            ).to_dict()
        elif result_stage == "T5":
            snapshot = build_t5_results(
                measurements, assessments, eligible_participants=eligible, cutoff=cutoff,
                rules_version=rules_version,
            ).to_dict()
        elif result_stage == "T10":
            kwargs = {
                "eligible_participants": eligible,
                "cutoff": cutoff,
                "rules_version": rules_version,
            }
            if m3_options is not None:
                kwargs["m3_options"] = m3_options
            snapshot = build_t10_results(measurements, assessments, **kwargs).to_dict()
        else:
            raise ExperimentError("공개 결과 단계는 T3, T5, T10 중 하나여야 합니다")
        return (
            snapshot
            if participant_type == ParticipantType.SYNTHETIC.value
            else _privacy_protect_public_result(snapshot, cohort_size=len(eligible))
        )
    except PublicResultError as exc:
        raise ExperimentError(str(exc)) from exc


def _insert_public_result_snapshot(
    connection: sqlite3.Connection,
    experiment: dict,
    *,
    result_stage: str,
    participant_type: str,
    scope_key: str,
    cutoff: datetime,
    rules_version: str,
    released_by: str,
) -> sqlite3.Row:
    cutoff_text = cutoff.isoformat().replace("+00:00", "Z")
    snapshot = _build_public_result(
        connection, experiment["id"], result_stage, participant_type, scope_key,
        cutoff, rules_version,
    )
    if snapshot["cutoff"] != cutoff_text:
        raise ImmutableRecordConflict("공개 결과 cutoff 직렬화가 일치하지 않습니다")
    try:
        connection.execute(
            "INSERT INTO aipol_public_result_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                _id("prs"), experiment["id"], result_stage, participant_type, scope_key,
                cutoff_text, rules_version, _json(snapshot), snapshot["content_hash"],
                released_by, datetime.now(timezone.utc).isoformat(),
            ),
        )
    except sqlite3.IntegrityError as exc:
        raced = _result_snapshot_row(
            connection, experiment["id"], result_stage,
            {"participant_type": participant_type, "id": scope_key},
        )
        if raced is None:
            raise
        if _validated_public_result(raced) != snapshot:
            raise ImmutableRecordConflict("동시에 다른 공개 결과 snapshot이 동결되었습니다") from exc
    row = _result_snapshot_row(
        connection, experiment["id"], result_stage,
        {"participant_type": participant_type, "id": scope_key},
    )
    assert row is not None
    return row


def release_public_result(
    experiment_id: str,
    result_stage: str,
    *,
    cutoff_at: str,
    rules_version: str,
    released_by: str,
) -> dict:
    """Freeze one real-cohort result. A release is immutable and never inferred."""
    if result_stage not in _RESULT_NEXT_STAGE:
        raise ExperimentError("공개 결과 단계는 T3, T5, T10 중 하나여야 합니다")
    if not released_by.strip():
        raise ExperimentError("결과 공개자가 필요합니다")
    if rules_version != _PUBLIC_RESULT_RULES_VERSION:
        raise ExperimentError(
            f"rules_version은 서버 정본 {_PUBLIC_RESULT_RULES_VERSION}과 일치해야 합니다"
        )
    cutoff = _parse_result_cutoff(cutoff_at)
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment = get_experiment(experiment_id, connection)
        if experiment["procedure_config"].get("version") not in {
            PROCEDURE_CONFIG["version"], V4_PROCEDURE_CONFIG["version"],
        }:
            raise ExperimentError("공개 결과 단계는 v3 또는 v4 절차에서만 지원합니다")
        if experiment["registration_open"]:
            raise ExperimentError("실제 cohort 등록 마감 뒤에만 결과를 공개할 수 있습니다")
        existing = connection.execute(
            "SELECT * FROM aipol_public_result_snapshots WHERE experiment_id=? "
            "AND result_stage=? AND participant_type='real' AND scope_key='real-cohort'",
            (experiment_id, result_stage),
        ).fetchone()
        if existing:
            snapshot = _validated_public_result(existing)
            if (
                existing["cutoff_at"] != cutoff.isoformat().replace("+00:00", "Z")
                or existing["rules_version"] != rules_version
            ):
                raise ImmutableRecordConflict("이미 다른 계약으로 공개 결과가 동결되었습니다")
            return snapshot
        required_measurement = {"T3": "M1", "T5": "M2", "T10": "M3"}[result_stage]
        cohort = connection.execute(
            "SELECT p.id,p.created_at,p.stage,m.submitted_at FROM aipol_participants p "
            "LEFT JOIN aipol_measurements m ON m.participant_id=p.id AND m.measurement_id=? "
            "WHERE p.experiment_id=? AND p.participant_type='real'",
            (required_measurement, experiment_id),
        ).fetchall()
        if not cohort:
            raise ExperimentError("공개할 실제 참가자 cohort가 없습니다")
        if any(float(row["created_at"]) > cutoff.timestamp() for row in cohort):
            raise ExperimentError("cutoff가 등록 마감 cohort 전체를 포함하지 않습니다")
        pending = [
            row for row in cohort
            if row["stage"] != "withdrawn" and row["submitted_at"] is None
        ]
        if pending:
            raise ExperimentError(
                f"{required_measurement}가 고정되지 않은 실제 참가자가 {len(pending)}명 있습니다"
            )
        after_cutoff = [
            row for row in cohort
            if row["submitted_at"] is not None
            and datetime.fromisoformat(row["submitted_at"]).astimezone(timezone.utc) > cutoff
        ]
        if after_cutoff:
            raise ExperimentError(
                f"cutoff 이후의 {required_measurement} 응답이 {len(after_cutoff)}명 있어 결과를 공개할 수 없습니다"
            )
        if result_stage in ("T5", "T10"):
            barrier = connection.execute(
                "SELECT finalized_at FROM aipol_m2_finalizations WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
            if not barrier:
                raise ExperimentError("M2 cohort-finalized barrier 뒤에만 T5/T10을 공개할 수 있습니다")
            if datetime.fromisoformat(barrier["finalized_at"]).astimezone(timezone.utc) > cutoff:
                raise ExperimentError("cutoff가 M2 cohort-finalized barrier보다 빠릅니다")
        row = _insert_public_result_snapshot(
            connection, experiment, result_stage=result_stage, participant_type="real",
            scope_key="real-cohort", cutoff=cutoff, rules_version=rules_version,
            released_by=released_by,
        )
        return _validated_public_result(row)


def _pending_public_result(
    connection: sqlite3.Connection,
    experiment: dict,
    participant: dict,
) -> tuple[str, sqlite3.Row | None] | None:
    if experiment["procedure_config"].get("version") not in {
        PROCEDURE_CONFIG["version"], V4_PROCEDURE_CONFIG["version"],
    }:
        return None
    if participant["stage"] == ExperimentStage.WITHDRAWN.value:
        return None
    latest = connection.execute(
        "SELECT measurement_id FROM aipol_measurements WHERE participant_id=? "
        "ORDER BY state_revision DESC LIMIT 1",
        (participant["id"],),
    ).fetchone()
    if not latest:
        return None
    result_stage = _RESULT_AFTER_MEASUREMENT[latest["measurement_id"]]
    row = _result_snapshot_row(connection, experiment["id"], result_stage, participant)
    if row is None and _synthetic_review_mode(experiment, participant):
        row = _insert_public_result_snapshot(
            connection, experiment, result_stage=result_stage, participant_type="synthetic",
            scope_key=participant["id"], cutoff=datetime.now(timezone.utc),
            rules_version=_PUBLIC_RESULT_RULES_VERSION, released_by="system:synthetic-review",
        )
    if row is not None:
        acknowledged = connection.execute(
            "SELECT 1 FROM aipol_public_result_acks WHERE participant_id=? AND snapshot_id=?",
            (participant["id"], row["id"]),
        ).fetchone()
        if acknowledged:
            return None
    return result_stage, row


def _require_public_result_ack(
    connection: sqlite3.Connection,
    experiment: dict,
    participant: dict,
) -> None:
    pending = _pending_public_result(connection, experiment, participant)
    if pending is None:
        return
    if pending[1] is None:
        raise CollectionDisabled(f"{pending[0]} 공개 결과가 아직 동결·공개되지 않았습니다")
    raise InvalidTransition(f"{pending[0]} 공개 결과를 확인한 뒤 다음 단계로 진행해야 합니다")


def acknowledge_public_result(
    experiment_id: str,
    participant_token: str,
    result_stage: str,
    *,
    content_hash_value: str,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    if result_stage not in _RESULT_NEXT_STAGE or not idempotency_key:
        raise ExperimentError("유효한 공개 결과 단계와 멱등 키가 필요합니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment, participant = _load_participant(connection, experiment_id, participant_token)
        existing = connection.execute(
            "SELECT a.*,s.result_stage FROM aipol_public_result_acks a "
            "JOIN aipol_public_result_snapshots s ON s.id=a.snapshot_id "
            "WHERE a.participant_id=? AND a.idempotency_key=?",
            (participant["id"], idempotency_key),
        ).fetchone()
        if existing:
            if (
                existing["result_stage"] != result_stage
                or existing["content_hash"] != content_hash_value
                or existing["state_revision"] != expected_revision
            ):
                raise IdempotencyConflict("같은 idempotency_key에 다른 결과 확인이 제출되었습니다")
            return {
                "stage": _RESULT_NEXT_STAGE[result_stage],
                "state_revision": expected_revision,
                "acknowledged_result": result_stage,
            }
        if participant["state_revision"] != expected_revision:
            raise StateRevisionConflict("현재 state_revision과 결과 확인 요청이 다릅니다")
        pending = _pending_public_result(connection, experiment, participant)
        if pending is None or pending[0] != result_stage or pending[1] is None:
            raise InvalidTransition("현재 확인할 수 있는 공개 결과가 없습니다")
        row = pending[1]
        snapshot = _validated_public_result(row)
        if content_hash_value != snapshot["content_hash"]:
            raise ImmutableRecordConflict("표시된 공개 결과 해시와 확인 요청이 다릅니다")
        connection.execute(
            "INSERT INTO aipol_public_result_acks VALUES(?,?,?,?,?,?,?)",
            (
                _id("pra"), participant["id"], row["id"], content_hash_value,
                datetime.now(timezone.utc).isoformat(), expected_revision, idempotency_key,
            ),
        )
        return {
            "stage": _RESULT_NEXT_STAGE[result_stage],
            "state_revision": expected_revision,
            "acknowledged_result": result_stage,
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
        if experiment.get("procedure_config", {}).get("version") == V4_PROCEDURE_CONFIG["version"]:
            result["event_kind"] = experiment.get("event_kind", "legacy_unclassified")
            for field in (
                "source_bundle_version_id", "constraint_set_version_id", "taxonomy_version_id",
                "source_bundle_hash", "constraint_set_hash", "taxonomy_hash",
            ):
                result[field] = experiment.get(field)
            demographics_recorded = bool(connection.execute(
                "SELECT 1 FROM aipol_demographics WHERE participant_id=?",
                (participant["id"],),
            ).fetchone())
            # Labels intentionally remain the approved opaque IDs: this API
            # must not invent numeric/default demographic values.
            demographic_options = {
                "gender_band_id": [{"id": value, "label": value} for value in GENDER_BAND_IDS],
                "age_band_id": [{"id": value, "label": value} for value in AGE_BAND_IDS],
                "monthly_personal_income_band_id": [
                    {"id": value, "label": value} for value in MONTHLY_PERSONAL_INCOME_BAND_IDS
                ],
            }
            result["demographics"] = {
                "required": True,
                "recorded": demographics_recorded,
                "rules_version": RESEARCH_SEGMENT_RULES_VERSION,
                "options": demographic_options,
            }
            result["demographics_required"] = True
            result["demographics_recorded"] = demographics_recorded
        synthetic_review = _synthetic_review_mode(experiment, participant)
        if synthetic_review:
            result["synthetic_review"] = True
        pending_result = _pending_public_result(connection, experiment, participant)
        if pending_result is not None:
            result_stage, snapshot_row = pending_result
            result["stage"] = result_stage
            result["title"] = {
                "T3": "1차 선택 결과",
                "T5": "1·2차 선택 비교 결과",
                "T10": (
                    "3차 선택과 변화 결과"
                    if _uses_v4_procedure(experiment)
                    else "최종 선택과 변화 결과"
                ),
            }[result_stage]
            result["acknowledgement_required"] = True
            if snapshot_row is None:
                result["waiting_for_result_release"] = True
            else:
                result["public_result"] = _validated_public_result(snapshot_row)
            return result
        if stage is ExperimentStage.CONSENT:
            result["consent_version"] = experiment["consent_version"]
            result["consent_text"] = experiment["consent_text"]
        elif stage is ExperimentStage.E0:
            result["policy_options"] = [
                _public_policy_option(option) for option in experiment["policy_options"]
            ]
            result["content_hash"] = content_hash(experiment["policy_options"])
            result["title"] = "정책전문가 A·B·C안 비교"
            result["acknowledgement_required"] = True
        elif stage is ExperimentStage.E1A:
            if (
                not synthetic_review
                and experiment["procedure_config"].get("version") == PROCEDURE_CONFIG["version"]
            ):
                research_profile = connection.execute(
                    "SELECT 1 FROM aipol_research_profiles WHERE participant_id=?",
                    (participant["id"],),
                ).fetchone()
                if not research_profile:
                    result["research_profile_required"] = True
                    result["research_profile_contract"] = _research_profile_public_contract()
                    return result
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
            if stage is ExperimentStage.M1 and _uses_v4_procedure(experiment):
                result["issue_taxonomy"] = _v4_issue_taxonomy(experiment, connection)
                result["issue_interests_required"] = True
            options = {option["policy_option_id"]: option for option in experiment["policy_options"]}
            result["policy_options"] = [
                _public_policy_option(options[key]) for key in result["option_order"]
            ]
            if stage is ExperimentStage.M2 and (
                _uses_current_procedure(experiment) or _uses_v4_procedure(experiment)
            ):
                result["structured_option_assessment"] = True
            if stage is ExperimentStage.M3:
                artifact_stage = "E3" if _uses_deliberation_procedure(experiment) else "E2"
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
                        include_content=(artifact_stage == "E3"),
                    )
                )
                if ai:
                    if _uses_current_procedure(experiment):
                        final_content = ai.get("content") or {}
                        final_levers = final_content.get("lever_values")
                        if not isinstance(final_levers, dict) or not final_levers:
                            raise ImmutableRecordConflict("승인된 D′ 비교 항목이 비어 있습니다")
                        result["policy_options"].append({
                            "policy_option_id": "D_PRIME",
                            "label": _public_policy_option_label("D_PRIME"),
                            "policy_version": ai["artifact_version"],
                            "lever_values": final_levers,
                            "artifact_id": ai["artifact_id"],
                            "artifact_version": ai["artifact_version"],
                            "content_hash": ai["content_hash"],
                        })
                        result["option_order"] = [*result["option_order"], "D_PRIME"]
                        result["structured_final_assessment"] = True
                    elif _uses_v4_procedure(experiment):
                        final_content = ai.get("content") or {}
                        final_levers = final_content.get("lever_values")
                        if not isinstance(final_levers, dict) or not final_levers:
                            raise ImmutableRecordConflict("승인된 D안 비교 항목이 비어 있습니다")
                        result["policy_options"].append({
                            "policy_option_id": "D",
                            "label": "D안",
                            "policy_version": ai["artifact_version"],
                            "lever_values": final_levers,
                            "artifact_id": ai["artifact_id"],
                            "artifact_version": ai["artifact_version"],
                            "content_hash": ai["content_hash"],
                        })
                        result["option_order"] = [*result["option_order"], "D"]
                    else:
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
                if (
                    participant["participant_type"] == "real"
                    and experiment["procedure_config"].get("version") == PROCEDURE_CONFIG["version"]
                ):
                    snapshot = _validated_t6_snapshot(connection, experiment_id, required=True)
                    acknowledged = connection.execute(
                        "SELECT 1 FROM aipol_t6_acks WHERE participant_id=? AND snapshot_id=?",
                        (participant["id"], snapshot["snapshot_id"]),
                    ).fetchone()
                    if not acknowledged:
                        result["interstitial_stage"] = "T6"
                        result["result_snapshot"] = snapshot
                        result["acknowledgement_required"] = True
                        return result
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
            result["public_audience_discussion"] = {
                "participant_text_collection": False,
                "facilitator_selected_input": True,
                "acknowledgement_required": True,
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


def acknowledge_policy_options(
    experiment_id: str,
    participant_token: str,
    *,
    content_hash_value: str,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    payload = {"operation": "policy_options_ack", "content_hash": content_hash_value}

    def apply(connection, experiment, participant, session):
        if experiment.get("procedure_config", {}).get("version") == V4_PROCEDURE_CONFIG["version"]:
            recorded = connection.execute(
                "SELECT 1 FROM aipol_demographics WHERE participant_id=?",
                (participant["id"],),
            ).fetchone()
            if not recorded:
                raise ExperimentError("E0 정책 확인 전에 인구통계 band를 먼저 기록해야 합니다")
        record = session.acknowledge_policy_options(
            participant["pseudonym"], content_hash_value=content_hash_value,
            expected_revision=expected_revision, idempotency_key=idempotency_key,
        )
        connection.execute(
            "INSERT INTO aipol_policy_option_acks VALUES(?,?,?,?,?,?)",
            (
                _id("poa"), participant["id"], record.content_hash,
                record.acknowledged_at.isoformat(), record.state_revision,
                record.idempotency_key,
            ),
        )
        return {"stage": ExperimentStage.M1.value, "state_revision": record.state_revision}

    return _write_action(experiment_id, participant_token, idempotency_key, payload, apply)


GENDER_BAND_IDS = ("female", "male", "non_binary", "no_answer")


def record_demographics(
    experiment_id: str,
    participant_token: str,
    *,
    gender_band_id: str,
    age_band_id: str,
    monthly_personal_income_band_id: str,
    expected_revision: int,
    idempotency_key: str,
    rules_version: str = RESEARCH_SEGMENT_RULES_VERSION,
) -> dict:
    """Record v4 band-only demographics exactly once, before the E0 ack."""
    if not idempotency_key or rules_version != RESEARCH_SEGMENT_RULES_VERSION:
        raise ExperimentError("인구통계 규칙 버전 또는 멱등 키가 유효하지 않습니다")
    if gender_band_id not in GENDER_BAND_IDS:
        raise ExperimentError("gender band가 허용 목록에 없습니다")
    if age_band_id not in AGE_BAND_IDS or monthly_personal_income_band_id not in MONTHLY_PERSONAL_INCOME_BAND_IDS:
        raise ExperimentError("age/income은 승인된 band ID만 허용합니다")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        experiment, participant = _load_participant(connection, experiment_id, participant_token)
        if experiment.get("procedure_config", {}).get("version") != V4_PROCEDURE_CONFIG["version"]:
            raise ExperimentError("인구통계 receipt는 v4 이벤트에서만 사용할 수 있습니다")
        if participant["participant_type"] not in {"real", "synthetic"}:
            raise ExperimentError("참가자 유형이 유효하지 않습니다")
        if participant["stage"] != ExperimentStage.E0.value or participant["state_revision"] != expected_revision:
            raise StateRevisionConflict("E0 단계와 state_revision이 인구통계 기록 요청과 다릅니다")
        existing = connection.execute(
            "SELECT * FROM aipol_demographics WHERE participant_id=?", (participant["id"],)
        ).fetchone()
        if existing:
            same_record = (
                existing["idempotency_key"] == idempotency_key
                and existing["gender_band_id"] == gender_band_id
                and existing["age_band_id"] == age_band_id
                and existing["monthly_personal_income_band_id"] == monthly_personal_income_band_id
                and existing["rules_version"] == rules_version
                and existing["state_revision"] == expected_revision
            )
            if not same_record:
                raise IdempotencyConflict("인구통계는 최초 기록 이후 변경할 수 없습니다")
            return {"recorded": True, "required": True, "state_revision": expected_revision}
        connection.execute(
            "INSERT INTO aipol_demographics(id,participant_id,gender_band_id,age_band_id,"
            "monthly_personal_income_band_id,rules_version,recorded_at,state_revision,idempotency_key) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (_id("demo"), participant["id"], gender_band_id, age_band_id,
             monthly_personal_income_band_id, rules_version,
             datetime.now(timezone.utc).isoformat(), expected_revision, idempotency_key),
        )
        return {"recorded": True, "required": True, "state_revision": expected_revision}


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
        _require_public_result_ack(connection, experiment, participant)
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
        is_current_procedure = (
            experiment["procedure_config"].get("version") == PROCEDURE_CONFIG["version"]
        )
        if stage == "E1a" and not synthetic_review and is_current_procedure:
            if not connection.execute(
                "SELECT 1 FROM aipol_research_profiles WHERE participant_id=?",
                (participant["id"],),
            ).fetchone():
                raise CollectionDisabled(
                    "연구 구간 저장 여부를 결정한 뒤에만 개인 비교를 완료할 수 있습니다"
                )
        if stage == "E2" and not synthetic_review and is_current_procedure:
            snapshot = _validated_t6_snapshot(connection, experiment_id, required=True)
            if not connection.execute(
                "SELECT 1 FROM aipol_t6_acks WHERE participant_id=? AND snapshot_id=?",
                (participant["id"], snapshot["snapshot_id"]),
            ).fetchone():
                raise InvalidTransition("T6 조건별 분석 결과를 확인한 뒤 D를 볼 수 있습니다")
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


def acknowledge_audience_discussion(
    experiment_id: str,
    participant_token: str,
    *,
    expected_revision: int,
    idempotency_key: str,
) -> dict:
    """Record only that a participant observed the public audience discussion."""
    payload = {"operation": "audience_discussion_ack"}

    def apply(connection, experiment, participant, session):
        if not _uses_deliberation_procedure(experiment):
            raise InvalidTransition("공개 청중 의견 확인은 v2/v3 절차에서만 제출할 수 있습니다")
        record = session.acknowledge_audience_discussion(
            participant["pseudonym"],
            expected_revision=expected_revision, idempotency_key=idempotency_key,
        )
        connection.execute(
            "INSERT INTO aipol_audience_discussion_acks VALUES(?,?,?,?,?)",
            (
                _id("ada"), participant["id"], record.acknowledged_at.isoformat(),
                record.state_revision, record.idempotency_key,
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
    option_assessments: dict | None = None,
    issue_interests: list[str] | None = None,
) -> dict:
    payload = {
        "operation": "measurement", "measurement_id": measurement_id, "choice": choice,
        "reason": reason, "confidence": confidence, "secondary_evaluation": secondary_evaluation,
        "stance": stance,
        "option_assessments": option_assessments,
        "issue_interests": issue_interests,
    }
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, int)):
        raise ExperimentError("confidence는 1~5 정수 또는 null이어야 합니다")

    def apply(connection, experiment, participant, session):
        is_current_procedure = _uses_current_procedure(experiment)
        is_v4_procedure = _uses_v4_procedure(experiment)
        uses_structured_m2 = is_current_procedure or is_v4_procedure
        selected_issue_codes: list[str] | None = None
        taxonomy: dict | None = None
        if is_v4_procedure and measurement_id == "M1":
            taxonomy = _v4_issue_taxonomy(experiment, connection)
            if (
                not isinstance(issue_interests, list)
                or not issue_interests
                or any(not isinstance(value, str) or not value for value in issue_interests)
                or len(set(issue_interests)) != len(issue_interests)
            ):
                raise ExperimentError("1차 선택에서는 관심 쟁점을 하나 이상 중복 없이 선택해야 합니다")
            allowed_codes = [topic["code"] for topic in taxonomy["topics"]]
            if any(value not in allowed_codes for value in issue_interests):
                raise ExperimentError("승인된 taxonomy에 없는 관심 쟁점입니다")
            if taxonomy["classification_mode"] == "single_label" and len(issue_interests) != 1:
                raise ExperimentError("이 행사의 관심 쟁점은 하나만 선택할 수 있습니다")
            selected_issue_codes = [code for code in allowed_codes if code in issue_interests]
        elif issue_interests is not None:
            raise ExperimentError("관심 쟁점은 v4 1차 선택에서만 제출할 수 있습니다")
        if secondary_evaluation is not None and (
            measurement_id != "M3" or is_current_procedure or is_v4_procedure
        ):
            raise ExperimentError("D/D′ 별도 평가는 M3에서만 제출할 수 있습니다")
        record = session.submit_measurement(
            participant["pseudonym"], measurement_id, choice=choice, reason=reason,
            confidence=confidence, expected_revision=expected_revision,
            idempotency_key=idempotency_key, stance=stance,
            option_assessments=option_assessments,
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
        if selected_issue_codes is not None and taxonomy is not None:
            connection.execute(
                "INSERT INTO aipol_m1_issue_interests VALUES(?,?,?,?,?,?,?,?)",
                (
                    _id("m1i"), participant["id"], taxonomy["version_id"],
                    taxonomy["content_hash"], _json(selected_issue_codes),
                    record.submitted_at.isoformat(), record.state_revision,
                    record.idempotency_key,
                ),
            )
        if (
            (measurement_id == "M2" and uses_structured_m2)
            or (measurement_id == "M3" and is_current_procedure)
        ):
            assert option_assessments is not None
            assessment_table = (
                "aipol_m2_option_assessments"
                if measurement_id == "M2"
                else "aipol_m3_option_assessments"
            )
            assessment_id_prefix = "m2a" if measurement_id == "M2" else "m3a"
            connection.executemany(
                f"INSERT INTO {assessment_table} VALUES(?,?,?,?,?,?)",
                [
                    (
                        _id(assessment_id_prefix), participant["id"], option_id,
                        assessment["stance"], assessment["reason"],
                        record.submitted_at.isoformat(),
                    )
                    for option_id, assessment in option_assessments.items()
                ],
            )
        if secondary_evaluation is not None:
            if _uses_deliberation_procedure(experiment):
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
        policy_options_content_hash=content_hash(experiment["policy_options"]),
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
    policy_options_ack = connection.execute(
        "SELECT * FROM aipol_policy_option_acks WHERE participant_id=?", (participant["id"],)
    ).fetchone()
    if policy_options_ack:
        events.append((policy_options_ack["state_revision"], "policy_options_ack", dict(policy_options_ack)))
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
    discussion_ack = connection.execute(
        "SELECT * FROM aipol_audience_discussion_acks WHERE participant_id=?", (participant["id"],)
    ).fetchone()
    if discussion_ack:
        events.append((discussion_ack["state_revision"], "audience_discussion_ack", dict(discussion_ack)))
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
        elif event_type == "policy_options_ack":
            session.acknowledge_policy_options(
                participant["pseudonym"], content_hash_value=value["content_hash"],
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
            assessments = None
            if (
                (
                    value["measurement_id"] == "M2"
                    and (
                        _uses_current_procedure(experiment)
                        or _uses_v4_procedure(experiment)
                    )
                )
                or (
                    value["measurement_id"] == "M3"
                    and _uses_current_procedure(experiment)
                )
            ):
                assessment_table = (
                    "aipol_m2_option_assessments"
                    if value["measurement_id"] == "M2"
                    else "aipol_m3_option_assessments"
                )
                assessment_rows = connection.execute(
                    f"SELECT option_id,stance,reason FROM {assessment_table} WHERE participant_id=?",
                    (participant["id"],),
                ).fetchall()
                assessments = {
                    row["option_id"]: {"stance": row["stance"], "reason": row["reason"]}
                    for row in assessment_rows
                }
            session.submit_measurement(
                participant["pseudonym"], value["measurement_id"], choice=value["choice"],
                reason=value["reason"], confidence=value["confidence"],
                expected_revision=revision - 1, idempotency_key=value["idempotency_key"],
                stance=value.get("stance"),
                option_assessments=assessments,
            )
        elif event_type == "audience_discussion_ack":
            session.acknowledge_audience_discussion(
                participant["pseudonym"], expected_revision=revision - 1,
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
        if _procedure_version(experiment) == V4_PROCEDURE_CONFIG["version"]:
            event_kind = experiment.get("event_kind", "legacy_unclassified")
            participant_type = participant.get("participant_type")
            valid_pair = (
                (event_kind == "live" and participant_type == ParticipantType.REAL.value)
                or (event_kind == "review" and participant_type == ParticipantType.SYNTHETIC.value)
            )
            if not valid_pair:
                raise CollectionDisabled(
                    "v4 event kind과 participant type 조합이 유효하지 않습니다"
                )
        previous = connection.execute(
            "SELECT request_hash,response FROM aipol_idempotency WHERE participant_id=? AND idempotency_key=?",
            (participant["id"], idempotency_key),
        ).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise IdempotencyConflict("같은 idempotency_key에 다른 payload가 제출되었습니다")
            return json.loads(previous["response"])
        if payload.get("operation") != "withdraw":
            _require_public_result_ack(connection, experiment, participant)
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
    result = {
        "artifact_id": artifact["artifact_id"],
        "artifact_version": artifact["artifact_version"],
        "content_hash": artifact["content_hash"],
        "content": artifact["content"],
        "approval_id": artifact["approval_id"],
        "approved_by": artifact["approved_by"],
        "approved_at": artifact["approved_at"],
        "fallback_used": bool(artifact["fallback_used"]),
    }
    for key in ("model", "deployment", "prompt_version", "generated_at", "evidence_refs"):
        if key in artifact:
            result[key] = artifact[key]
        elif key in artifact["content"]:
            result[key] = artifact["content"][key]
    return result


init()
