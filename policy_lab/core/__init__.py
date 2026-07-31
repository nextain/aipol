"""policy-lab 도메인 중립 코어.

프로토콜(§5)·방어장치(§6)·오케스트레이션은 도메인과 무관하게 공유된다.
도메인(연금·기후·주거 …)은 ``DomainPlugin`` 으로 갈아끼운다.
"""
from __future__ import annotations

from .levers import FixedVariable, Lever, PolicyOption
from .evidence import Evidence, EvidenceStore
from .impact import Direction, ImpactModel, ImpactResult
from .deliberation import (
    Actor,
    DeliberationProtocol,
    Segment,
    Stage,
    StageType,
    VoteRound,
    mind_change,
)
from .provenance import ProvenanceLog, ProvenanceRecord
from .guards import (
    GuardViolation,
    HumanGate,
    MeasurementPurpose,
    assert_ab_separation,
    assert_declared_purpose,
    assert_not_opinion_claim,
    assert_within_whitelist,
    reject_single_number,
)
from .prompts import Prompt
from .protocols import standard_deliberation
from .plugin import DomainPlugin

__all__ = [
    "FixedVariable",
    "Lever",
    "PolicyOption",
    "Evidence",
    "EvidenceStore",
    "Direction",
    "ImpactModel",
    "ImpactResult",
    "Actor",
    "DeliberationProtocol",
    "Segment",
    "Stage",
    "StageType",
    "VoteRound",
    "mind_change",
    "ProvenanceLog",
    "ProvenanceRecord",
    "GuardViolation",
    "HumanGate",
    "MeasurementPurpose",
    "assert_ab_separation",
    "assert_declared_purpose",
    "assert_not_opinion_claim",
    "assert_within_whitelist",
    "reject_single_number",
    "Prompt",
    "standard_deliberation",
    "DomainPlugin",
]
