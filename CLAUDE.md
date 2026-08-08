# AIPOL

사람과 AI가 함께 정책을 설계하고 실험하는 도메인 중립 프레임워크입니다.

이 파일은 여러 AI 세션이 공유하는 **저장소 진입 인덱스**입니다. 현재 작업의 목표, 범위, 요구사항, 결정, 진행 상태, 연구 시나리오 또는 대외 문구를 이 파일에 기록하지 않습니다.

## 필수 읽기

작업 전에 다음 순서로 읽습니다.

1. `.agents/context/agents-rules.json` — 세션과 무관한 저장소 규칙
2. `.agents/context/project-index.yaml` — 코드·설계·도메인·시험·인계 문서 위치

현재 작업과 관련된 RFC·도메인 명세만 `project-index.yaml`에서 찾아 읽습니다. 현재 세션의 계약과 진행 상태는 `.agents/progress/`의 명시적으로 결박된 문서에서만 읽으며, 다른 세션 문서를 현재 목표로 추정하지 않습니다.

## 진입점

- 공개 설명: `README.md`
- 컨텍스트 인덱스: `.agents/context/project-index.yaml`
- 코어 공개 API: `policy_lab/core/__init__.py`
- 대외 사이트: `site/index.html`
- 시험: `tests/`

## 인계

세션 간 인계는 `.agents/progress/`의 세션별 문서에 기록합니다. `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`는 동일한 인덱스 내용을 유지합니다.
