"""[slice 2] 응답자·응답 계약 테스트 (실 Postgres). DATABASE_URL 없으면 skip.

계약: 다차원 누락·조건부 빈텍스트 거부(core), 중복 차단, 익명 code 회차연결, human/virtual.
"""
import os
import pytest

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL 미설정(컨테이너 db 필요)", allow_module_level=True)
pytest.importorskip("api")

from api import repo, respondents as R2  # noqa: E402


@pytest.fixture
def survey():
    p = repo.create_policy("slice2 정책")
    sv = repo.create_survey(p["policy_id"], round=1, title="1회차",
                            proposals=[{"id": "1안", "title": "a", "body": "."},
                                       {"id": "2안", "title": "b", "body": "."}],
                            segment_key="age")
    yield p, sv
    repo.delete_policy(p["policy_id"])


def test_contract_missing_and_conditional(survey):
    _, sv = survey
    rid, _ = R2.get_or_create_respondent(None, {"age": "30대"}, "human")
    with pytest.raises(ValueError):  # 2안 누락
        R2.save_response(sv, rid, {"1안": {"stance": "accept"}})
    with pytest.raises(ValueError):  # 조건부 빈텍스트
        R2.save_response(sv, rid, {"1안": {"stance": "conditional", "text": ""}, "2안": {"stance": "accept"}})
    rec = R2.save_response(sv, rid, {"1안": {"stance": "reject", "text": "부담"}, "2안": {"stance": "accept"}})
    assert rec["respondent_id"] == rid and rec["segment"] == "30대"


def test_duplicate_blocked(survey):
    _, sv = survey
    rid, _ = R2.get_or_create_respondent(None, {}, "human")
    R2.save_response(sv, rid, {"1안": {"stance": "accept"}, "2안": {"stance": "accept"}})
    with pytest.raises(ValueError):
        R2.save_response(sv, rid, {"1안": {"stance": "reject", "text": "x"}, "2안": {"stance": "accept"}})


def test_code_linking_and_kind(survey):
    _, sv = survey
    rid, code = R2.get_or_create_respondent(None, {"age": "50대"}, "human")
    rid2, _ = R2.get_or_create_respondent(code, {}, "human")  # 같은 code
    assert rid2 == rid
    rid_v, _ = R2.get_or_create_respondent(None, {}, "qwen")  # virtual
    assert R2.get_respondent(rid)["kind"] == "human"
    assert R2.get_respondent(rid_v)["kind"] == "virtual"
