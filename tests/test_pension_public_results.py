from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from policy_lab.domains.pension.public_results import (
    DeidentifiedMeasurement,
    DeidentifiedOptionAssessment,
    PublicResultError,
    build_t10_results,
    build_t3_m1_results,
    build_t5_results,
    canonical_content_hash,
)


CUTOFF = datetime(2026, 8, 12, 6, 0, tzinfo=timezone.utc)
BEFORE = CUTOFF - timedelta(minutes=1)
AFTER = CUTOFF + timedelta(seconds=1)
ELIGIBLE = ("p3", "p1", "p5", "p2", "p4")


def m(participant: str, round_id: str, choice: str | None, at: datetime = BEFORE):
    return DeidentifiedMeasurement(participant, round_id, choice, at)


def a(participant: str, round_id: str, option: str, stance: str | None):
    return DeidentifiedOptionAssessment(participant, round_id, option, stance, BEFORE)


def test_t3_counts_rates_and_explicit_abstention_attrition_metadata():
    result = build_t3_m1_results(
        [m("p1", "M1", "A"), m("p2", "M1", "A"), m("p3", "M1", "C"),
         m("p4", "M1", None), m("p5", "M1", "B", AFTER)],
        eligible_participants=ELIGIBLE, cutoff=CUTOFF, rules_version="public-v1",
    )

    assert result.stage == "T3"
    assert result.cutoff == "2026-08-12T06:00:00Z"
    assert (result.m1.eligible_count, result.m1.submitted_count, result.m1.denominator) == (5, 4, 3)
    assert (result.m1.abstention_count, result.m1.attrition_count) == (1, 1)
    assert [(row.key, row.count, row.denominator, row.rate) for row in result.m1.options] == [
        ("A", 2, 3, 2 / 3), ("B", 0, 3, 0.0), ("C", 1, 3, 1 / 3),
    ]


def test_t5_has_stable_3x3_pairing_and_per_option_stance_denominators():
    measurements = [
        m("p1", "M1", "A"), m("p1", "M2", "B"),
        m("p2", "M1", "B"), m("p2", "M2", "B"),
        m("p3", "M1", "C"), m("p3", "M2", None),
        m("p4", "M1", "A"),
        m("p5", "M2", "C"),
    ]
    assessments = [
        a("p1", "M2", "A", "reject"), a("p1", "M2", "B", "accept"), a("p1", "M2", "C", "reject"),
        a("p2", "M2", "A", "reject"), a("p2", "M2", "B", "conditional"), a("p2", "M2", "C", "reject"),
        a("p3", "M2", "A", None),
    ]
    result = build_t5_results(
        reversed(measurements), reversed(assessments), eligible_participants=reversed(ELIGIBLE),
        cutoff=CUTOFF, rules_version="public-v1",
    )

    assert [row.key for row in result.m1.options] == ["A", "B", "C"]
    assert (result.m1.denominator, result.m2.denominator) == (4, 3)
    assert result.m1_to_m2.row_options == ("A", "B", "C")
    assert result.m1_to_m2.column_options == ("A", "B", "C")
    assert result.m1_to_m2.cells == ((0, 1, 0), (0, 1, 0), (0, 0, 0))
    assert (
        result.m1_to_m2.denominator,
        result.m1_to_m2.paired_abstention_count,
        result.m1_to_m2.paired_attrition_count,
    ) == (2, 1, 1)
    by_option = {item.option_id: item for item in result.m2_stances}
    assert [row.count for row in by_option["B"].stances] == [1, 1, 0]
    assert (by_option["B"].denominator, by_option["B"].attrition_count) == (2, 3)
    assert (by_option["A"].abstention_count, by_option["A"].denominator) == (1, 2)


def test_t10_outputs_final_choice_stances_and_both_stable_3x4_transitions():
    measurements = [
        m("p1", "M1", "A"), m("p1", "M2", "B"), m("p1", "M3", "D_PRIME"),
        m("p2", "M1", "B"), m("p2", "M2", "B"), m("p2", "M3", "A"),
        m("p3", "M1", "C"), m("p3", "M2", "C"), m("p3", "M3", None),
        m("p4", "M1", "A"), m("p4", "M3", "C"),
    ]
    assessments = [
        a(participant, "M3", option, "accept" if option == choice else "reject")
        for participant, choice in (("p1", "D_PRIME"), ("p2", "A"), ("p4", "C"))
        for option in ("A", "B", "C", "D_PRIME")
    ]
    result = build_t10_results(
        measurements, assessments, eligible_participants=ELIGIBLE,
        cutoff=CUTOFF, rules_version="public-v1",
    )

    assert [row.key for row in result.m3.options] == ["A", "B", "C", "D_PRIME"]
    assert [row.count for row in result.m3.options] == [1, 0, 1, 1]
    assert (result.m3.denominator, result.m3.abstention_count, result.m3.attrition_count) == (3, 1, 1)
    assert result.m2_to_m3.cells == ((0, 0, 0, 0), (1, 0, 0, 1), (0, 0, 0, 0))
    assert result.m1_to_m3.cells == ((0, 0, 1, 1), (1, 0, 0, 0), (0, 0, 0, 0))
    assert result.m2_to_m3.denominator == 2
    assert result.m1_to_m3.denominator == 3
    d_prime = result.m3_stances[-1]
    assert d_prime.option_id == "D_PRIME"
    assert [row.count for row in d_prime.stances] == [1, 0, 2]


def test_content_is_order_independent_bound_to_rules_and_contains_no_participant_or_reason():
    rows = [m("p1", "M1", "A"), m("p2", "M1", "B")]
    first = build_t3_m1_results(
        rows, eligible_participants=("p1", "p2"), cutoff=CUTOFF, rules_version="v1"
    )
    second = build_t3_m1_results(
        reversed(rows), eligible_participants=("p2", "p1"), cutoff=CUTOFF, rules_version="v1"
    )
    changed = build_t3_m1_results(
        rows, eligible_participants=("p1", "p2"), cutoff=CUTOFF, rules_version="v2"
    )

    assert first == second
    assert first.content_hash != changed.content_hash
    public = first.to_dict()
    digest_input = {key: value for key, value in public.items() if key != "content_hash"}
    assert first.content_hash == canonical_content_hash(digest_input)
    rendered = str(public).lower()
    assert "participant" not in rendered
    assert "reason" not in rendered


@pytest.mark.parametrize(
    "records, message",
    [
        ([m("p1", "M1", "A"), m("p1", "M1", "B")], "duplicate"),
        ([m("unknown", "M1", "A")], "ineligible"),
        ([m("p1", "M1", "D_PRIME")], "invalid choice"),
    ],
)
def test_invalid_measurement_inputs_fail_closed(records, message):
    with pytest.raises(PublicResultError, match=message):
        build_t3_m1_results(
            records, eligible_participants=("p1",), cutoff=CUTOFF, rules_version="v1"
        )


def test_zero_denominators_use_null_rate_and_naive_dates_or_empty_rules_fail_closed():
    empty = build_t3_m1_results(
        [], eligible_participants=("p1",), cutoff=CUTOFF, rules_version="v1"
    )
    assert empty.m1.denominator == 0
    assert all(row.rate is None for row in empty.m1.options)
    with pytest.raises(PublicResultError, match="timezone"):
        build_t3_m1_results([], eligible_participants=(), cutoff=datetime(2026, 8, 12), rules_version="v1")
    with pytest.raises(PublicResultError, match="rules_version"):
        build_t3_m1_results([], eligible_participants=(), cutoff=CUTOFF, rules_version=" ")


def test_invalid_assessment_is_rejected_and_input_types_have_no_reason_field():
    assert "reason" not in DeidentifiedMeasurement.__dataclass_fields__
    assert "reason" not in DeidentifiedOptionAssessment.__dataclass_fields__
    bad = [a("p1", "M3", "D_PRIME", "maybe")]
    with pytest.raises(PublicResultError, match="invalid stance"):
        build_t10_results(
            [], bad, eligible_participants=("p1",), cutoff=CUTOFF, rules_version="v1"
        )
