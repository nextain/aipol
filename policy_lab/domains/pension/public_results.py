"""Deterministic, deidentified public result builders for the pension experiment.

The builders in this module do not read a database, mutate records, or expose
participant-level rows.  A caller supplies the eligible deidentified keys and
records captured at or before a frozen cutoff.  Free-text reasons are
deliberately absent from every input and output type.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence


M1_M2_OPTIONS = ("A", "B", "C")
M3_OPTIONS = ("A", "B", "C", "D_PRIME")
STANCES = ("accept", "conditional", "reject")


class PublicResultError(ValueError):
    """A public result input violates the frozen aggregation contract."""


@dataclass(frozen=True)
class DeidentifiedMeasurement:
    """One deidentified choice row; ``None`` means an explicit abstention."""

    participant_key: str
    measurement_id: str
    choice: str | None
    submitted_at: datetime


@dataclass(frozen=True)
class DeidentifiedOptionAssessment:
    """One option-level stance row without a free-text reason."""

    participant_key: str
    measurement_id: str
    option_id: str
    stance: str | None
    submitted_at: datetime


@dataclass(frozen=True)
class CountRate:
    key: str
    count: int
    denominator: int
    rate: float | None


@dataclass(frozen=True)
class ChoiceDistribution:
    measurement_id: str
    eligible_count: int
    submitted_count: int
    denominator: int
    abstention_count: int
    attrition_count: int
    options: tuple[CountRate, ...]


@dataclass(frozen=True)
class StanceDistribution:
    option_id: str
    eligible_count: int
    submitted_count: int
    denominator: int
    abstention_count: int
    attrition_count: int
    stances: tuple[CountRate, ...]


@dataclass(frozen=True)
class TransitionMatrix:
    from_measurement: str
    to_measurement: str
    row_options: tuple[str, ...]
    column_options: tuple[str, ...]
    denominator: int
    from_valid_count: int
    to_valid_count: int
    paired_abstention_count: int
    paired_attrition_count: int
    cells: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class T3M1Results:
    stage: str
    cutoff: str
    rules_version: str
    m1: ChoiceDistribution
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class T5Results:
    stage: str
    cutoff: str
    rules_version: str
    m1: ChoiceDistribution
    m2: ChoiceDistribution
    m1_to_m2: TransitionMatrix
    m2_stances: tuple[StanceDistribution, ...]
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class T10Results:
    stage: str
    cutoff: str
    rules_version: str
    m3: ChoiceDistribution
    m3_stances: tuple[StanceDistribution, ...]
    m2_to_m3: TransitionMatrix
    m1_to_m3: TransitionMatrix
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def canonical_content_hash(value: object) -> str:
    """Return the SHA-256 of a canonical JSON representation."""

    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_t3_m1_results(
    measurements: Iterable[DeidentifiedMeasurement],
    *,
    eligible_participants: Iterable[str],
    cutoff: datetime,
    rules_version: str,
) -> T3M1Results:
    """Build the T3 M1 public counts and rates."""

    eligible = _eligible(eligible_participants)
    cutoff_text = _cutoff(cutoff)
    records = _measurement_index(measurements, eligible, cutoff)
    m1 = _choice_distribution(records, "M1", M1_M2_OPTIONS, eligible)
    validated_rules = _rules(rules_version)
    payload = {"stage": "T3", "cutoff": cutoff_text, "rules_version": validated_rules, "m1": asdict(m1)}
    return T3M1Results(
        stage="T3", cutoff=cutoff_text, rules_version=validated_rules, m1=m1,
        content_hash=canonical_content_hash(payload),
    )


def build_t5_results(
    measurements: Iterable[DeidentifiedMeasurement],
    assessments: Iterable[DeidentifiedOptionAssessment],
    *,
    eligible_participants: Iterable[str],
    cutoff: datetime,
    rules_version: str,
) -> T5Results:
    """Build M1/M2 comparison, paired 3x3 transitions, and M2 stances."""

    eligible = _eligible(eligible_participants)
    cutoff_text = _cutoff(cutoff)
    records = _measurement_index(measurements, eligible, cutoff)
    assessment_records = _assessment_index(assessments, eligible, cutoff)
    m1 = _choice_distribution(records, "M1", M1_M2_OPTIONS, eligible)
    m2 = _choice_distribution(records, "M2", M1_M2_OPTIONS, eligible)
    transition = _transition(
        records, "M1", "M2", M1_M2_OPTIONS, M1_M2_OPTIONS, eligible
    )
    stances = _stance_distributions(assessment_records, "M2", M1_M2_OPTIONS, eligible)
    validated_rules = _rules(rules_version)
    payload = {
        "stage": "T5", "cutoff": cutoff_text, "rules_version": validated_rules,
        "m1": asdict(m1), "m2": asdict(m2), "m1_to_m2": asdict(transition),
        "m2_stances": tuple(asdict(item) for item in stances),
    }
    return T5Results(
        stage="T5", cutoff=cutoff_text, rules_version=validated_rules, m1=m1, m2=m2,
        m1_to_m2=transition, m2_stances=stances,
        content_hash=canonical_content_hash(payload),
    )


def build_t10_results(
    measurements: Iterable[DeidentifiedMeasurement],
    assessments: Iterable[DeidentifiedOptionAssessment],
    *,
    eligible_participants: Iterable[str],
    cutoff: datetime,
    rules_version: str,
) -> T10Results:
    """Build M3 choice/stances and paired M2->M3 and M1->M3 transitions."""

    eligible = _eligible(eligible_participants)
    cutoff_text = _cutoff(cutoff)
    records = _measurement_index(measurements, eligible, cutoff)
    assessment_records = _assessment_index(assessments, eligible, cutoff)
    m3 = _choice_distribution(records, "M3", M3_OPTIONS, eligible)
    stances = _stance_distributions(assessment_records, "M3", M3_OPTIONS, eligible)
    m2_to_m3 = _transition(
        records, "M2", "M3", M1_M2_OPTIONS, M3_OPTIONS, eligible
    )
    m1_to_m3 = _transition(
        records, "M1", "M3", M1_M2_OPTIONS, M3_OPTIONS, eligible
    )
    validated_rules = _rules(rules_version)
    payload = {
        "stage": "T10", "cutoff": cutoff_text, "rules_version": validated_rules,
        "m3": asdict(m3), "m3_stances": tuple(asdict(item) for item in stances),
        "m2_to_m3": asdict(m2_to_m3), "m1_to_m3": asdict(m1_to_m3),
    }
    return T10Results(
        stage="T10", cutoff=cutoff_text, rules_version=validated_rules, m3=m3,
        m3_stances=stances, m2_to_m3=m2_to_m3, m1_to_m3=m1_to_m3,
        content_hash=canonical_content_hash(payload),
    )


def _rules(value: str) -> str:
    if not value or not value.strip():
        raise PublicResultError("rules_version must not be empty")
    return value


def _cutoff(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PublicResultError("cutoff must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _eligible(values: Iterable[str]) -> tuple[str, ...]:
    items = tuple(values)
    if any(not item for item in items):
        raise PublicResultError("eligible participant keys must not be empty")
    if len(items) != len(set(items)):
        raise PublicResultError("eligible participant keys must be unique")
    return tuple(sorted(items))


def _within_cutoff(submitted_at: datetime, cutoff: datetime) -> bool:
    if submitted_at.tzinfo is None or submitted_at.utcoffset() is None:
        raise PublicResultError("record submitted_at must include a timezone")
    return submitted_at <= cutoff


def _measurement_index(
    records: Iterable[DeidentifiedMeasurement], eligible: Sequence[str], cutoff: datetime
) -> Mapping[tuple[str, str], DeidentifiedMeasurement]:
    result: dict[tuple[str, str], DeidentifiedMeasurement] = {}
    allowed = set(eligible)
    for record in records:
        if not _within_cutoff(record.submitted_at, cutoff):
            continue
        if record.participant_key not in allowed:
            raise PublicResultError("measurement contains an ineligible participant key")
        if record.measurement_id not in {"M1", "M2", "M3"}:
            raise PublicResultError("measurement_id must be M1, M2, or M3")
        valid = M3_OPTIONS if record.measurement_id == "M3" else M1_M2_OPTIONS
        if record.choice is not None and record.choice not in valid:
            raise PublicResultError("measurement contains an invalid choice")
        key = (record.participant_key, record.measurement_id)
        if key in result:
            raise PublicResultError("duplicate measurement for participant and round")
        result[key] = record
    return result


def _assessment_index(
    records: Iterable[DeidentifiedOptionAssessment], eligible: Sequence[str], cutoff: datetime
) -> Mapping[tuple[str, str, str], DeidentifiedOptionAssessment]:
    result: dict[tuple[str, str, str], DeidentifiedOptionAssessment] = {}
    allowed = set(eligible)
    for record in records:
        if not _within_cutoff(record.submitted_at, cutoff):
            continue
        if record.participant_key not in allowed:
            raise PublicResultError("assessment contains an ineligible participant key")
        valid_options = M3_OPTIONS if record.measurement_id == "M3" else M1_M2_OPTIONS
        if record.measurement_id not in {"M2", "M3"} or record.option_id not in valid_options:
            raise PublicResultError("assessment round or option is invalid")
        if record.stance is not None and record.stance not in STANCES:
            raise PublicResultError("assessment contains an invalid stance")
        key = (record.participant_key, record.measurement_id, record.option_id)
        if key in result:
            raise PublicResultError("duplicate assessment for participant, round, and option")
        result[key] = record
    return result


def _rate(key: str, count: int, denominator: int) -> CountRate:
    return CountRate(key, count, denominator, count / denominator if denominator else None)


def _choice_distribution(
    records: Mapping[tuple[str, str], DeidentifiedMeasurement],
    measurement_id: str,
    options: Sequence[str],
    eligible: Sequence[str],
) -> ChoiceDistribution:
    submitted = [records[(key, measurement_id)] for key in eligible if (key, measurement_id) in records]
    choices = [record.choice for record in submitted if record.choice is not None]
    denominator = len(choices)
    return ChoiceDistribution(
        measurement_id=measurement_id,
        eligible_count=len(eligible),
        submitted_count=len(submitted),
        denominator=denominator,
        abstention_count=sum(record.choice is None for record in submitted),
        attrition_count=len(eligible) - len(submitted),
        options=tuple(_rate(option, choices.count(option), denominator) for option in options),
    )


def _stance_distributions(
    records: Mapping[tuple[str, str, str], DeidentifiedOptionAssessment],
    measurement_id: str,
    options: Sequence[str],
    eligible: Sequence[str],
) -> tuple[StanceDistribution, ...]:
    output = []
    for option in options:
        submitted = [
            records[(key, measurement_id, option)]
            for key in eligible if (key, measurement_id, option) in records
        ]
        stances = [record.stance for record in submitted if record.stance is not None]
        denominator = len(stances)
        output.append(StanceDistribution(
            option_id=option, eligible_count=len(eligible), submitted_count=len(submitted),
            denominator=denominator,
            abstention_count=sum(record.stance is None for record in submitted),
            attrition_count=len(eligible) - len(submitted),
            stances=tuple(_rate(stance, stances.count(stance), denominator) for stance in STANCES),
        ))
    return tuple(output)


def _transition(
    records: Mapping[tuple[str, str], DeidentifiedMeasurement],
    from_measurement: str,
    to_measurement: str,
    rows: Sequence[str],
    columns: Sequence[str],
    eligible: Sequence[str],
) -> TransitionMatrix:
    from_choices = {
        participant: record.choice for (participant, measurement), record in records.items()
        if measurement == from_measurement and record.choice is not None
    }
    to_choices = {
        participant: record.choice for (participant, measurement), record in records.items()
        if measurement == to_measurement and record.choice is not None
    }
    paired = sorted(set(from_choices) & set(to_choices))
    paired_abstentions = sum(
        key in from_choices
        and (key, to_measurement) in records
        and records[(key, to_measurement)].choice is None
        for key in eligible
    )
    paired_attrition = sum(
        key in from_choices and (key, to_measurement) not in records
        for key in eligible
    )
    cells = tuple(tuple(
        sum(from_choices[key] == row and to_choices[key] == column for key in paired)
        for column in columns
    ) for row in rows)
    return TransitionMatrix(
        from_measurement=from_measurement, to_measurement=to_measurement,
        row_options=tuple(rows), column_options=tuple(columns), denominator=len(paired),
        from_valid_count=len(from_choices), to_valid_count=len(to_choices),
        paired_abstention_count=paired_abstentions,
        paired_attrition_count=paired_attrition, cells=cells,
    )
