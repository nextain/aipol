# AIPOL public-site deployment

This deployment publishes the static content in `site/` only. It does not deploy the stateful `event-tool/`, a
database, AI workloads, participant data, DNS records, or custom-domain bindings.

## Environment contract

| Environment | Resource group | Static Web App | Custom-host intent |
|---|---|---|---|
| Production | `rg-aipol-prod` | `swa-aipol-prod` | `aipol.kaps.or.kr` |
| Development | `rg-aipol-dev` | `swa-aipol-dev` | not assigned by default |

- Azure Static Web Apps region: `eastasia` (the service is not offered in Korea Central).
- SKU: Free.
- Search remains disabled by the HTML, response-header, and `robots.txt` controls in `site/`.
- The resource groups are environment boundaries and must already exist. The group-scoped Bicep template neither
  creates resource groups nor moves resources between them.
- `aipol.kaps.or.kr` is the temporary public-host intent. The template stores that intent as a tag; it does not
  create an Azure custom-domain resource or change DNS.
- `aipol.kaps.or.kr` is the future official host. Its cutover requires KAPS DNS authority and a separate reviewed
  release; it is not an alias that this template silently activates.

The old `rg-nextain-koreacentral` / `swa-nextain-policy-lab` deployment is historical and is not a target of this
template or workflow. Deployment receipts remain in the private operations repository.

## Validate without changing Azure

The repository gate compiles all four AIPOL deployment units and is also run by
`.github/workflows/verify-azure-bicep.yml`:

```bash
python scripts/verify_azure_bicep.py
```

The optional protected workflow job passes `--validate-resource-group` and performs ARM `validate` only; it never
uses `deployment group create`. The commands below show the equivalent public-site validation. The two `validate` commands ask Azure Resource Manager to validate each
environment deployment without creating or updating resources.

```bash
az bicep build --file deploy/azure/public-site.bicep

az deployment group validate \
  --resource-group rg-aipol-prod \
  --template-file deploy/azure/public-site.bicep \
  --parameters environment=prod

az deployment group validate \
  --resource-group rg-aipol-dev \
  --template-file deploy/azure/public-site.bicep \
  --parameters environment=dev
```

Use `what-if` after validation when an environment already contains resources and the exact delta needs review:

`python scripts/verify_azure_bicep.py --validate-resource-group rg-aipol-dev` uses explicit development parameters
for every template and emits one `ARM_VALIDATE_RECEIPT` per unit. The receipt lists branches exercised by ARM and
branches intentionally left inactive, so a successful default-OFF validation cannot be mistaken for coverage of an
enabled deployment. Validation is hard-restricted to `rg-aipol-dev`; it does not deploy resources. In particular,
model/quota discovery, versioned secrets, an attested KB receiver, and container-image pullability remain separate
activation evidence.

```bash
az deployment group what-if \
  --resource-group rg-aipol-prod \
  --template-file deploy/azure/public-site.bicep \
  --parameters environment=prod
```

## Provisioning (human gate)

The following commands change shared Azure state. Run them only after the reviewed change is approved.

```bash
az deployment group create \
  --resource-group rg-aipol-dev \
  --template-file deploy/azure/public-site.bicep \
  --parameters environment=dev

az deployment group create \
  --resource-group rg-aipol-prod \
  --template-file deploy/azure/public-site.bicep \
  --parameters environment=prod
```

The default names are derived from `environment`. For a deliberate exception, pass `name=<resource-name>` and
record the reason in the deployment review.

## Static-content upload

The local and CI browser gate use the same declared test dependencies and Chromium installation:

```bash
python -m pip install -e ".[test]"
python -m playwright install --with-deps chromium
python -m pytest -q tests/test_public_site.py tests/test_aipol_metadata.py tests/test_public_site_browser.py
```

Store each Static Web App deployment token in the matching repository secret:

- `AZURE_STATIC_WEB_APPS_API_TOKEN_AIPOL_DEV`
- `AZURE_STATIC_WEB_APPS_API_TOKEN_AIPOL_PROD`

Create protected GitHub environments `aipol-dev` and `aipol-prod`. Set `AIPOL_DEV_URL` on `aipol-dev`, and require
reviewers for `aipol-prod`. The repository currently references these gates but does not create the environments,
secrets, variables, Static Web Apps, or Azure resources automatically.

Then manually run **Deploy AIPOL public site to Azure** and select `dev` or `prod`. The token selects the actual
Azure resource; the workflow never accepts an arbitrary resource group or resource name. A production run always
deploys and live-verifies the same `${{ github.sha }}` in `aipol-dev` before the protected `aipol-prod` job can run.
Static and responsive-browser tests are mandatory release gates.

## Custom-domain sequence

Domain work is intentionally separate from Bicep provisioning and content upload.

1. Deploy and verify the Azure default hostname.
2. Add `aipol.kaps.or.kr` to `swa-aipol-prod` in Azure and obtain Azure's required validation record.
3. Review and change the authoritative DNS record, then wait for Azure certificate issuance.
4. Verify HTTPS, redirects, canonical/OG URLs, security headers, and rollback behavior on the custom host.
5. When KAPS authorizes `aipol.kaps.or.kr`, repeat validation for that host and switch canonical metadata only in
   the reviewed official-domain release. Keep or retire the temporary host by an explicit redirect decision.

Do not point DNS at an unverified default hostname, and do not publish the future KAPS hostname as live before its
certificate and site responses are verified.

### `aipol.kaps.or.kr` 위임 요청값

`aipol.kaps.or.kr`처럼 하위 도메인만 별도 DNS 영역으로 운영할 수 있다. KAPS가 관리하는
`kaps.or.kr` 상위 영역에 **호스트 이름 `aipol`의 NS 레코드 4개**를 추가하면 된다. 2026-07-29
Azure DNS 자식 영역에서 확인한 위임 대상은 다음과 같다.

```text
ns1-06.azure-dns.com.
ns2-06.azure-dns.net.
ns3-06.azure-dns.org.
ns4-06.azure-dns.info.
```

이는 `kaps.or.kr` 전체 네임서버를 변경하는 요청이 아니다. `aipol` 하위 영역만 위임한다. 발송 전
Azure Portal 또는 `az network dns zone show --resource-group rg-aipol-prod --name aipol.kaps.or.kr`
결과와 위 네 값을 다시 대조한다.

메일/메시지 초안:

> 제목: aipol.kaps.or.kr 하위 도메인 DNS 위임 요청
>
> 안녕하세요. 한국정책학회 AIPOL 정책실험 공식 사이트 연결을 위해 `aipol.kaps.or.kr` 하위
> 도메인의 DNS 위임을 요청드립니다. `kaps.or.kr` DNS에서 호스트 이름 `aipol`에 아래 NS 레코드
> 4개를 추가해 주세요: `ns1-06.azure-dns.com.`, `ns2-06.azure-dns.net.`,
> `ns3-06.azure-dns.org.`, `ns4-06.azure-dns.info.` 이 변경은 `kaps.or.kr` 전체 네임서버 교체가
> 아니라 `aipol.kaps.or.kr` 하위 영역만 위임하는 설정입니다. 반영 후 회신 부탁드립니다.

위임 확인은 `Resolve-DnsName -Type NS aipol.kaps.or.kr`로 수행한다. 네 NS가 모두 반환된 뒤에만
Static Web Apps 사용자 지정 도메인 검증을 진행한다.
