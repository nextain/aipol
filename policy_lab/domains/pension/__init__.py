"""연금 도메인 — policy-lab 첫 레퍼런스 구현.

대상 행사: 한국정책학회 하계학술대회 "연금개혁-AI 정책실험"(2026-08-12).
명세: ``domains/pension/spec.md``.
"""
from __future__ import annotations

from .experiment import (
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
    MeasurementRecord,
    MeasurementSpec,
    ParticipantType,
    PensionExperimentSession,
    PolicyOptionDefinition,
    StateRevisionConflict,
)
from .plugin import PensionDomain

__all__ = [
    "ArtifactApproval",
    "ArtifactKind",
    "CollectionDisabled",
    "ExperimentArtifact",
    "ExperimentError",
    "ExperimentStage",
    "FreezeApproval",
    "FreezeManifest",
    "IdempotencyConflict",
    "ImmutableRecordConflict",
    "MeasurementRecord",
    "MeasurementSpec",
    "ParticipantType",
    "PensionDomain",
    "PensionExperimentSession",
    "PolicyOptionDefinition",
    "StateRevisionConflict",
]
