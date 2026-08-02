# AIPOL 행사 도구 전용 운영 Azure IaC

이 디렉터리는 AIPOL 행사 도구의 전용 운영 스택을 빈 리소스 그룹 `rg_aipol`에 새로 만드는 Bicep 정본입니다. 현재 `rg-nextain-koreacentral`에서 서비스 중인 앱과 데이터는 수정하거나 가져와 관리하지 않습니다. 새 앱을 기본 Azure 주소로 검증한 뒤에만 DNS를 수동 전환합니다.

## 생성되는 전용 자원

| 구분 | 고정 이름 |
|---|---|
| 리소스 그룹 | `rg_aipol` |
| Azure Container Registry | `acraipolprod01` |
| 승인 이미지 저장소 | `policy-lab-event` |
| Container Apps 환경 | `cae-aipol-prod` |
| Container App | `aipol-session-prod` |
| Storage Account | `staipolprod01` |
| Azure Files | `eventdata` |
| 환경 저장소 연결 | `eventstore` |
| Key Vault | `kv-aipol-prod-01` |
| 사용자 할당 관리 ID | `uami-aipol-prod` |
| 감사 Blob | `aipol-audit-checkpoints` |

기존 DNS zone `aipol.kaps.or.kr`은 `rg-nextain-koreacentral`의 외부 참조로만 선언합니다. 템플릿에는 DNS record, custom domain, 관리 인증서 변경이 없습니다.

## 코드로 고정한 보안 경계

- 배포 대상 리소스 그룹은 정확히 `rg_aipol`이어야 합니다.
- 리소스 이름은 단일 허용값으로 고정합니다.
- 이미지는 정확히 `acraipolprod01.azurecr.io/policy-lab-event@sha256:<64 lowercase hex>` 형식이어야 합니다.
- ACR 관리자 계정과 익명 pull은 비활성화하고 관리 ID에 `AcrPull`만 부여합니다.
- 외부 HTTPS ingress, 단일 revision, replica 1개로 고정합니다.
- Container App 명령에서도 `uvicorn --workers 1 --no-proxy-headers`를 강제합니다.
- 수집, 공개 챗봇, 배치, receipt verifier는 허용값 자체가 `false`입니다.
- 관리자 비밀번호는 scrypt 해시, 모든 운영 계정은 TOTP 비밀을 가져야 합니다.
- 런타임 비밀은 이름 있는 Key Vault secret 각각에 읽기 권한을 주고 정확한 버전 URL로 고정합니다.
- 감사 컨테이너는 versioning과 365일 보존 정책을 만들며 앱에는 읽기/생성 권한만 부여합니다.
- 감사 정책을 사람이 잠근 뒤 정책 ID와 ETag를 넣지 않으면 앱 생성 조건이 false가 되어 배포가 차단됩니다.
- 과거 SQLite 백업은 불변 감사 checkpoint보다 뒤처질 수 있으므로, 서명된 복구 계보 프로토콜이
  구현되기 전까지 운영 백업 API는 503으로 닫힙니다.
- Storage Blob 공개 접근은 끄고 TLS 1.2와 HTTPS를 강제합니다.

`collection_enabled`의 실제 값은 DB의 실험 manifest가 관리합니다. IaC가 기존 데이터를 자동으로 켜거나 끄지 않으므로 DB 복원 전후에도 모든 실험의 수집 OFF를 확인해야 합니다.

연구반의 화면·절차 검토는 실제 수집과 분리합니다. `collection_enabled=false` 동결 실험에 합성 참가자를 만들고, `#review_token=` fragment를 사용한 비밀 링크로만 배포합니다. 합성 검토는 승인된 대체 자료로 전 과정을 확인할 수 있지만 실제 참가자 등록, 계산기 영수증 검증, 실제 M2 마감·E2 공개 조건을 우회하지 않습니다. 링크는 기본 7일 후 만료되며 교체·유출 시 관리자 폐기 API로 즉시 무효화합니다. 검토 링크와 토큰은 Key Vault 또는 비공개 운영 저장소에만 보관합니다.

## 비밀 이름

실제 값과 TOTP seed는 Git, 매개변수 파일, CI 로그, 단체 채팅에 넣지 않습니다.

| Key Vault secret | 런타임 환경 변수 |
|---|---|
| `event-session-secret` | `EVENT_SESSION_SECRET` |
| `event-admin-users-json-b64` | `EVENT_ADMIN_USERS_JSON_B64` |
| `event-admin-roles-json-b64` | `EVENT_ADMIN_ROLES_JSON_B64` |
| `event-admin-totp-secrets-json-b64` | `EVENT_ADMIN_TOTP_SECRETS_JSON_B64` |
| `event-credential-secrets-json-b64` | `EVENT_CREDENTIAL_SECRETS_JSON_B64` |
| `event-audit-checkpoint-secrets-json-b64` | `AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON_B64` |

비밀은 승인된 로컬 보안 터미널에서 등록하고, 값이 출력되지 않는 명령으로 각 secret ID의 마지막 버전만 확인합니다.

## 배포 순서

예제 파일을 Git에 추적되지 않는 `main.parameters.prod.json`으로 복사합니다. 모든 배포 전에 먼저 `what-if`를 검토합니다.

### 1. 전용 기반 자원 생성

`deployFoundation=true`, `manageAuditPolicy=true`, `configureRuntimeAccess=false`, `deployApp=false`로 배포합니다.

```powershell
az deployment group what-if `
  --resource-group rg_aipol `
  --template-file deploy/azure/event-tool-prod/main.bicep `
  --parameters '@deploy/azure/event-tool-prod/main.parameters.prod.json'

az deployment group create `
  --resource-group rg_aipol `
  --template-file deploy/azure/event-tool-prod/main.bicep `
  --parameters '@deploy/azure/event-tool-prod/main.parameters.prod.json'
```

이 단계는 기존 서비스, 기존 DB, DNS를 변경하지 않습니다.

### 2. 이미지와 비밀 준비

승인한 소스에서 이미지를 전용 ACR의 `policy-lab-event`에 올립니다. ACR이 반환한 digest를 다시 읽어 정확한 64자리 소문자 SHA-256을 매개변수에 넣습니다. 태그만 넣으면 `immutableImageAccepted=false`가 되고 앱 생성이 차단됩니다.

Key Vault에 여섯 비밀을 등록합니다. 비밀번호 JSON은 평문 비밀번호가 아니라 scrypt 해시만 포함하고, 운영 계정마다 역할과 TOTP seed가 있어야 합니다. 그 뒤 `configureRuntimeAccess=true`, `deployApp=false`로 최소 권한을 적용합니다.

### 3. 감사 정책 잠금

새 감사 정책이 365일 `Unlocked` 상태로 만들어졌는지 먼저 확인합니다. 승인된 운영자가 Azure의 별도 잠금 작업을 수행합니다. 잠금은 되돌릴 수 없으므로 컨테이너 이름, 보존기간, 대상 리소스 그룹을 다시 확인합니다.

잠금 뒤에는 `manageAuditPolicy=false`로 바꿔 이후 배포가 잠긴 정책을 다시 PUT하지 않게 합니다. GET 결과가 `state=Locked`인지 확인하고 `<policy-resource-id>:<etag>`를 `auditImmutabilityLockEvidenceId`에 기록합니다. 확인 없이 플래그만 true로 바꾸면 안 됩니다.

### 4. 새 운영 DB 초기화

기존 서비스에는 운영 검증용 실험 1건과 참여자·측정값 0건만 있으므로 기존 DB를 복제하지 않습니다.
새 `staipolprod01/eventdata`에서 빈 DB를 초기화해 새 `db_instance_id`와 새 불변 감사 계보로
시작합니다. 기존 DB와 감사 Blob은 배포 증거로 보존하되 새 운영 계보에 섞지 않습니다.

과거 DB를 그대로 복원하면 불변 감사 저장소가 SQLite보다 앞서 시작이 차단됩니다. 역사적
checkpoint, 백업 해시, 별도 복구 서명키를 연결하는 recovery-lineage v2가 구현·검증되기 전에는
운영 DB 복원을 시도하지 않습니다.

### 5. 새 앱 생성과 기본 주소 검증

모든 비밀 버전, 활성 key ID, 이미지 digest, 감사 잠금 증거와 함께 `reviewBuildCommit`,
`reviewDbSeedHash`, `reviewDeploymentRevision`, `reviewPublicOrigin`을 실제 배포 영수증 값으로 고정한 뒤
`deployFoundation=true`, `configureRuntimeAccess=true`, `deployApp=true`, `manageAuditPolicy=false`로 배포합니다.
`reviewDeploymentRevision`은 `aipol-session-prod--<revisionSuffix>` 전체 이름과 정확히 같아야 합니다.
하나라도 비었거나 형식이 다르면 앱 리소스를 만들지 않습니다. 이때도 DNS는 바뀌지 않습니다.

Container App의 기본 Azure FQDN으로 다음을 확인합니다.

1. 정확히 revision 1개와 replica 1개가 Healthy
2. `/healthz`, `/readyz` HTTP 200
3. `collection_ready=false`, receipt verifier disabled
4. MFA 로그인과 작성자/승인자 역할 분리
5. 빈 운영 DB, 새 DB instance, 감사 bootstrap checkpoint 정상
6. `robots.txt`와 모든 응답의 noindex 정책
7. 재시작 뒤 Azure Files의 DB 유지

### 6. DNS와 custom domain 수동 전환

기존 DNS zone은 이 템플릿이 수정하지 않습니다. 기본 주소 검증이 끝난 뒤 별도 변경 창에서 다음 순서로 진행합니다.

1. 새 Container App의 custom-domain verification ID 확인
2. 기존 zone에 Azure가 요구하는 TXT/CNAME 검증 record 추가
3. `session.aipol.kaps.or.kr`을 새 앱에 hostname으로 추가
4. 관리 인증서 발급과 SNI 연결 완료 확인
5. HTTPS, 인증, DB, 감사 로그 재검증
6. DNS TTL이 지난 뒤 트래픽 전환 확인

전환 전까지 기존 서비스가 정본입니다. 전환 실패 시 DNS를 기존 대상에 유지하거나 되돌리고 새 앱을 조사합니다. 기존 서비스와 저장소는 새 운영 스택의 안정화 및 복구 검증이 끝날 때까지 삭제하지 않습니다.

## Azure Files 제약

Container Apps의 Azure Files 환경 저장소는 현재 계정 키를 요구하므로 `allowSharedKeyAccess=true`가 남습니다. 기본 Container Apps 환경에 private endpoint/VNet 경로도 없으므로 저장소 public network를 즉시 차단하면 DB mount가 실패할 수 있습니다. 대신 Blob 공개 접근 금지, HTTPS/TLS 1.2, 계정 키 비노출, 전용 계정과 단일 앱 사용으로 경계를 줄입니다.

SQLite/Azure Files는 단일 replica·단일 worker·직렬 HTTP에서만 허용합니다. 무중단 중첩 revision, 다중 replica, 병렬 worker, 두 앱의 동시 mount를 금지합니다. 상시 공개 수집이나 확장이 필요하면 국내 리전 관리형 PostgreSQL과 외부 작업 큐로 이전합니다.

## 롤백

- DNS 전환 전: 기존 서비스가 계속 정본이므로 새 앱을 중지하고 수정합니다.
- DNS 전환 후: DNS를 기존 서비스로 되돌리고 전환 시점 이후 쓰기 여부를 조사합니다.
- 앱: 마지막 승인 digest와 비밀 버전으로 재배포합니다.
- DB: 현재 운영 백업·복원은 fail-closed입니다. recovery-lineage v2 전에는 DNS를 기존 서비스로
  되돌리고 새 DB를 임의 복원하지 않습니다. 이미지 롤백은 schema를 되돌리지 않습니다.
- Key Vault: 값을 덮어쓰지 않고 이전 승인 버전으로 pin을 되돌립니다.

## 정적 검증

```powershell
az bicep build --file deploy/azure/event-tool-prod/main.bicep
git diff --check -- deploy/azure/event-tool-prod
```

생성되는 `main.json`은 빌드 산출물이므로 커밋하지 않습니다.
