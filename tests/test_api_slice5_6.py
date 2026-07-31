"""[slice 5·6] 종합 보고서 §6 + 수용 시나리오 전 루프 (실 Postgres, stub 독파모).

골 수용 시나리오: 정책→설문→에이전트→숙의→승인→다음회차(원안+AI안)→재응답→이동→보고서.
"""
import os
import json
import pytest

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL 미설정(컨테이너 db 필요)", allow_module_level=True)
pytest.importorskip("api")

from policy_lab.core.approval import ApprovalToken, digest_artifact  # noqa: E402
from policy_lab.core.guards import MeasurementPurpose, GuardViolation  # noqa: E402
from api import repo, respondents as R2, proposals as PP, agents as AG, report as RP  # noqa: E402


def test_report_rejects_opinion_purpose():
    with pytest.raises(GuardViolation):
        RP.final_report("pl-x", purposes=[MeasurementPurpose.OPINION_MEASUREMENT])


def test_full_acceptance_scenario():
    # 정책 + 1회차 설문(open)
    pol = repo.create_policy("연금 개혁 수용시나리오")
    try:
        sv1 = repo.create_survey(pol["policy_id"], round=1, title="1회차",
                                 proposals=[{"id": "1안", "title": "재정", "body": "."},
                                            {"id": "2안", "title": "소득", "body": "."}], segment_key="age")
        repo.set_survey_status(sv1["survey_id"], "open")
        # 가상 응답자 3명 1회차 (거부→이동 준비)
        codes = []
        for age, a1 in [("70대", "reject"), ("30대", "reject"), ("50대", "conditional")]:
            rid, code = R2.get_or_create_respondent(None, {"age": age}, "sim")
            R2.save_response(sv1, rid, {"1안": {"stance": a1, "text": "x"}, "2안": {"stance": "accept"}}, model="sim")
            codes.append(code)
        repo.set_survey_status(sv1["survey_id"], "closed")

        # 에이전트 3사 + 숙의(stub)
        stub = lambda m, s, u: json.dumps({"title": "세대상생안", "body": "차등+기초연금",
                                           "reflects": ["1안 거부"], "tradeoffs": [], "unaddressed": []})
        drafters = [{"model_id": "exaone", "company": "LG", "system_prompt": "재정"},
                    {"model_id": "solar", "company": "Upstage", "system_prompt": "소득"},
                    {"model_id": "kanana", "company": "Kakao", "system_prompt": "형평"}]
        out = PP.deliberate(sv1, drafters, {"model_id": "solar", "company": "Upstage"}, generate=stub)
        pp = PP.save_proposal(sv1["survey_id"], out["merged"], out["provenance"])

        # human_gate 승인 → 2회차(원안+AI안)
        tok = ApprovalToken(issuer="admin", stage_id=PP.STAGE,
                            artifact_digest=digest_artifact(pp["current"]), nonce="n")
        PP.approve_proposal(pp["proposal_id"], tok, {"admin"})
        sv2 = PP.to_survey(pp["proposal_id"], next_round=2)
        repo.set_survey_status(sv2["survey_id"], "open")

        # 재응답(같은 code → 이동): 70대·30대 1안 유지, 하지만 accept로 이동시켜 검증
        for code, a1 in zip(codes, ["accept", "reject", "conditional"]):
            rid, _ = R2.get_or_create_respondent(code, {}, "sim")
            R2.save_response(sv2, rid, {"1안": {"stance": a1, "text": "y"}, "2안": {"stance": "accept"},
                                        "ai안": {"stance": "accept"}}, model="sim")

        # 종합 보고서 — 이동·구성·숙의근거
        rep = RP.final_report(pol["policy_id"])
        assert set(rep["per_round"].keys()) == {"1", "2"}
        assert rep["movement"]["1안"]["transitions"].get("reject->accept") == 1  # 70대 이동
        assert rep["composition"]["virtual"] >= 3
        props2 = repo.get_survey(sv2["survey_id"])["proposals"]
        assert "ai안" in [p["id"] for p in props2] and "1안" in [p["id"] for p in props2]
        assert rep["deliberations"][0]["approved_by"] == "admin"
        assert rep["limits"]
    finally:
        repo.delete_policy(pol["policy_id"])
