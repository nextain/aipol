from __future__ import annotations

import copy
import re

import pytest

from policy_lab.domains.pension.research_segments import (
    AGE_BAND_IDS,
    EXPECTED_CONTRIBUTION_YEARS_BAND_IDS,
    EXPECTED_RETIREMENT_AGE_BAND_IDS,
    MONTHLY_PERSONAL_INCOME_BAND_IDS,
    RULES_VERSION,
    ResearchSegmentError,
    project_research_segments,
)


def _response(
    *,
    age: str = AGE_BAND_IDS[0],
    a: str = "accept",
    b: str = "conditional",
    c: str = "reject",
    a_topics: tuple[str, ...] = (),
) -> dict:
    return {
        "profile": {
            "age_band_id": age,
            "monthly_personal_income_band_id": MONTHLY_PERSONAL_INCOME_BAND_IDS[0],
            "expected_contribution_years_band_id": EXPECTED_CONTRIBUTION_YEARS_BAND_IDS[0],
            "expected_retirement_age_band_id": EXPECTED_RETIREMENT_AGE_BAND_IDS[0],
        },
        "stances": {
            "A": {"stance": a, "reason_topic_codes": list(a_topics)},
            "B": {"stance": b, "reason_topic_codes": []},
            "C": {"stance": c, "reason_topic_codes": []},
        },
    }


def test_exact_values_and_free_text_reasons_are_rejected() -> None:
    exact_age = _response()
    exact_age["profile"]["age_band_id"] = 37
    with pytest.raises(ResearchSegmentError, match="exact raw values"):
        project_research_segments([exact_age])

    extra_raw_income = _response()
    extra_raw_income["profile"]["monthly_personal_income"] = 3_250_000
    with pytest.raises(ResearchSegmentError, match="unexpected"):
        project_research_segments([extra_raw_income])

    free_text = _response()
    free_text["stances"]["A"]["reason"] = "나의 구체적인 사정"
    with pytest.raises(ResearchSegmentError, match="unexpected"):
        project_research_segments([free_text])


def test_fixed_band_contract_excludes_out_of_scope_and_unknown_bands() -> None:
    assert AGE_BAND_IDS == (
        "age_20_29", "age_30_39", "age_40_49", "age_50_59", "age_60_69", "age_70_plus"
    )
    assert MONTHLY_PERSONAL_INCOME_BAND_IDS[-2:] == (
        "monthly_personal_income_600_799", "monthly_personal_income_800_plus"
    )
    assert EXPECTED_CONTRIBUTION_YEARS_BAND_IDS[-2:] == (
        "expected_contribution_years_30_39", "expected_contribution_years_40_plus"
    )
    assert EXPECTED_RETIREMENT_AGE_BAND_IDS == (
        "expected_retirement_age_le_59", "expected_retirement_age_60_64",
        "expected_retirement_age_65_67", "expected_retirement_age_68_plus"
    )
    assert not any("not_" in band for band in (
        *AGE_BAND_IDS,
        *MONTHLY_PERSONAL_INCOME_BAND_IDS,
        *EXPECTED_CONTRIBUTION_YEARS_BAND_IDS,
        *EXPECTED_RETIREMENT_AGE_BAND_IDS,
    ))


def test_only_preapproved_unique_topic_codes_are_accepted() -> None:
    unknown = _response(a_topics=("unapproved_topic",))
    with pytest.raises(ResearchSegmentError, match="unapproved"):
        project_research_segments([unknown])

    duplicate = _response(a_topics=("fiscal_sustainability", "fiscal_sustainability"))
    with pytest.raises(ResearchSegmentError, match="duplicate"):
        project_research_segments([duplicate])

    with pytest.raises(ResearchSegmentError, match="iterable of codes"):
        project_research_segments([], approved_reason_topic_codes="not-a-code-list")


def test_small_rows_are_omitted_without_releasing_any_totals() -> None:
    output = project_research_segments([_response() for _ in range(9)])
    assert output["segments"] == []
    serialized = repr(output).lower()
    assert "row_total" not in serialized
    assert "column_total" not in serialized
    assert "input_count" not in serialized
    assert "suppressed_row" not in serialized


def test_primary_and_secondary_suppression_prevent_single_cell_inversion() -> None:
    responses = [
        *(_response(a="accept") for _ in range(5)),
        *(_response(a="conditional") for _ in range(5)),
    ]
    counts = project_research_segments(responses)["segments"][0]["options"]["A"][
        "stance_counts"
    ]
    # reject=0 is primarily suppressed; one of the two visible tied cells is
    # secondarily suppressed using the stable stance order.
    assert counts == {"accept": None, "conditional": 5, "reject": None}


def test_reason_topic_counts_use_the_same_k_and_secondary_rule() -> None:
    responses = [
        *(
            _response(a_topics=("fiscal_sustainability",))
            for _ in range(5)
        ),
        *(
            _response(a_topics=("contribution_burden",))
            for _ in range(5)
        ),
    ]
    reasons = project_research_segments(
        responses,
        approved_reason_topic_codes=(
            "contribution_burden",
            "fiscal_sustainability",
            "retirement_timing",
        ),
    )["segments"][0]["options"]["A"]["reason_topic_counts"]
    assert reasons == {
        "contribution_burden": None,
        "fiscal_sustainability": 5,
        "retirement_timing": None,
    }


def test_cross_option_difference_attack_omits_the_complete_segment() -> None:
    responses = [
        *(_response(a="accept", b="reject", c="reject") for _ in range(5)),
        *(_response(a="conditional", b="reject", c="reject") for _ in range(5)),
        *(_response(a="reject", b="accept", c="reject") for _ in range(2)),
        *(_response(a="reject", b="reject", c="accept") for _ in range(3)),
    ]
    # Publishing each option independently reveals the B-selected group as
    # row-size minus B.reject (=2).  The whole shared row must stay private.
    assert project_research_segments(responses)["segments"] == []


def test_projection_and_hash_are_deterministic_and_input_is_not_mutated() -> None:
    responses = [
        *(_response(age=AGE_BAND_IDS[1], a_topics=("benefit_adequacy",)) for _ in range(10)),
        *(_response(age=AGE_BAND_IDS[0], a="reject") for _ in range(10)),
    ]
    original = copy.deepcopy(responses)
    forward = project_research_segments(responses)
    reverse = project_research_segments(reversed(responses))

    assert forward == reverse
    assert responses == original
    assert forward["rules_version"] == RULES_VERSION
    assert re.fullmatch(r"[0-9a-f]{64}", forward["content_hash"])


@pytest.mark.parametrize(
    ("k", "row_min"),
    [(1, 10), (True, 10), (5, 4), (5, False)],
)
def test_invalid_privacy_thresholds_fail_closed(k: object, row_min: object) -> None:
    with pytest.raises(ResearchSegmentError):
        project_research_segments([], k=k, row_min=row_min)  # type: ignore[arg-type]
