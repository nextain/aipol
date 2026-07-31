# AIPOL — 컨텍스트 인덱스 (사람용 mirror)

> 이 문서는 `.agents/context/project-index.yaml` 의 사람용 한국어 mirror다.
> 기계가 읽는 SoT는 `.agents/` 쪽이며, 규칙 SoT는 `.agents/context/agents-rules.json`.

## 무엇인가

**Human+AI 정책 설계·실험 프레임워크.** 정책 숙의 실험을 재현 가능·투명·반증 가능하게
설계·운영·기록하는 도메인 중립 도구. 연금(`domains/pension`)이 첫 레퍼런스 구현이다.
한국정책학회 "연금개혁-AI 정책실험"(2026-08-12)에서 출발했다.

## 세션 시작 시 읽을 것 (순서)

1. `.agents/context/agents-rules.json` — 규칙 SoT (방어장치 불변식 + 금지/필수)
2. `.agents/context/project-index.yaml` — 컨텍스트 인덱스
3. `RFC-0001-framework.md` — 도메인 중립 아키텍처 SoT

도메인 작업 전: 해당 `domains/<name>/spec.md` (예: `domains/pension/spec.md`).

## 핵심 — 방어장치가 이 프로젝트의 정체성

red-team이 지적한 정책실험의 약점(폐루프 오류 증폭·manufactured consent·표본≠민의·
허위 정밀성·비재현성)을 **프레임워크가 코드로 강제 차단**한다. `policy_lab/core/guards.py` +
`DeliberationProtocol.validate()`. 이 방어장치가 곧 학술 기여 포인트이며, 약화는 헌장 수정에
준한다(사용자 승인 필수).

| 가드 | 막는 것 |
|------|---------|
| A/B 분리 | 영향 모델(A)·공론 LLM(B) 모델 공유 → 오류 증폭 |
| human_gate | AI 쟁점정리가 전문가 승인 없이 청중 노출 |
| 화이트리스트 | 청중 변수 질문 인젝션 |
| 단일숫자 금지 | 허위 정밀성 |
| 재현성(Provenance) | 결과 비재현성 |

## 빌드 / 테스트

```bash
pip install -e ".[test]"
pytest -q     # 그린 = 방어장치 동작 증거
```

## 구조

- `policy_lab/core/` — levers · evidence · impact · deliberation · provenance · guards · prompts · protocols · plugin
- `policy_lab/domains/pension/` — 첫 레퍼런스: plugin · evidence · impact · prompts (+ `domains/pension/spec.md`)
- `tests/` — 방어장치가 실제로 막는가 검증

## 진행 상황


## 배포·데이터 운영

온라인 공개, Vercel 자동 배포, 행사 도구의 SQLite 제약, 데이터베이스 후보, 개인정보 처리,

## 연금 합성 데이터

100명 합성 시민의 정확한 출처·구성·모델 배정·공개 산출물 계약은
`.agents/context/research-data.yaml`이 정본이다. 사람용 설명은
`.users/ko/context/research-data.md`, 상세 방법은 `docs/pension-synthetic-methodology.md`를 본다.
# 비공개 자료 진입점

- 저장소: `nextain/policy-lab-private` (비공개)
- 로컬 경로: `private/` (Git 추적 제외)
- `received/`: 외부에서 받은 원본 문서
- `internal/`: 내부 논의, 회의록, 인계 문서, 미공개 초안
- 공개 전 점검은 현재 트리와 Git 전체 이력을 모두 대상으로 합니다.
