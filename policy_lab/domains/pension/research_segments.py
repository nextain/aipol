"""Privacy-preserving research profile projections for the pension domain.

This module is deliberately independent of persistence and transport code.  It
accepts only pre-banded research profiles, validates a small closed schema, and
returns deterministic aggregate counts.  Participant identifiers, exact
values, free-text reasons, and marginal totals are not part of the contract.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
from typing import Final


RULES_VERSION: Final = "pension-research-segments-v1"
DEFAULT_K: Final = 5
DEFAULT_ROW_MIN: Final = 10

# Band IDs are opaque contract values.  Callers must band exact values before
# invoking this module; this module never receives or derives exact values.
AGE_BAND_IDS: Final = (
    "age_20_29",
    "age_30_39",
    "age_40_49",
    "age_50_59",
    "age_60_69",
    "age_70_plus",
)
MONTHLY_PERSONAL_INCOME_BAND_IDS: Final = (
    "monthly_personal_income_lt_200",
    "monthly_personal_income_200_399",
    "monthly_personal_income_400_599",
    "monthly_personal_income_600_799",
    "monthly_personal_income_800_plus",
)
EXPECTED_CONTRIBUTION_YEARS_BAND_IDS: Final = (
    "expected_contribution_years_lt_10",
    "expected_contribution_years_10_19",
    "expected_contribution_years_20_29",
    "expected_contribution_years_30_39",
    "expected_contribution_years_40_plus",
)
EXPECTED_RETIREMENT_AGE_BAND_IDS: Final = (
    "expected_retirement_age_le_59",
    "expected_retirement_age_60_64",
    "expected_retirement_age_65_67",
    "expected_retirement_age_68_plus",
)

PROFILE_FIELDS: Final = (
    "age_band_id",
    "monthly_personal_income_band_id",
    "expected_contribution_years_band_id",
    "expected_retirement_age_band_id",
)
OPTION_IDS: Final = ("A", "B", "C")
STANCE_IDS: Final = ("accept", "conditional", "reject")

# These codes describe topics, not a participant's words.  Adding or changing
# a code is a rules-version change because it changes the released table.
APPROVED_REASON_TOPIC_CODES: Final = (
    "benefit_adequacy",
    "contribution_burden",
    "fiscal_sustainability",
    "intergenerational_fairness",
    "retirement_timing",
    "trust_and_governance",
)

_ALLOWED_BANDS: Final = {
    "age_band_id": frozenset(AGE_BAND_IDS),
    "monthly_personal_income_band_id": frozenset(MONTHLY_PERSONAL_INCOME_BAND_IDS),
    "expected_contribution_years_band_id": frozenset(EXPECTED_CONTRIBUTION_YEARS_BAND_IDS),
    "expected_retirement_age_band_id": frozenset(EXPECTED_RETIREMENT_AGE_BAND_IDS),
}


class ResearchSegmentError(ValueError):
    """Raised when input could expose raw data or violates the closed contract."""


def _closed_keys(value: Mapping[str, object], allowed: set[str], label: str) -> None:
    actual = set(value)
    if actual != allowed:
        missing = sorted(allowed - actual)
        unexpected = sorted(actual - allowed)
        raise ResearchSegmentError(
            f"{label} must contain exactly {sorted(allowed)!r}; "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )


def validate_research_profile(profile: Mapping[str, object]) -> tuple[str, str, str, str]:
    """Validate and canonicalize an already banded research profile.

    A closed schema is intentional: fields such as ``age``, ``income``, or an
    exact expected year cannot be silently retained alongside the bands.
    """
    if not isinstance(profile, Mapping):
        raise ResearchSegmentError("profile must be a mapping of fixed band IDs")
    _closed_keys(profile, set(PROFILE_FIELDS), "profile")

    canonical: list[str] = []
    for field in PROFILE_FIELDS:
        value = profile[field]
        if not isinstance(value, str) or value not in _ALLOWED_BANDS[field]:
            raise ResearchSegmentError(
                f"{field} must be one of {sorted(_ALLOWED_BANDS[field])!r}; "
                "exact raw values are not accepted"
            )
        canonical.append(value)
    return tuple(canonical)  # type: ignore[return-value]


def _validate_topic_codes(
    value: object,
    approved: frozenset[str],
    *,
    option_id: str,
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ResearchSegmentError(
            f"stances.{option_id}.reason_topic_codes must be a sequence"
        )
    codes = tuple(value)
    if any(not isinstance(code, str) for code in codes):
        raise ResearchSegmentError("reason topic codes must be strings")
    if len(codes) != len(set(codes)):
        raise ResearchSegmentError("duplicate reason topic codes are not accepted")
    unknown = sorted(set(codes) - approved)
    if unknown:
        raise ResearchSegmentError(f"unapproved reason topic codes: {unknown!r}")
    return tuple(sorted(codes))


def _validate_response(
    response: Mapping[str, object], approved: frozenset[str]
) -> tuple[tuple[str, str, str, str], dict[str, tuple[str, tuple[str, ...]]]]:
    if not isinstance(response, Mapping):
        raise ResearchSegmentError("each response must be a mapping")
    _closed_keys(response, {"profile", "stances"}, "response")
    profile = validate_research_profile(response["profile"])  # type: ignore[arg-type]

    stances = response["stances"]
    if not isinstance(stances, Mapping):
        raise ResearchSegmentError("stances must be a mapping")
    _closed_keys(stances, set(OPTION_IDS), "stances")

    canonical: dict[str, tuple[str, tuple[str, ...]]] = {}
    for option_id in OPTION_IDS:
        assessment = stances[option_id]
        if not isinstance(assessment, Mapping):
            raise ResearchSegmentError(f"stances.{option_id} must be a mapping")
        _closed_keys(
            assessment,
            {"stance", "reason_topic_codes"},
            f"stances.{option_id}",
        )
        stance = assessment["stance"]
        if not isinstance(stance, str) or stance not in STANCE_IDS:
            raise ResearchSegmentError(
                f"stances.{option_id}.stance must be one of {list(STANCE_IDS)!r}"
            )
        topics = _validate_topic_codes(
            assessment["reason_topic_codes"], approved, option_id=option_id
        )
        canonical[option_id] = (stance, topics)
    return profile, canonical


def _suppress_counts(
    counts: Mapping[str, int], ordered_keys: Sequence[str], k: int
) -> dict[str, int | None]:
    """Apply primary and deterministic secondary cell suppression.

    Counts from zero through ``k - 1`` are represented by ``None``.  When that
    leaves exactly one suppressed cell, the smallest visible cell is also
    suppressed (ties follow ``ordered_keys``), preventing recovery if a total
    is known from another source.
    """
    released: dict[str, int | None] = {
        key: count if (count := counts.get(key, 0)) >= k else None
        for key in ordered_keys
    }
    suppressed = [key for key, count in released.items() if count is None]
    visible = [key for key, count in released.items() if count is not None]
    if len(suppressed) == 1 and visible:
        secondary = min(visible, key=lambda key: (released[key], ordered_keys.index(key)))
        released[secondary] = None
    return released


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_research_segments(
    responses: Iterable[Mapping[str, object]],
    *,
    k: int = DEFAULT_K,
    row_min: int = DEFAULT_ROW_MIN,
    approved_reason_topic_codes: Iterable[str] = APPROVED_REASON_TOPIC_CODES,
) -> dict[str, object]:
    """Return a deterministic k-anonymous stance projection for options A/B/C.

    A row is a unique combination of the four approved profile bands.  Rows
    with fewer than ``row_min`` responses are omitted.  No input count, row
    total, option total, column total, or suppressed-row count is released.
    Reasons are released only as counts of approved topic codes and follow the
    same primary/secondary suppression rule as stance cells.
    """
    if isinstance(k, bool) or not isinstance(k, int) or k < 2:
        raise ResearchSegmentError("k must be an integer of at least 2")
    if isinstance(row_min, bool) or not isinstance(row_min, int) or row_min < k:
        raise ResearchSegmentError("row_min must be an integer greater than or equal to k")

    if isinstance(approved_reason_topic_codes, (str, bytes)):
        raise ResearchSegmentError("approved reason topic codes must be an iterable of codes")
    approved_values = tuple(approved_reason_topic_codes)
    if not approved_values or any(
        not isinstance(code, str) or not code for code in approved_values
    ):
        raise ResearchSegmentError("approved reason topic codes must be non-empty strings")
    approved_tuple = tuple(sorted(approved_values))
    if len(approved_tuple) != len(set(approved_tuple)):
        raise ResearchSegmentError("approved reason topic codes must be unique")
    approved = frozenset(approved_tuple)

    rows: dict[
        tuple[str, str, str, str],
        list[dict[str, tuple[str, tuple[str, ...]]]],
    ] = defaultdict(list)
    for response in responses:
        profile, stances = _validate_response(response, approved)
        rows[profile].append(stances)

    segments: list[dict[str, object]] = []
    for profile in sorted(rows):
        members = rows[profile]
        if len(members) < row_min:
            continue

        segment_stance_counts = {
            option_id: Counter(member[option_id][0] for member in members)
            for option_id in OPTION_IDS
        }
        segment_reason_counts = {
            option_id: Counter(
                topic for member in members for topic in member[option_id][1]
            )
            for option_id in OPTION_IDS
        }
        # Treat the three option tables as one release.  Suppressing cells in
        # each table independently permits subtraction attacks across the
        # shared row.  Omit the complete segment whenever any positive stance
        # or topic cell is below k.
        if any(
            0 < count < k
            for counts in (*segment_stance_counts.values(), *segment_reason_counts.values())
            for count in counts.values()
        ):
            continue

        options: dict[str, object] = {}
        for option_id in OPTION_IDS:
            stance_counts = segment_stance_counts[option_id]
            reason_counts = segment_reason_counts[option_id]
            options[option_id] = {
                "stance_counts": _suppress_counts(stance_counts, STANCE_IDS, k),
                "reason_topic_counts": _suppress_counts(
                    reason_counts, approved_tuple, k
                ),
            }

        segments.append(
            {
                "profile": dict(zip(PROFILE_FIELDS, profile, strict=True)),
                "options": options,
            }
        )

    payload: dict[str, object] = {
        "rules_version": RULES_VERSION,
        "privacy_rules": {
            "k": k,
            "row_min": row_min,
            "suppressed_value": None,
            "secondary_suppression": True,
            "totals_released": False,
            "approved_reason_topic_codes": list(approved_tuple),
        },
        "segments": segments,
    }
    return {**payload, "content_hash": _canonical_hash(payload)}


__all__ = [
    "AGE_BAND_IDS",
    "APPROVED_REASON_TOPIC_CODES",
    "DEFAULT_K",
    "DEFAULT_ROW_MIN",
    "EXPECTED_CONTRIBUTION_YEARS_BAND_IDS",
    "EXPECTED_RETIREMENT_AGE_BAND_IDS",
    "MONTHLY_PERSONAL_INCOME_BAND_IDS",
    "OPTION_IDS",
    "PROFILE_FIELDS",
    "RULES_VERSION",
    "ResearchSegmentError",
    "STANCE_IDS",
    "project_research_segments",
    "validate_research_profile",
]
