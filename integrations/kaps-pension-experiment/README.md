# AIPOL 연금개혁-AI 숙의민주주의 정책실험 시나리오 통합

이 디렉터리는 외부 기여 시나리오 앱을 AIPOL의 `연금개혁-AI 숙의민주주의 정책실험`에 통합하기 위한 경계입니다.

- 원본 저장소: `armybonita/2026-Flagship-Session-KAPS-Human-AI-Collaborative-Policy-Lab-`
- 원본 PR: `#1`
- 고정 커밋: `fcbae3c0dab18476e2274f9e4ff91dadeb2db944`
- 포함 범위: PR 최상위 `src/` 앱과 빌드 설정
- 제외 범위: 별도 하위 프로젝트 `personal-pension-simulator/`

`vendor/`는 원본 커밋에서 그대로 추출한 읽기 전용 기준선입니다. `adapter/`가 원본을 수정하지 않고 다음 통합 요소를 적용합니다.

- AIPOL 공통 디자인과 `연금개혁-AI 숙의민주주의 정책실험` 명칭
- 한국정책학회·넥스테인 공동 운영 로고
- 프로젝트 소개와 연금팀 시나리오 검토 기준으로 돌아가는 경로
- 원본의 사전조사 → 1차 투표 → AI 진단·소그룹 토론 → 최종 2차 투표 흐름

```bash
cd integrations/kaps-pension-experiment/vendor
npm install
cd ../../..
node scripts/build_pension_experiment.mjs
```

산출물은 `site/cases/pension/experiment/`에 생성됩니다. 정책 수치와 분석 문구는 연금팀 검토 대상이며, 현재 정적 검토본의 응답은 서버에 저장되거나 전송되지 않습니다.
