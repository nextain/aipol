# AIPOL

**Human+AI 정책 설계·실험 프레임워크** — 도메인 중립 숙의 프로토콜 + 방어장치 내장 엔진.
연금(`policy_lab/domains/pension`)이 첫 레퍼런스 구현이다.

한국정책학회 "연금개혁-AI 정책실험"(2026-08-12)에서 출발했으나, 연금은 첫 도메인일 뿐이다.

---

## ⚠️ Multi-tool Harness

이 `AGENTS.md` = **canonical SoT**. `CLAUDE.md` / `GEMINI.md` 는 동일 내용 mirror.
편집은 `AGENTS.md`에 하고 두 mirror에 같은 내용을 반영한다. 표준: [agents.md](https://agents.md/).

## Mandatory Reads (every session start)

코드를 만지기 전 순서대로 읽는다:

1. `.agents/context/agents-rules.json` — 규칙 SoT (방어장치 불변식 + 금지/필수).
2. `.agents/context/project-index.yaml` — 컨텍스트 인덱스 + 진입점.
3. `RFC-0001-framework.md` — 도메인 중립 아키텍처 SoT.

특정 도메인을 손대기 전: `policy_lab/domains/<name>/` 와 그 `spec.md`(예: `domains/pension/spec.md`).

## 핵심 불변 — 방어장치 (Charter, RFC §6)

이 프레임워크의 신뢰성은 다음 가드에서 나온다. `policy_lab/core/guards.py` + 프로토콜
`validate()` 로 **코드로 강제**된다. 우회·약화는 **헌장 수정에 준함 → 사용자 명시 승인 필수**.

| 가드 | 강제 위치 | 막는 것 |
|------|-----------|---------|
| **A/B 분리** | `assert_ab_separation` | 영향 모델(A)과 공론 LLM(B)이 같은 모델 공유 → 폐루프 오류 증폭 |
| **human_gate** | `HumanGate` + `DeliberationProtocol.validate` | AI 쟁점정리가 전문가 승인 없이 청중 노출 |
| **화이트리스트** | `assert_within_whitelist` | 청중 변수 질문 인젝션 |
| **단일숫자 금지** | `reject_single_number` (`ImpactResult.__post_init__`) | 허위 정밀성(단일 정밀 숫자를 권위로 제시) |
| **재현성** | `ProvenanceRecord` (모델·버전·temp·시드·프롬프트·근거 기록) | 결과 비재현성 |

`agents-rules.json` `forbidden_actions` 가 SoT.

## 빌드 / 테스트

```bash
pip install -e ".[test]"
pytest -q
```

테스트는 "방어장치가 실제로 막는가"를 검증한다 (`tests/test_core.py`, `tests/test_pension.py`).

## 구조

```
aipol/
  AGENTS.md = CLAUDE.md = GEMINI.md   ← harness 진입점(동일 내용)
  README.md                            ← 공개 진입점
  RFC-0001-framework.md                ← 아키텍처 SoT
  LICENSE                              ← Apache-2.0
  CONTRIBUTING.md
  pyproject.toml
  .agents/context/                     ← AI SoT (agents-rules.json, project-index.yaml)
  .users/ko/context/                   ← 사람용 mirror (Korean)
  policy_lab/
    core/        ← levers · evidence · impact · deliberation · provenance · guards · prompts · protocols · plugin
    domains/
      pension/   ← 첫 레퍼런스: plugin · evidence · impact · prompts + spec.md
  tests/
```

## 새 도메인 추가

`DomainPlugin`(`policy_lab/core/plugin.py`)을 구현한다: `levers / fixed_variables / evidence /
impact_model / segments / prompts`. 프로토콜·방어장치는 코어에서 상속된다. `domains/<name>/spec.md`
명세를 함께 둔다.

## License

Apache-2.0
