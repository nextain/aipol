"""[slice 4] AI 정책안 human_gate·수정이력·→설문·숙의 (실 Postgres, stub 독파모)."""
import os
import json
import pytest

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL 미설정(컨테이너 db 필요)", allow_module_level=True)
pytest.importorskip("api")

from policy_lab.core.approval import ApprovalToken, digest_artifact  # noqa: E402
from policy_lab.core.guards import GuardViolation  # noqa: E402
from api import repo, respondents as R2, proposals as PP  # noqa: E402

ALLOWED = {"admin"}


@pytest.fixture
def survey():
    p = repo.create_policy("slice4")
    sv = repo.create_survey(p["policy_id"], round=1, title="1회차",
                            proposals=[{"id": "1안", "title": "재정", "body": "."}], segment_key="")
    yield p, sv
    repo.delete_policy(p["policy_id"])


def _tok(issuer, art):
    return ApprovalToken(issuer=issuer, stage_id=PP.STAGE, artifact_digest=digest_artifact(art), nonce="n")


def test_human_gate_and_toctou(survey):
    p, sv = survey
    pp = PP.save_proposal(sv["survey_id"], {"title": "AI안", "body": "원본"})
    # 미승인 → 설문화 거부
    with pytest.raises(GuardViolation):
        PP.to_survey(pp["proposal_id"], next_round=2)
    # 임의(비신뢰) 발급자 거부
    with pytest.raises(GuardViolation):
        PP.approve_proposal(pp["proposal_id"], _tok("llm:gpt", pp["current"]), ALLOWED)
    # 승인
    PP.approve_proposal(pp["proposal_id"], _tok("admin", pp["current"]), ALLOWED)
    # TOCTOU: 승인 후 변조 → 거부
    PP.add_revision(pp["proposal_id"], editor="x", after={"title": "AI안", "body": "악성"}, reason="변조")
    with pytest.raises(GuardViolation):
        PP.to_survey(pp["proposal_id"], next_round=2)


def test_approved_to_survey_carries_original_and_ai(survey):
    p, sv = survey
    pp = PP.save_proposal(sv["survey_id"], {"title": "AI 통합안", "body": "차등"})
    PP.approve_proposal(pp["proposal_id"], _tok("admin", pp["current"]), ALLOWED)
    nxt = PP.to_survey(pp["proposal_id"], next_round=2)
    ids = [x["id"] for x in nxt["proposals"]]
    assert "1안" in ids and "ai안" in ids and nxt["round"] == 2


def test_revision_history_and_ai_original(survey):
    p, sv = survey
    pp = PP.save_proposal(sv["survey_id"], {"title": "원", "body": "a"})
    PP.add_revision(pp["proposal_id"], editor="expert", after={"title": "원", "body": "b"},
                    reason="회의보강", source="전문가회의")
    got = PP.get_proposal(pp["proposal_id"])
    assert got["ai_original"]["body"] == "a" and got["current"]["body"] == "b"
    assert got["revisions"][0]["source"] == "전문가회의"


def test_deliberate_stub(survey):
    p, sv = survey
    # 응답 3건(가상)
    for st in ("reject", "accept", "conditional"):
        rid, _ = R2.get_or_create_respondent(None, {}, "sim")
        R2.save_response(sv, rid, {"1안": {"stance": st, "text": "x" if st != "accept" else ""}}, model="sim")
    drafters = [{"model_id": "exaone", "company": "LG", "system_prompt": "재정"},
                {"model_id": "solar", "company": "Upstage", "system_prompt": "소득"},
                {"model_id": "kanana", "company": "Kakao", "system_prompt": "형평"}]
    merger = {"model_id": "solar", "company": "Upstage"}
    stub = lambda m, s, u: json.dumps({"title": "통합", "body": "x", "reflects": [], "tradeoffs": [], "unaddressed": []})
    out = PP.deliberate(sv, drafters, merger, generate=stub)
    assert out["merged"]["title"] == "통합" and len(out["drafts"]) == 3
    # 회사<3 거부
    with pytest.raises(ValueError):
        PP.deliberate(sv, drafters[:2], merger, generate=stub)
