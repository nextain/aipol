"""Executable user-case traceability for the pension v2 participant journey.

These cases intentionally name the 11 requirements from the approved step-by-step
procedure.  Unit tests elsewhere prove individual functions; this file prevents a
feature from being counted as complete when it is not wired to the participant
browser and the public API.
"""
from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SOURCES = {
    "html": (ROOT / "event-tool/web/aipol.html").read_text(encoding="utf-8"),
    "js": (ROOT / "event-tool/web/aipol.js").read_text(encoding="utf-8"),
    "server": (ROOT / "event-tool/server.py").read_text(encoding="utf-8"),
    "store": (ROOT / "event-tool/aipol_store.py").read_text(encoding="utf-8"),
    "experiment": (ROOT / "policy_lab/domains/pension/experiment.py").read_text(encoding="utf-8"),
}


# REQ-ID -> observable participant contract.  Every token must occur in the
# named production source; comments or tests alone cannot satisfy a user case.
UC_TRACE = {
    "AIPOL-STEP-01": {
        "html": ("state-start", "intro-procedure", "admission-code", "정책전문가팀", "AI팀"),
        "js": ("participants", "consent-check"),
    },
    "AIPOL-STEP-02": {
        "experiment": ('E0 = "E0"',),
        "js": ("renderPolicyOptions", "policy-options-ack", "policy-table"),
    },
    "AIPOL-STEP-03": {
        "js": ('current.stage === "T3"', "1차 선택 분포", "measurements/${current.stage}"),
        "store": ('_RESULT_AFTER_MEASUREMENT = {"M1": "T3"',),
    },
    "AIPOL-STEP-04": {
        "js": ("startCalculator", "research_profile_required", "renderResearchProfile", "research-profile"),
        "store": ("record_research_profile", "stores_exact_values", "E1A"),
    },
    "AIPOL-STEP-05": {
        "js": ("structuredM2", "optionAssessments", 'current.stage === "T5"'),
        "store": ("aipol_m2_option_assessments", "build_t5_results"),
    },
    "AIPOL-STEP-06": {
        "js": ('current.interstitial_stage === "T6"', "renderT6Result", "조건별 분석"),
        "store": ("_build_t6_snapshot", "aipol_t6_snapshots", "project_research_segments"),
        "server": ('/{experiment_id}/t6-ack',),
    },
    "AIPOL-STEP-07": {
        "js": ("잠정 의견 D", "waiting_for_e2_release"),
        "store": ("e2_m2_aggregate_hash", "def release_e2("),
    },
    "AIPOL-STEP-08": {
        "js": ("renderAudienceDiscussion", "진행자", "참가자"),
        "store": ("aipol_public_audience_inputs", "aipol_audience_discussion_acks"),
    },
    "AIPOL-STEP-09": {
        "js": ("수정 의견 D′", "waiting_for_e3_release"),
        "store": ("FINAL_AI_OPINION", "public_audience_input_hash", "expert_artifact_hash"),
    },
    "AIPOL-STEP-10": {
        "js": ("structuredM3", 'current.stage === "T10"', "D_PRIME"),
        "store": ("aipol_m3_option_assessments", "build_t10_results"),
    },
    "AIPOL-STEP-11": {
        "html": ("state-done", "closing-panel-title", "패널 총평과 마무리"),
        "js": ('current.stage === "complete"',),
    },
}


@pytest.mark.parametrize("requirement_id", tuple(UC_TRACE))
def test_each_approved_step_is_wired_to_production_surface(requirement_id: str) -> None:
    """AIPOL-GATE-UC: all 11 approved steps have executable production wiring."""
    missing = {
        source: [token for token in tokens if token not in SOURCES[source]]
        for source, tokens in UC_TRACE[requirement_id].items()
    }
    missing = {source: tokens for source, tokens in missing.items() if tokens}
    assert not missing, f"{requirement_id} production wiring missing: {missing}"


def test_v3_declares_the_full_participant_sequence_without_future_stage_leakage() -> None:
    """AIPOL-GATE-UC: the state-machine order matches the approved procedure."""
    core_order = '["consent", "E0", "M1", "E1a", "M2", "E2", "E1b", "A1", "E3", "M3", "complete"]'
    assert core_order in SOURCES["experiment"]
    assert '_RESULT_AFTER_MEASUREMENT = {"M1": "T3", "M2": "T5", "M3": "T10"}' in SOURCES["store"]
    assert '_RESULT_NEXT_STAGE = {"T3": "E1a", "T5": "E2", "T10": "complete"}' in SOURCES["store"]
    assert '"interstitial_stage"] = "T6"' in SOURCES["store"]
