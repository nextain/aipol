# AIPOL 챗봇·통합 관리자 코어 계약

두 패키지는 행사 숙의 엔진과 분리된 선택적 배포 단위다. `event-tool`의 실제 어댑터는
`aipol_admin_store.py`(SQLite), `aipol_chat.py`(추출형/Foundry)와 `/api/admin/aipol/*`에 있다.

- `policy_lab.services.chatbot`: 승인된 공개 지식만 검색하고, 모든 문장/주장을 원문 청크에 인용한다.
  충분한 근거가 없거나 인용·지지 검증이 실패하면 명시적으로 답변을 보류한다. 문서 안의 명령형
  문자열은 신뢰하지 않으며, 외부 모델 어댑터에는 지시문과 `untrusted_evidence` JSON을 분리해 전달한다.
- `policy_lab.services.admin`: 출처, 수집 배치, 지식 승인, 챗봇 설정의 도메인 계약이다. 편집자와
  승인자를 분리하고 변경을 해시 체인 감사 로그에 추가한다.

## 운영 통합 경계

코어 패키지는 실제 로그인 서버나 MFA 발급기가 아니다. event-tool은 SQLite와 UI/API를 연결했지만,
현재 서명 세션에는 외부 IdP가 검증한 MFA claim이 없다. 그래서 운영 환경의 모든 AIPOL 관리자
API는 읽기와 변경 모두 일괄 `503`으로 닫혀 있으며, 외부 IdP 어댑터가 붙기 전에는 이를 켜지 않는다.
공개 챗봇은 별도 이중 kill switch를 사용하고, 일반 행사 도구 API는 이 계약의 범위 밖이다.

1. 조직의 OIDC/OAuth2 공급자가 인증과 MFA를 수행하고 `Principal`/`SessionContext`를 만든다.
2. SQLite는 지식 개정·상태·감사 이벤트의 UPDATE/DELETE를 trigger로 막고, 같은 트랜잭션에서
   해시 체인을 덧붙인다. 시작할 때 체인을 재검증한다. 해시 체인은 접근 통제의 대체물이 아니다.
3. 검색 시점마다 현재 상태가 `approved`이고 공개 출처가 활성화된 청크만 조립한다. 승인 철회는
   즉시 다음 검색에서 제외된다.
4. 모델 어댑터는 구조화된 `Claim`만 반환하고, 자유 형식 답변을 사용자에게 직접 전달하지 않는다.
5. `chatbot/fixtures/evaluation.json`과 `FIXED_THRESHOLDS`를 릴리스 게이트로 실행한다.

## 런타임 kill switch

- `AIPOL_CHATBOT_PUBLIC_ENABLED=false`가 환경 기본값이고 DB의 `chatbot_config.enabled`도 기본 OFF다.
  둘 다 켜져야 공개 `/api/aipol/chat`가 응답한다.
- 생성 모드는 `off`, `extractive`, `azure_foundry`로 분리한다. Foundry는 `IDENTITY_ENDPOINT`가 있는
  Azure 관리 ID 환경에서만 lazy 초기화하며 API key 경로를 제공하지 않는다. 모델 호출 직전에
  질문 원문 없이 월별 비용 단위 1개를 원자적으로 예약하고 상한을 넘으면 호출을 거절한다.
- 배치 설정과 Azure 실행 스위치는 각각 기본 OFF다. 둘 다 명시적으로 켜진 경우에만 관리자가
  user-assigned managed identity로 지정된 Container Apps Job을 수동 시작하고 실행 상태를 조회한다.
  권한은 그 Job 하나의 `Container Apps Jobs Operator` 범위이며 자동 발행은 하지 않는다.
- `policy-news`와 `naia-kb-compiler` import는 `human_approved` + `public_export=true`의 공개 요약만
  받는다. 가져온 항목도 로컬에서는 다시 초안으로 시작해 별도 승인자를 거친다.

## 보안·개인정보 기본값

- 참가자 응답과 개인정보는 챗봇 지식에 넣지 않는다.
- 원문 질문 저장은 기본 비활성화하고 비용·오류 메타데이터만 최소 보관한다.
- 관리자 권한 작업은 기본 `SessionPolicy`에서 MFA와 세션 만료 검사를 요구한다.
- `ADMIN` 역할은 모든 권한을 자동 상속하지 않는다. 승인·편집·운영 권한은 명시적으로 분리한다.
