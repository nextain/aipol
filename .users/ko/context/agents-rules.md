# AIPOL — 규칙 (사람용 mirror)

> 기계가 읽는 SoT는 `.agents/context/agents-rules.json`. 이 문서는 그 한국어 mirror다.
> 규칙이 충돌하면 JSON이 정본.

## 헌장 불변 (Charter)

다음 파일 + 방어장치는 AI가 단독 수정 불가, 사용자 명시 승인 필수:
`AGENTS.md` · `CLAUDE.md` · `GEMINI.md` · `.agents/context/agents-rules.json` ·
`RFC-0001-framework.md` · **`policy_lab/core/guards.py`**.

> `guards.py`가 헌장에 들어간 이유: 방어장치 코드가 곧 프레임워크의 신뢰성 보증이다.
> 약화하면 이 프로젝트의 학술 기여가 무력화된다.

## 방어장치 불변식 (RFC §6)

`policy_lab/core/guards.py` + `DeliberationProtocol.validate()` 로 코드 강제. 테스트가 검증.

| ID | 가드 | 강제 | 막는 것 |
|----|------|------|---------|
| G-AB | A/B 분리 | `assert_ab_separation` | 영향모델(A)·공론 LLM(B) 모델 공유 → 폐루프 오류 증폭 |
| G-GATE | human_gate | `HumanGate` + `validate` | AI 산출물이 전문가 승인 없이 청중 노출 |
| G-WL | 화이트리스트 | `assert_within_whitelist` | 청중 변수 질문 인젝션 |
| G-NUM | 단일숫자 금지 | `reject_single_number` | 허위 정밀성 |
| G-PROV | 재현성 | `ProvenanceRecord` | 결과 비재현성 |

## 금지 행동 (forbidden_actions)

- **F01** 헌장 파일(guards.py 포함) 승인 없이 수정 금지
- **F02** 방어장치 우회·약화·삭제 금지. 변경 PR은 "어떤 red-team 약점을 다시 여는가" 명시
- **F03** 출처·버전 없는 정량 앵커를 Evidence 추가 금지
- **F04** 도메인 plugin 이 코어(`policy_lab/core`) 수정 금지 — 코어 변경은 별도 RFC/이슈
- **F-SEC01** 키·시크릿·세션 원자료(투표 PII)는 추적 경로 금지 → `data-private/`(gitignored)

## 승인 필요 고위험 행동 (ask)

- 라이브 세션 프롬프트/근거를 사전검수 통과본 외로 교체
- 정식 레포 생성·공개 전환·릴리즈 태그
- 방어장치 enforcement 수준 변경

## 빌드 / 테스트

```bash
pip install -e ".[test]"
pytest -q     # 그린 = 방어장치 동작 증거
```
# 비공개 자료 보관 규칙

- 외부에서 받은 원본 문서, 미공개 초안, 내부 논의, 회의록 및 연구진 인계 문서는 `AIPOL` 공개 저장소에 복사하거나 커밋하지 않습니다.
- 해당 자료는 비공개 저장소 `nextain/policy-lab-private`의 `received/` 또는 `internal/`에만 보관합니다.
- 공개 저장소의 로컬 `private/` 경로는 Git에서 무시됩니다.
- 저장소 공개 전에는 현재 파일뿐 아니라 Git 전체 이력에서도 비공개 자료가 남아 있지 않은지 검사합니다.
