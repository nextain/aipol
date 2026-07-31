"""[slice 3] AI 에이전트(모델×페르소나) CRUD + 가드 (실 Postgres)."""
import os
import pytest

if not os.environ.get("DATABASE_URL"):
    pytest.skip("DATABASE_URL 미설정(컨테이너 db 필요)", allow_module_level=True)
pytest.importorskip("api")

from api import agents as AG  # noqa: E402


@pytest.fixture
def cleanup():
    made = {"m": [], "p": [], "a": []}
    yield made
    for a in made["a"]:
        AG.delete_agent(a)
    for m in made["m"]:
        AG.delete_model(m)
    for p in made["p"]:
        AG.delete_persona(p)


def test_model_persona_agent_crud(cleanup):
    m = AG.create_model("EXAONE", "LG", "friendli"); cleanup["m"].append(m["model_id"])
    p = AG.create_persona("재정안정 옹호", "drafter", "재정 관점으로"); cleanup["p"].append(p["persona_id"])
    a = AG.create_agent("EXAONE·재정", m["model_id"], p["persona_id"]); cleanup["a"].append(a["agent_id"])
    # 조인 조회 = 회사·role·system_prompt 함께
    got = next(x for x in AG.list_agents() if x["agent_id"] == a["agent_id"])
    assert got["company"] == "LG" and got["role"] == "drafter"
    # 없는 모델/페르소나 → 거부
    with pytest.raises(ValueError):
        AG.create_agent("x", "m-none", p["persona_id"])


def test_company_guard():
    two = [{"company": "LG"}, {"company": "Upstage"}]
    with pytest.raises(ValueError):
        AG.assert_drafters_independent(two)   # 2사<3
    AG.assert_drafters_independent(two + [{"company": "Kakao"}])  # 3사 통과
    # 대소문자·공백 우회 차단
    with pytest.raises(ValueError):
        AG.assert_drafters_independent([{"company": "LG"}, {"company": "lg "}, {"company": " LG"}])


def test_judge_separation():
    with pytest.raises(ValueError):
        AG.assert_judge_separation({"LG", "Upstage"}, {"lg"})  # 겹침(정규화)
    AG.assert_judge_separation({"LG", "Upstage"}, {"Kakao"})   # 분리
