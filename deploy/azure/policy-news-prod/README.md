# 해외 정책 동향 일일 작업 운영

이 디렉터리는 `rg_aipol`의 Azure Container Apps Job을 정의합니다. 작업은 매일 오전 6시(한국시간)에 최대 3개의 해외 공식기관 자료를 수집하고, AIPOL 전용 Naia 계정에서 Solar Pro 4 분석 → DeepSeek V4 Pro 검증·근거 기반 교정 → GPT-5.6 Luna 번역 → DeepSeek V4 Flash 적대검토를 수행합니다.

결과는 비공개 Blob 컨테이너에만 저장합니다. 공개 사이트 게시, Git 커밋, 병합, 사람 승인 처리는 수행하지 않습니다. 검토 결과가 `PASS`여도 자동 공개하지 않습니다.

## 품질과 권한 경계

- 사전 품질 표본은 공식 GOV.UK 원문으로 평가했습니다.
- 원문·초안·검토 전문은 비공개 저장소에 보관하고, 이 저장소에는 SHA-256만 기록합니다.
- 전용 관리 ID만 사용하며 참여자·관리자 서비스의 ID와 공유하지 않습니다.
- 작업이 꺼져 있으면 Naia 비밀과 Blob 쓰기 권한을 연결하지 않습니다.
- Upstage 직접 키는 연결하지 않고 Solar도 Naia 게이트웨이를 통해 호출합니다.
- AnyLLM 주소는 `https://api.nextain.io/v1`로 고정합니다.
- 모델은 `upstage:solar-pro4`, `azure:deepseek-v4-pro`, `azure:gpt-5.6-luna`, `azure:deepseek-v4-flash`로 고정합니다.
- Blob 사용자 정의 역할은 읽기·쓰기만 허용하고 삭제 권한은 포함하지 않습니다.
- 이미지 태그는 거부하며 검증한 ACR digest만 배포합니다.

## 배포 순서

1. Bicep과 테스트를 검증합니다.
2. 깨끗한 커밋에서 이미지를 빌드하고 digest를 확인합니다.
3. `policyNewsEnabled=true`, `enableSchedule=false`로 수동 작업을 배포합니다.
4. 수동 실행 후 실행 상태, 비공개 Blob 기록, 호출 수와 비용, 자동 공개가 없음을 확인합니다.
5. 수동 실행 영수증의 SHA-256과 동일 이미지 digest를 넣은 경우에만 `enableSchedule=true`로 전환합니다.

```powershell
az bicep build --file deploy/azure/policy-news-prod/main.bicep
az containerapp job start --resource-group rg_aipol --name aipol-policy-news-daily
az containerapp job execution list --resource-group rg_aipol --name aipol-policy-news-daily -o table
```

예약식 `0 21 * * *`은 UTC 기준이며 한국시간 오전 6시입니다. 병렬 실행 수는 1, 재시도는 0으로 고정합니다.

## 즉시 중단

`policyNewsEnabled=false`, `enableSchedule=false`로 다시 배포합니다. 이 상태에서는 런타임 비밀 참조와 공급자·Blob 데이터 권한도 제거됩니다.
