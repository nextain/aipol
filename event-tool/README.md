# 정책 숙의 행사 도구 (event-tool)

전문가 안을 시민에게 정확히 받고 → 빠짐없이 수렴해 AI(독파모)가 추가 안을 내고 → 사람이
검토·승인해 다음 회차로 재수집 → 최종 보고서까지, **진행자 한 명이 라이브로 굴리는 도구**.
`KAPS Human + AI Collaboration Policy Lab: 연금개혁-AI 숙의민주주의 정책실험`(2026-08-12)이
활용 사례이나, **도메인 중립** — 어떤 정책
숙의에도 데이터(케이스)만 바꿔 재사용한다.

> 설계 배경·의사결정은 [`docs/event-tool-design.md`](../docs/event-tool-design.md) 참조.
> 초기 프로토타입 실험(6/25, 페르소나 생성기=Nemotron, 숙의=비한국 모델 혼합 — 아래 §7에서
> 한국 3사 요건 위반으로 폐기·재실행됨)의 기록은 과거 비공개 운영 저장소에서 보관합니다.

---

## 1. 무엇을 하나 (한눈에)

- **시민 페이지**(공개): 진행 중 설문의 안(제안)에 **수용/조건부/거부 + 의견**을 낸다. 고령 접근성 우선(큰 글씨·큰 버튼).
- **진행자 페이지**(어드민): 행사를 **단계대로** 진행 — 준비 → 수집 → AI 숙의 → 수정·승인 → 다음 회차 → 보고서.
- **AIPOL 통합 관리자**(`/aipol-admin.html`): 실험·공개 지식·정책동향 배치·근거형 챗봇 설정을 탭으로
  관리한다. 지식은 작성자와 별도 승인자를 요구하고 승인 철회 즉시 검색에서 제외된다.
- **AI 숙의**: 독파모 여럿이 시민 의견을 교차 검토해 통합 추가 안을 만든다. **가드**로 자기강화·허위정밀을 막고, **반영/미반영을 정직하게** 노출한다.

## 2. 경량 스택

- **백엔드**: FastAPI (`server.py`)
- **저장**: SQLite 파일 (`event.db`, 자동 생성). Azure 운영에서는 Azure Files에 영속 저장
- **프론트**: 순수 HTML/CSS/JS (`web/`) — 빌드 스텝 없음, 프레임워크 없음
- **AI**: 독파모 API(Friendli·Upstage·CLOVA) 디스패치 — 프로바이더 레지스트리(`llm.py`, `ai_config.py`, `deliberate.py`)
- **운영 배포**: Azure Container Apps 단일 replica + Azure Files 영속 SQLite

통합 관리 데이터(출처, 지식 개정/상태, 배치 설정/요청, 챗봇 설정, 해시 체인 감사 로그)도 같은
SQLite 파일에 저장되고 재시작 때 복원된다. 지식 개정·상태·감사 테이블은 append-only trigger로
보호한다.

운영 보안 기본값은 `AIPOL_CHATBOT_PUBLIC_ENABLED=false`이며 배치·챗봇 DB 설정도 OFF다.
`EVENT_ENV=production`에서는 평문 관리자 비밀번호를 거부하고 scrypt 해시만 허용한다. 모든 개인
관리자 계정은 TOTP 2단계 인증과 명시적 역할 매핑이 있어야 하며 하나라도 빠지면 서버가 시작되지
않는다. 작성자와 승인자는 서로 다른 계정으로 구성한다.

## 3. 빠른 시작 (처음 온 사람용)

```bash
cd event-tool

# 1) 파이썬 가상환경 + 의존성 (한 번만)
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn

# 2) (선택) AI 숙의를 쓰려면 독파모 키를 .env 에 둔다 — 커밋 금지(gitignored)
#    AI 숙의를 안 쓰면 이 단계 생략 가능(준비·수집·보고서는 키 없이 동작)
cat > .env <<'EOF'
FRIENDLI_AI_KEY=여기에_키
UPSTAGE_KEY=여기에_키
EVENT_ADMIN_PASSWORD=demo
# AIPOL 통합 관리자는 개발에서도 역할을 명시해야 한다. 실제 승인 흐름은
# editor와 approver를 서로 다른 계정으로 구성한다.
EVENT_ADMIN_ROLES_JSON={"local":["editor","operator","admin","auditor"]}
EOF

# 3) 서버 실행
.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8100
```

- **시민 화면**: http://127.0.0.1:8100/
- **AIPOL 참여 화면**: http://127.0.0.1:8100/aipol.html?experiment={실험ID}
- **진행자 화면**: http://127.0.0.1:8100/admin.html  (아이디 `local`, 비밀번호 = `EVENT_ADMIN_PASSWORD`, 기본 `demo`)
- **AIPOL 통합 운영**: http://127.0.0.1:8100/aipol-admin.html

> 위 주소와 `demo` 기본값은 **로컬 개발·리허설 전용**이다. 인터넷에 그대로 배포하지 않는다.
> 운영 주소는 `https://session.aipol.kaps.or.kr/`이다. 관리자·참여자 경로는 모두
> `X-Robots-Tag: noindex, nofollow, noarchive`와 `robots.txt: Disallow /`로 검색에서 제외한다.
> 실제 응답 수집은 승인된 정본 자료·외부 계산기 receipt 검증·개인정보 운영계획을 확인한 뒤 실험별
> `collection_enabled`를 명시적으로 켠 경우에만 가능하다. 기본값은 항상 OFF다.

Azure Files는 SQLite 파일 잠금을 지원하지 않아 운영 컨테이너는 `EVENT_SQLITE_NOLOCK=true`와
**단일 replica**를 함께 사용한다. 두 인스턴스를 동시에 실행하거나 무중단 리비전 중첩을 허용하면 안 된다.
배포 전 수집을 닫고 온라인 백업의 무결성·체크섬을 검증한 뒤 기존 리비전을 완전히 내려야 한다.
상시 다중 인스턴스·고동시성 운영으로 확장할 때는 국내 리전 관리형 PostgreSQL과 외부 작업 큐로 전환한다.

## 4. 진행자 운영 흐름 (어드민에서)

어드민은 **2단계**다. **(1) 행사 목록**(생성·열기·삭제) → 행사를 열면 **(2) 작업공간**으로 들어가고,
왼쪽 **단계 네비**(개요·회차·수집 현황·AI 숙의·응답자·보고서)로 이동한다. 긴 세로 스크롤이 아니라
단계별 화면이다.

1. **행사 목록**에서 **행사 만들기** → 제목 입력(만들면 작업공간으로 이동).
2. **회차**: 회차 제목·서문·(선택)첨부 자료·**전문가 안(번호·제목·설명, 폼으로 입력)**·연령대 물어보기 여부. 공개/마감/삭제.
3. **공개** → 시민이 응답 시작. **수집 현황**에서 응답 수·안별 분포·연령대 실시간 확인.
4. **마감** → **AI 숙의** 단계에서 **실행**(버튼 하나). 진행률·취소·실패 재시도. **6단계 회의 과정이 메인으로** 표시된다(독립안→각자수정안→취합→수정요청→투표→최종).
5. 결과 = **통합 추가 안 + 반영/트레이드오프/미반영(정직 노출)**. **사람 수정 / 전문가회의 보강** 가능(수정 시 승인 자동 무효화).
6. **승인**(human_gate) → **→ 다음 회차 설문으로**(원안 + AI안). ‘회차’에서 다시 공개해 재수집.
7. **응답자**: 100명 개개인을 한 명씩 — 누구인지(가상=페르소나 전문) + 회차별 입장·이유·이동표.
8. **보고서**: 참여 구성·회차별 수용도·**이동(같은 사람 입장 변화)**·정성 의견·AI 근거·**비대표성 고지**.

시민은 같은 기기로 다음 회차에 자동으로 이어진다(참여 코드 = 이동 연결 키).

## 5. AI 숙의 구성 (시스템 설정, 운영자 화면엔 숨김)

`ai_config.py`에서 조정. 운영자는 "숙의 실행" 버튼만 누른다.

- **초안가 = 한국 주권 LLM 3사**: EXAONE(LG)·Solar(Upstage)·HCX(Naver). 해외 모델(GLM·Qwen 등) 배제.
- **숙의 = 6단계 프로토콜 v2** (`deliberate.py`): ①독립안 ②각자 수정안(다른 안 보고 보강) ③취합 통합안 ④수정 요청 ⑤수정범위 투표(과반) ⑥반영. 3사가 **투명한 누적 스레드**로 전 과정을 함께 보며 매 단계 드리프트를 서로 감시한다.
- **판정기 분리**: 별도 병합 모델을 두는 대신, 취합·최종을 로테이션하고 수정안을 3사 **투표(3중 2)**로 상쇄한다.
- **가드(실행 경로 강제, fail-closed)**:
  - 활성 독파모 독립 회사 **≥3** (`assert_min_companies`) — 미만이면 숙의 거부
  - **단일 정밀 수치 금지**(예: "47.3%") → 방향·범위로 (잔존 시 발표 전 사람 확인 경고, G10)
  - AI 산출은 **정량 수치 권위 주장 금지**(프롬프트)
- 실제 실행된 모델·회사는 보고서 provenance로 노출(숨김 ≠ 무력화)

## 5.1 프로바이더(모델 공급자) 추가하기

`ai_config.py`의 레지스트리로 분리돼 있어 **엔드포인트·모델 추가가 쉽다**.

1. **`PROVIDERS`에 한 줄** — OpenAI 호환이면 코드 수정 0:
   ```python
   "myprov": {"kind": "openai", "base": "https://.../v1", "env": "MY_API_KEY", "max_tokens": 8000,
              "extra": {}},  # extra=요청에 항상 붙일 파라미터
   ```
   특수 포맷(예: CLOVA)이면 `kind`를 새로 두고 `llm.py`의 `_DISPATCH`에 함수 1개 추가.
2. **`.env`에 키** (`MY_API_KEY=...`). 키가 있으면 `is_enabled`가 자동 활성.
3. **`DOKPAMO` 로스터에 한 줄** — `{"label","company","provider":"myprov","model":"..."}`.

현재: friendli(EXAONE)·upstage(Solar)·clova(HCX) **3사 활성**. **sktax(A.X)는 유효 키 대기**(로스터에 주석 처리, 키 오면 한 줄 해제).
활성 독파모가 3사 미만이면 숙의는 가드로 거부된다(fail-closed).

## 6. 시뮬레이션 돌리기 (엔진 검증·규모 시연)

실제 청중 전에 **가상 응답자**로 파이프라인을 검증한다. `.env`에 독파모 키 필요.

```bash
.venv/bin/python simulate.py
```

- `AIPOL_SYNTHETIC_PERSONAS_PATH`로 지정한 합성 페르소나를 사용합니다. 기본값은 소수의 공개 예제입니다.
- 각 합성 페르소나를 활성 모델 중 하나에 배정하고 자기 대화 세션에서 1차 응답을 생성합니다.
- 마감 → AI 숙의 → 승인 → 2차(원안+AI안) → **동일 페르소나·동일 모델·동일 세션**으로 재투표 → **이동 추적**
- 결과는 어드민 종합 보고서에서 확인합니다. 합성 스레드 산출물은 공개 저장소에 커밋하지 않습니다.

> ⚠️ 가상 응답자 = 합성 페르소나. **실제 여론 아님·대표성 없음.** 엔진·정직 노출 검증용.

### 연구반 합성 검토 링크

실제 참가자 수집을 열기 전에는 `collection_enabled=false`로 동결한 실험에 합성 참가자를 등록해 전체 화면과 절차를 검토합니다. 이 경로는 실제 참가자 등록을 열지 않으며, 외부 계산기 완료 영수증과 실제 참가자 M2 마감도 요구하지 않습니다. 대신 편집자와 승인자가 분리된 계정으로 미리 승인한 E1a·E1b·E2 대체 자료만 표시합니다.

합성 참가자 토큰은 주소의 fragment에만 넣습니다.

```text
https://session.aipol.kaps.or.kr/aipol.html?experiment={실험ID}#review_token={합성참가자토큰}
```

브라우저는 주소에서 fragment를 먼저 지운 뒤 서버에서 합성 검토 권한을 확인하고, 검증된 토큰만 로컬 저장소에 보관합니다. 기본 유효기간은 7일이며 `AIPOL_SYNTHETIC_REVIEW_TTL_SECONDS`로 15분~30일 범위에서 조정할 수 있습니다. 운영자는 `POST /api/admin/aipol/experiments/{실험ID}/synthetic-participants/{review_id}/revoke`로 링크를 즉시 폐기할 수 있습니다. 이 링크는 참가 권한을 가진 비밀 링크이므로 공개 저장소, 공개 이슈, 검색 가능한 문서에 기록하지 않습니다.

## 7. 신뢰·정직 원칙

- **빠짐없음 계약**: 모든 안에 응답해야 제출(조건부는 의견 필수). 서버에서 재검증.
- **중복 차단**: 1인 1참여코드 + `UNIQUE(회차, 참여자)`.
- **human_gate**: 미승인 안은 다음 회차로 못 나감. 사람 수정 시 승인 자동 무효화 → 재승인.
- **정직 노출**: 반영·트레이드오프·**미반영을 채택 안과 동급으로** 표시.
- **비대표성 고지**: 보고서 상단 제거 불가 요소. 가상/실제 참여자 분리 집계.

## 8. 파일 안내

### AIPOL 공개 등록과 계산기 receipt 운영 계약

- 참여코드는 16~128자이며 공백 없이 대·소문자, 숫자, 기호 중 3종 이상을 사용한다. 사람이 정한 행사명·날짜 조합은 금지하고 비밀번호 생성기로 발급한다.
- 잘못된 참여코드만 실험·remote 단위 제한과 전역 실패 예산에 누적된다. 정상 등록은 예산을 소비하지 않는다. 관련 환경 변수는 `AIPOL_REGISTRATION_FAILURE_WINDOW_SECONDS`, `AIPOL_REGISTRATION_FAILURES_PER_REMOTE`, `AIPOL_REGISTRATION_GLOBAL_FAILURE_BUDGET`, `AIPOL_REGISTRATION_RATE_MAX_KEYS`다.
- 이 실패 제한은 bounded in-memory 상태다. 따라서 반드시 단일 replica·단일 worker로 운영한다. 전달 헤더는 기본적으로 무시하며, 운영자가 확인한 ingress CIDR만 `AIPOL_TRUSTED_PROXY_CIDRS`에 명시할 수 있다. 다중 replica 전환 전에는 공유 rate-limit 저장소로 교체해야 한다.
- 외부 계산기가 없는 환경은 `AIPOL_RECEIPT_VERIFIER_MODE=disabled`로 두며 E1a 완료가 fail-closed 된다. 활성화하려면 `ed25519_jws`, `AIPOL_RECEIPT_ED25519_PUBLIC_KEY_B64`, `AIPOL_RECEIPT_KEY_ID`를 설정한다.
- 계산기는 flattened JWS JSON(`protected`, `payload`, `signature`)을 발급한다. `alg=EdDSA`, `typ=JWT`, 동결된 `kid`를 사용하고 payload에 `jti`, `iss`, `aud`, `iat`, `exp`, `experiment_id`, `experiment_version`, `session_id`, `participant_pseudonym`, `artifact_id`, `artifact_hash`, `contract_hash`를 넣는다. 기본 최대 유효기간은 600초이며 `AIPOL_RECEIPT_MAX_TTL_SECONDS`로 줄일 수 있다. `jti`는 실험 전체에서 한 번만 사용할 수 있다.
- 참여자 UI는 `aipol-calculator-return-v2` 계약으로 승인된 exact HTTPS origin의 clean URL만
  `noopener,noreferrer`로 열고 fragment에 제한된 context와 same-origin 복귀 URL만 전달한다.
  복귀 페이지의 `BroadcastChannel`로 flattened JWS를 받으며, 자동 전달 미지원 또는 시간초과 때만
  수동 입력을 열고 서버가 서명과 행사 context를 최종 검증한다. 계산 정본과 E1a artifact는
  같은 `integration_contract_version` 및 브라우저 E2E `integration_test_hash`를 가져야 한다.

| 파일 | 역할 |
|---|---|
| `server.py` | FastAPI 라우트(시민·진행자·숙의 잡·보고서) + 인증 |
| `db.py` | SQLite 저장(행사·회차·참여자·응답·잡·숙의·보고서 집계) |
| `ai_config.py` | 독파모 로스터·가드 파라미터·프롬프트(시스템 설정) |
| `llm.py` | 독파모 dispatch(단일턴·멀티턴) |
| `deliberate.py` | 숙의 로직 + 가드 + 잡 러너 |
| `simulate.py` | 가상 응답자 2회차 누적-스레드 시뮬 |
| `web/` | 시민(`index.html`)·진행자(`admin.html`) 화면 + CSS/JS |
| `instances/` | 예제 케이스 데이터(서문·안·첨부) |

## 10. 한계 (정직)

- 가상 응답자는 합성 페르소나 — 실제 민의 대리·예측 아님.
- 현재 MVP 필수 경로(준비→수집→숙의→승인→다음 회차→보고서) 구현. 전면 undo·발표 모드·리허설
  모드·객체별 완전 CRUD는 후속.
- AI 숙의는 외부 독파모 API 의존(키·네트워크 필요). 로컬 모델 대체 시 분산·품질 달라질 수 있음.
