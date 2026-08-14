# 해외 정책동향 봇

공식 정부·국제기구 출처에서 정책개발 관련 항목을 수집하고 한국어 검토 레코드를 만드는 작업이다.
운영 정기 작업은 공개 사이트나 RSS를 자동 수정하지 않는다. 결과 공개는 사람 검토와 별도 Pull
Request 승인 뒤에만 가능하다.

## 운영 상태

- 일정: 매일 06:00 KST (`0 21 * * *` UTC)
- 실행 환경: Azure Container Apps Job `aipol-policy-news-daily`
- 수집 한도: 실행당 공식 출처 최대 3건
- 원문 분석: AIPOL 전용 Naia 계정의 `upstage:solar-pro4`
- 분석 검증·근거 기반 교정: `azure:deepseek-v4-pro`
- 한국어 번역: `azure:gpt-5.6-luna`
- 최종 적대검토: `azure:deepseek-v4-flash`
- 저장: 비공개 Azure Blob `policy-news-sources`, `policy-news-runs`
- 공개: 자동 게시 없음

2026년 7월 31일 수동 운영 실행으로 원문 3건과 실행 레코드 3건을 확인한 뒤, 같은 이미지와 설정
지문에 대해서만 일정을 활성화했다. 자세한 증거는
실제 실행 영수증과 공급자 호출 기록은 공개 저장소가 아닌 비공개 운영 저장소에 기록한다.

## 편집·검토 계약

1. 허용 목록에 있는 공식 정부·국제기구 출처만 사용한다.
2. 원문 전체를 재게시하거나 완역하지 않고 정책적 의미를 요약한다.
3. AI 활용, 사람 검토 필요 사항, AIPOL 관련성, 한계를 분리한다.
4. 초안·검토 모델, 검토 시각, 대조 범위와 지적 사항을 기록한다.
5. 키 누락, 공급자 오류, 형식 오류, 필수 대조 누락은 실패로 닫는다.
6. 검토 지적은 `BLOCK` 레코드로 보존하고 자동 공개하지 않는다.
7. 자동화는 사이트·RSS·Git 브랜치·Pull Request를 수정하지 않는다.

## 구성 요소

- `collector.py`: 허용된 공식 Atom 피드에서 최대 3건을 수집한다. 리디렉션, 응답 크기, 시간,
  추출 문자의 상한을 둔다.
- `adapters.py`: Naia AnyLLM 한 계정에서 Solar 분석 → DeepSeek Pro 검증·교정 → Luna 번역 → DeepSeek Flash
  적대검토를 수행한다. 최상위 필드, 필수 대조 항목,
  issue 필드와 심각도, 판정 일관성을 모두 검증한다.
- `orchestrator.py`: 호출 횟수·비용 예약·재시도·중단 규칙을 적용하고 단계별 레코드를 남긴다.
- `azure_blob_store.py`: 조건부 쓰기, 실행 간 임대, SHA 주소 원문을 비공개 Blob에 저장한다.
- `scheduled_job.py`: 관리 ID와 Key Vault 참조를 사용하는 운영 진입점이며 게시 동작이 없다.
- `Dockerfile`: 고정된 기반 이미지와 비루트 사용자로 실행한다.

## 로컬 검증

기본값은 비활성·드라이런이다. 실제 공급자 호출에는 명시적인 운영 환경변수와 비밀키가 필요하다.
키를 소스, 이미지, 사이트, Pull Request에 넣지 않는다.

```bash
python bots/policy_news/bot.py --dry-run --max-items 3
python -m pytest tests/test_policy_news_bot.py tests/test_policy_news_prod_deployment.py -q
```

운영 IaC와 수동 실행→일정 활성화 절차는
[`deploy/azure/policy-news-prod/README.md`](../../deploy/azure/policy-news-prod/README.md)를 따른다.

## 비용·권한 경계

- 상시 실행 VM 없이 하루 한 번만 작업한다.
- 실행당 최대 3건, 최대 9회 공급자 호출 예약, 보수적 비용 상한 2달러를 적용한다.
- AIPOL 전용 AnyLLM 계정에는 별도 월 예산을 둔다.
- 전용 관리 ID는 두 공급자 비밀을 각각 읽을 수 있고 다른 Key Vault 비밀은 읽지 못한다.
- 두 Blob 컨테이너에는 read/write/add만 허용하고 삭제 권한은 주지 않는다.
- 이미지 다이제스트, 공급자 품질 증거, 비밀 버전, 모델, 실행 한도와 수동 성공 증빙이 일치해야
  정기 일정을 활성화할 수 있다.
