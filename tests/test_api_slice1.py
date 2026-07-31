"""[slice 1] 정책·설문 CRUD 통합 테스트 (실 Postgres). DATABASE_URL 없으면 skip.

스펙 정합: 각 객체 CRUD + 계약(안 id·비어있지않음·회차유일·정책실존) + CASCADE.
"""
import os
import pytest

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL 미설정(컨테이너 db 필요)", allow_module_level=True)
pytest.importorskip("api")

from api import repo  # noqa: E402


@pytest.fixture
def policy():
    p = repo.create_policy("테스트 정책", "ctx")
    yield p
    repo.delete_policy(p["policy_id"])  # CASCADE로 설문도 정리


def test_policy_crud(policy):
    assert repo.get_policy(policy["policy_id"])["title"] == "테스트 정책"
    up = repo.update_policy(policy["policy_id"], title="수정")
    assert up["title"] == "수정"
    assert any(p["policy_id"] == policy["policy_id"] for p in repo.list_policies())


def test_survey_contract(policy):
    pid = policy["policy_id"]
    sv = repo.create_survey(pid, round=1, title="1회차",
                            proposals=[{"id": "1안", "title": "a", "body": "."}])
    assert sv["round"] == 1
    # 회차 유일
    with pytest.raises(ValueError):
        repo.create_survey(pid, round=1, title="중복", proposals=[{"id": "1안", "title": "a", "body": "."}])
    # 안 id 필수
    with pytest.raises(ValueError):
        repo.create_survey(pid, round=2, title="t", proposals=[{"title": "a", "body": "."}])
    # 빈 안
    with pytest.raises(ValueError):
        repo.create_survey(pid, round=3, title="t", proposals=[])
    # 없는 정책
    with pytest.raises(ValueError):
        repo.create_survey("pl-nope", round=1, title="t", proposals=[{"id": "1안", "title": "a", "body": "."}])


def test_survey_edit_status_delete(policy):
    pid = policy["policy_id"]
    sv = repo.create_survey(pid, round=5, title="t", proposals=[{"id": "1안", "title": "a", "body": "."}])
    sid = sv["survey_id"]
    # 편집(안 편집)
    up = repo.update_survey(sid, title="수정", proposals=[{"id": "1안", "title": "재정", "body": "x"},
                                                        {"id": "2안", "title": "소득", "body": "y"}])
    assert up["title"] == "수정" and len(up["proposals"]) == 2
    # 상태
    assert repo.set_survey_status(sid, "open")["status"] == "open"
    with pytest.raises(ValueError):
        repo.set_survey_status(sid, "bogus")
    # 삭제
    repo.delete_survey(sid)
    assert repo.get_survey(sid) is None


def test_cascade_delete():
    p = repo.create_policy("삭제테스트")
    repo.create_survey(p["policy_id"], round=1, title="t", proposals=[{"id": "1안", "title": "a", "body": "."}])
    repo.delete_policy(p["policy_id"])
    assert repo.list_surveys(p["policy_id"]) == []  # CASCADE
