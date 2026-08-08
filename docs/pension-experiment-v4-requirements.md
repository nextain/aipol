# 국민연금 AI 숙의 실험 v4 정본 요구사항

- 상태: 구현 기준 초안
- 결정 기준일: 2026-08-09
- 구현 저장소: `nextain/aipol`
- 실험·회의·수신자료·합성 산출물 저장소: `nextain/aipol-lab`
- 제외 저장소: `armybonita/Pension-Policy-Lab-` (개인연금 UI의 역사적 참고자료일 뿐 정본·배포 대상이 아님)

이 문서는 2026-08-09 사용자 결정과 전달 자료의 확인 가능한 부분을 기존 v3 계약과
구분해 기록한다. 충돌할 때 이 문서의 명시적 사용자 결정을 우선하되, 정책 수치·계산식·
전문가 명의에는 별도의 출처와 승인이 있어야 한다.

## 1. 제품과 데이터 경계

1. 참가자 서비스와 어드민은 `nextain/aipol`에서 하나의 정본으로 개발한다.
2. `?review`는 별도 화면 구현을 선택하는 기능이 아니다. 같은 프런트엔드, 같은 API,
   같은 상태 전이와 검증 규칙을 사용하고 `kind=review`인 별도 행사와 별도 참가자
   namespace를 선택한다.
3. review 행사는 실제 행사와 다른 `event_id`를 사용하며 실제 집계에 포함되지 않는다.
   브라우저에서 API 호출을 생략하거나 고정 fixture만 그리는 review 분기는 허용하지 않는다.
4. 100명·250명 합성 실험, 회의록, 전달 원문, 실험 영수증과 합성 결과 공개 페이지는
   `nextain/aipol-lab`에서 별도 이슈로 진행한다.
5. review query는 권한을 만들지 않는다. 서버가 발급한 제한된 review credential과
   review event의 결합이 유효할 때만 읽기·쓰기를 허용한다.

## 2. 해석 계약

- 행사의 phase가 참가자에게 허용된 구간을 결정하고, 그 구간 안에서는 서버가 확인한
  참가자 prerequisite가 현재 화면을 결정한다.
- 브라우저는 서버가 반환한 단계보다 앞설 수 없다. 새로고침 때 로컬 최대 단계를 복원해
  서버 상태를 덮어쓰지 않는다.
- `M1→M2`와 `M2→M3`는 같은 참가자 안에서 관찰된 변화다. 무작위 통제군 없이
  AI·전문가가 변화를 야기했다는 인과 주장을 하지 않는다.
- 모든 투표는 그 투표에 대응하는 승인된 전문가 설명 또는 숙의 산출물을 확인한 뒤 열린다.
  따라서 M1은 무정보 기준선이 아니라 **전문가의 A/B/C 설명 이후 1차 측정**이다.

## 3. 참가자 유스케이스

### UC-P01 — 입장, 동의, 개인정보 입력

참가자는 행사 코드로 입장하고 동의문을 확인한 뒤 M1 전에 성별, 나이, 소득을 입력한다.

수용 조건:

- 동의 버전·동의 시각과 프로필 완료 시각을 별도로 기록한다.
- 성별은 `응답하지 않음`을 포함한다.
- 연령과 소득의 정확값이 개인 계산에 필요하면 브라우저 또는 계산기 경계에서만 사용하고,
  연구 DB에는 사전 등록한 구간과 구간 규칙 버전을 저장한다.
- 프로필이 완료되지 않으면 M1을 조회하거나 제출할 수 없다.
- 프로필은 첫 투표 이후 수정할 수 없다.

### UC-P02 — 전문가 A/B/C 설명과 1차 투표(M1)

참가자는 승인된 A/B/C 비교자료를 읽고 확인한 뒤 하나의 안을 선택한다. 선택안의 수용성
(`수용` 또는 `조건부 수용`)과 자유서술 사유는 필수다.

수용 조건:

- 정책안 자료는 source bundle, 정책안 version, 전문가 승인과 content hash를 가진다.
- 자료 확인 receipt가 없으면 M1 선택 UI와 제출 API를 열지 않는다.
- 선택, 수용성, 필수 사유를 하나의 append-only M1 ballot으로 저장한다.
- 자유서술을 먼저 작성한 뒤 관심 쟁점을 별도 선택하게 해 분류 priming을 줄인다.
- 관심 쟁점 선택은 참가자의 명시적 관심이고 AI 분류를 대체하지 않는다.

### UC-P03 — 개인 조건 비교와 2차 투표(M2)

참가자는 출처·산식·기준일·포함/제외 항목이 승인된 개인 조건 비교를 확인하고 A/B/C를
다시 평가한다.

수용 조건:

- 계산 receipt와 승인된 전문가 설명 receipt가 모두 있어야 M2가 열린다.
- 선택안은 `수용|조건부 수용`과 필수 사유, 나머지 두 안은 `비선택`과 각 필수 사유를 저장한다.
- M1과 같은 option id·표시 순서·질문 version을 유지한다.
- 계산식이 전문가 승인 전이면 숫자를 생성하지 않고 `검증 대기`로 차단한다.

### UC-P04 — AI 쟁점 정리와 D 생성

AI는 동결된 M2 결과와 의견을 입력으로 쟁점을 분류하고 D 초안을 만든다. 참가자 원문,
숨은 추론, 내부 프롬프트와 개인정보는 공개하지 않는다.

입력 계약:

- M2 선택 분포와 수용성
- 선택안·비선택안의 자유서술 사유
- M1→M2 참가자 내 변화의 비식별 집계
- AI 분류된 쟁점 통계와 별도 참가자 관심 쟁점 통계
- 승인된 source bundle, constraint set, taxonomy version

출력 계약:

- 역할별 제안, 상호 비판, 수정, 종합안의 **구조화된 공개 요약**
- 실행 ID, 공급자·모델, 프롬프트 version, 입력 artifact hash, 시작·종료 시각, 오류·fallback
- D 초안의 정책 레버, 전제, 근거 식별자와 constraint 검사 결과
- 공개 요약에는 raw chain-of-thought, 원문 의견, 개인 식별 정보와 미승인 수치를 포함하지 않는다.

### UC-P05 — 전문가 검토와 D 공개

전문가는 D 초안을 비용·부담·정책 제약·실현 가능성 관점에서 검토하고 수정 또는 승인한다.

수용 조건:

- AI 초안 artifact hash와 승인본 artifact hash를 함께 저장한다.
- 공개 가능한 field-level diff, 수정 이유, 승인자, 승인 시각과 서명을 저장한다.
- D 화면은 AI 공개 요약, 사용한 입력/자료의 provenance, 전문가 수정 diff와 승인 결과를
  같은 승인 version으로 보여준다.
- 전문가 승인이 없거나 source/constraint/taxonomy가 바뀌어 승인이 stale이면 D를 공개하지 않는다.

### UC-P06 — 3차 투표(M3)

화면과 보고서에는 `최종 투표`가 아니라 `3차 투표`라고 표시한다. 참가자는 승인된 D와
전문가 검토 내용을 확인한 뒤 3차 응답을 제출한다.

수용 조건:

- M2 완료, 현재 D 공개요약·전문가 diff·승인 receipt가 없으면 선택 UI를 보여주지 않는다.
- 선택지 구성은 행사 동결 manifest에 명시하며 UI가 임의로 D 또는 D′를 추가하지 않는다.
- 선택·수용성·필수 사유를 append-only M3 ballot으로 저장한다.
- 결과는 `1차→2차→3차`로 표현하고 `최종`이라는 인과·종결 암시 표현을 사용하지 않는다.

### UC-P07 — 재접속과 단계 일관성

- 서버 resolver는 `event phase ∩ participant prerequisites`로 현재 단계를 계산한다.
- API 조회, 제출 transaction과 DB guard가 같은 prerequisite 계약을 적용한다.
- direct API, stale revision, 다른 event의 participant id, stale artifact receipt를 거부한다.
- review와 real 참가자의 데이터·집계·credential은 교차 사용할 수 없다.

## 4. 어드민 유스케이스

### UC-A01 — 행사 생성과 동결

어드민은 행사 종류 `live|review`, 절차 version, 정원, phase, consent version,
source bundle version, constraint set version, taxonomy version을 지정한다. 참가자 종류는
`real|synthetic`으로 별도 관리하며 `live↔real`, `review↔synthetic` 조합만 허용한다. review는
live 행사를 직접 변경하지 않고 승인된 설정을 별도 event id로 복제한다.

### UC-A02 — 자료·제약조건 관리

어드민은 아래 artifact를 draft → preview → 별도 승인자 승인 → freeze 순서로 관리한다.

- A/B/C 정책안과 전문가 설명
- 개인 조건 비교 산식·정책 레버·known-answer fixture
- AI 역할·라운드·전체 시간 제한과 실패/fallback 규칙
- 허용/금지 정책 제약, 단위, 경계, 근거와 적용 version
- 쟁점 taxonomy와 분류 규칙
- 개인정보·연구윤리·보존·삭제·공개 집계 규칙

제약조건은 UI 문자열이 아니라 versioned DB artifact다. D run은 정확한 constraint artifact id와
hash를 참조하고, 위반하면 전문가 승인 단계로 넘어갈 수 없다.

### UC-A03 — D 숙의 요약과 전문가 승인

어드민은 실제 실행으로 생성된 구조화 공개 요약을 검토하고, D 초안과 승인본 차이를 입력·
확인하며, 공개 이유를 작성한다. 정적 애니메이션이나 미리 작성한 일반 문구를 실제 AI
논의과정으로 표시하지 않는다.

### UC-A04 — 행사 phase 운영

어드민은 등록, M1, 개인 비교/M2, AI·전문가 작업, M3, 종료를 명시적으로 전환한다.
각 전환은 현재 prerequisite와 승인 artifact를 서버에서 재검증하고 감사 로그에 남긴다.

## 5. 쟁점 분류와 수치 계약

수신 문서의 다섯 쟁점은 `예시`이며 산식은 제공되지 않았다. 승인된 taxonomy가 없으면
다섯 이름을 공식 고정 분류로 주장하지 않는다.

기본 표시 계약:

- AI 분류 언급률: `해당 쟁점으로 분류된 고유 응답자 수 / 해당 차수 유효 응답자 수(N)`
- 사유 레코드 수: 해당 쟁점 label이 붙은 선택·비선택 사유 레코드 수
- 명시 관심률: `해당 쟁점을 직접 선택한 고유 응답자 수 / 관심 쟁점 응답자 수(N)`
- M1과 M2는 따로 계산하고, 변화는 같은 metric끼리만 비교한다.
- 다중 label이면 쟁점별 비율 합이 100%를 넘을 수 있음을 화면에 명시한다.
- 화면에는 `n`, `%`, 유효 N, 결측·제외 수, taxonomy version, 단일/다중 label 규칙,
  사람 승인 상태를 함께 표시한다.
- 근거 없는 중요도 `점수`와 `47/44/41/38/35` 같은 fixture 숫자는 정식 화면에 표시하지 않는다.

## 6. 데이터 모델 불변식

필수 개념은 다음과 같다.

- `events`: kind, cloned_from_event_id, phase, phase_version, procedure_version,
  source_bundle_version_id, constraint_set_version_id, taxonomy_version_id, current_d_artifact_id
- `participants`: event와 복합 식별, consent version/time, profile completed time, participant type
- `participant_profiles`: 승인된 성별 범주와 연령·소득 구간, binning rule version
- `artifacts`: 불변 source/constraint/taxonomy/expert/AI/public-summary/D version, visibility,
  provenance, content hash, approval status
- `participant_artifact_receipts`: participant·event·artifact version·receipt type·ack time
- `ballots`: event·participant·measurement·revision·phase version·prerequisite snapshot hash·
  preceding artifact versions·choice·stance·reason
- `reason_classifications`: reason hash·taxonomy version·labels·model provenance·사람 승인
- `participant_issue_interests`: AI 분류와 분리된 명시 선택
- `expert_reviews`: base draft hash·approved hash·public diff·rationale·signer·time·supersedes
- `audit`: event sequence와 이전 hash를 포함한 append-only 관리자·참가자 행위 기록

기존 행은 존재하지 않는 profile·receipt·D provenance를 추정해 backfill하지 않는다.
증명할 수 없는 행은 `legacy_unverified`로 분리해 엄격 완료 집계에서 제외한다.

## 7. 정량 출처 게이트

기획 적대 리뷰는 화면·API·fixture의 사용자 노출 정량값 목록부터 시작한다. 각 값은 다음을
모두 가져야 한다.

- source id와 원문 위치
- 기준일과 version
- 단위, 분모와 산식
- 불확실성 또는 적용 한계
- 승인자와 승인 시각
- 파생값이면 입력 artifact hash와 재계산 가능한 코드/test

하나라도 없으면 `출처 미확인`, `검토용 fixture` 또는 `검증 대기`로 분류하고 정식 UI·D 입력·
결과 해석에서 차단한다. 역사적 코드 커밋이나 화면 존재만으로 전문가 승인 또는 공인 산식으로
간주하지 않는다.

## 8. 완료 게이트

서비스·어드민 작업은 아래를 모두 충족해야 완료로 판단한다.

1. 각 UC에 API·DB·UI·자동 테스트 trace가 있다.
2. review event가 real과 같은 서비스 경로를 사용하고 데이터가 격리된다.
3. M1 전 프로필과 각 투표 전 승인 artifact receipt가 서버와 DB에서 강제된다.
4. M1/M2/M3 필수 사유, AI 분류, 명시 관심 쟁점과 재현 가능한 통계가 분리 저장된다.
5. D 공개요약·전문가 diff·승인이 실제 artifact와 결합되고 private output이 누출되지 않는다.
6. 정량 출처 감사의 release blocker가 0건이다.
7. product-preservation, contract-conformance, build, 브라우저 E2E와 적대 리뷰가 통과한다.
8. 운영 수집은 backup recovery와 receipt verifier를 포함한 readiness가 모두 true일 때만 연다.

100명·250명 합성 실행과 합성 결과 공개 페이지는 이 완료 뒤 `aipol-lab`의 별도 이슈에서
수행한다.
