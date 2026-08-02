# AIPOL event-tool development backend

This directory is a self-contained deployment unit for the **stateful development backend only**. It targets
`rg-aipol-dev`; it does not deploy or change the public site, policy-news job, DNS, production resources, or any
resource group. Nothing in this directory has been deployed by adding these files.

## Safe defaults and boundaries

- `deployInfrastructure=false` and `deployApp=false`: compile and validation are the default operations.
- External ingress is off by default. A separately approved synthetic-review deployment may expose only the
  Container Apps managed HTTPS FQDN; no VM, standalone public IP, DNS, or production resource is declared.
- Collection, chatbot, and batch switches are all `false`; no model API key is accepted by this template.
- Internal ingress uses `EVENT_ENV=development` for the development-only admin workflow. An explicitly approved
  external review deployment switches to `EVENT_ENV=production`, which enforces scrypt password hashes and TOTP
  for every administrator. Demo seeding remains explicitly off in both modes. Neither mode is a production
  deployment.
- The app runs one Uvicorn worker in exactly one Container Apps replica. A deployment-only ASGI wrapper serializes
  HTTP requests because synchronous FastAPI handlers can otherwise overlap in a thread pool.
- SQLite and the provider roster live on a 5-GiB Azure Files share mounted at `/data`. The image runs as fixed
  non-root UID/GID `10001:10001`; startup writes and reads a probe under `/data` and fails before importing the
  application if the mounted share is not writable by that identity.
- A user-assigned managed identity pulls the private ACR image and reads six required version-pinned Key Vault references. ACR admin
  credentials are disabled.
- Receipt verification is disabled by default, so `/readyz` reports `collection_ready=false`. A reviewed full E1a through
  M3 rehearsal can opt in to one version-pinned Ed25519 public-key secret plus exact key ID, issuer, audience, and TTL.
- The template creates Key Vault but never creates secret values. Secret material must not be committed or passed
  as ordinary Bicep parameters.

The current event-tool enforces real collection primarily through each experiment's frozen manifest. The server
consumes `AIPOL_CHATBOT_PUBLIC_ENABLED`, so the public chatbot route is application-level disabled. The
current server has no generic collection environment-variable gate, so this unit does not invent or advertise an
ineffective collection variable. The batch adapter has a separate `AIPOL_BATCH_AZURE_ENABLED=false` default and
requires both a user-assigned managed identity and the exact target Job resource ID. When explicitly enabled, the
identity receives `Container Apps Jobs Operator` only on that one Job; it receives no resource-group-wide role and
no API key. Collection authorization remains the frozen experiment manifest, not an infrastructure variable.

This unit is for development with synthetic data. It is not approval to collect real participant data. Before real
collection, complete the privacy, retention, operator authentication, incident-response, and deletion gates in the
project deployment contract.

Every resource condition checks that the actual Resource Manager target is `rg-aipol-dev`. A command aimed at
another resource group therefore fails closed with no resources created; the `resourceGroupScopeAccepted` output
must be `true` in every reviewed deployment.

## External endpoint quarantine check (read-only)

`session.policylab.nextain.io` is not the AIPOL source of truth or a deployment target of this unit. If it resolves
or returns HTTP 200, that only proves an older external endpoint still responds. Do not use or share it. Before any
release, record its owning subscription, resource group, operator, data store, retention period, and retirement
decision; otherwise keep the release blocked. These checks do not change Azure or DNS state:

```powershell
Resolve-DnsName session.policylab.nextain.io
curl.exe -I https://session.policylab.nextain.io/
az containerapp list --query "[].{name:name,resourceGroup:resourceGroup,fqdn:properties.configuration.ingress.fqdn}" -o table
az resource list --resource-group rg-aipol-dev -o table
az resource list --resource-group rg-aipol-prod -o table
```

A new dynamic service starts internal-only in `rg-aipol-dev`; production remains a separate reviewed deployment.

## Resources

| Resource | Default name/purpose |
|---|---|
| Container Apps environment | `cae-aipol-event-tool-dev` |
| Container App | `ca-aipol-event-tool-dev`, internal ingress, one replica |
| Azure Container Registry | unique `acraipolevt...`, Basic, admin disabled |
| Storage account and file share | unique `staipolevt...` / `event-tool-state` |
| User-assigned identity | `uami-aipol-event-tool-dev` |
| Key Vault | unique `kv-aipol-evt-...`, RBAC and purge protection enabled |

Azure Files SMB environment storage currently uses the storage account key. ARM resolves that key into the
Container Apps environment storage link; it is not stored in the repository. Managed identity is used for ACR and
Key Vault access.

## Managed-identity RBAC drift gate

Run this read-only gate before and after every reviewed deployment. The event identity may have `Key Vault Secrets
User` on exactly the six required named secret scopes, plus the optional receipt public-key scope, never on the vault root.

```powershell
$AipolPrincipalId = az identity show --resource-group rg-aipol-dev --name uami-aipol-event-tool-dev --query principalId -o tsv
$AipolVault = az keyvault list --resource-group rg-aipol-dev --query "[?starts_with(name, 'kv-aipol-evt-')].name | [0]" -o tsv
$AipolVaultId = az keyvault show --resource-group rg-aipol-dev --name $AipolVault --query id -o tsv
$AipolExpectedSecretScopes = @(
  "$AipolVaultId/secrets/event-session-secret",
  "$AipolVaultId/secrets/event-admin-users-json",
  "$AipolVaultId/secrets/event-admin-roles-json",
  "$AipolVaultId/secrets/event-admin-totp-secrets-json",
  "$AipolVaultId/secrets/event-credential-secrets-json",
  "$AipolVaultId/secrets/event-audit-checkpoint-secrets-json"
)
$AipolAssignments = az role assignment list --assignee-object-id $AipolPrincipalId --all -o json | ConvertFrom-Json
$AipolSecretRoles = @($AipolAssignments | Where-Object { $_.roleDefinitionName -eq 'Key Vault Secrets User' })
$AipolVaultWide = @($AipolSecretRoles | Where-Object { $_.scope.TrimEnd('/') -ieq $AipolVaultId.TrimEnd('/') })
if ($AipolVaultWide.Count -ne 0) { throw 'Vault-wide Key Vault Secrets User drift detected; root must remove it.' }
$AipolActualScopes = @($AipolSecretRoles | ForEach-Object { $_.scope.TrimEnd('/') })
foreach ($AipolScope in $AipolExpectedSecretScopes) {
  if ($AipolActualScopes -inotcontains $AipolScope) { throw "Missing secret-scoped role: $AipolScope" }
}
```

If the pre-check finds the known vault-wide drift, stop. A root operator may remove only that exact assignment
after reviewing the resolved principal and vault IDs; this runbook does not authorize an agent to execute it:

```powershell
az role assignment delete --assignee-object-id $AipolPrincipalId --role 'Key Vault Secrets User' --scope $AipolVaultId
```

Then rerun the read-only gate and require all six required named-secret scopes before and after deployment.

## 1. Local verification (no Azure changes)

Run all commands from the repository root.

```powershell
az bicep build --file deploy/azure/event-tool-dev/main.bicep --stdout | Out-Null

docker build `
  --file deploy/azure/event-tool-dev/Dockerfile `
  --tag aipol-event-tool-dev:local `
  .
```

The Dockerfile is intentionally separate from `event-tool/Dockerfile`. Its build context is the repository root so
that the image contains the event-tool modules, the imported `policy_lab` package, and `serialized_app.py`. The
Python base image is pinned by digest. The wrapper queues HTTP requests in this single process; it does not make
Azure Files suitable for multiple workers, replicas, revisions, or maintenance processes.

The Azure Files mount must preserve write access for UID/GID `10001:10001`. Treat a write-probe startup failure as
a deployment blocker and correct the mount permissions; do not remove `USER 10001:10001` or run the service as
root to bypass the check.

Optional local smoke test with synthetic, throwaway state:

```powershell
docker run --rm --name aipol-event-tool-smoke `
  --publish 127.0.0.1:18100:8100 `
  --tmpfs /data `
  --env EVENT_SESSION_SECRET=local-smoke-session-secret-000000000000 `
  --env 'EVENT_ADMIN_USERS_JSON={"operator":"local-smoke-password-0000"}' `
  aipol-event-tool-dev:local
```

In a second terminal, verify `http://127.0.0.1:18100/healthz` and `http://127.0.0.1:18100/readyz`, then stop the
container with `docker stop aipol-event-tool-smoke`. The values above are disposable local examples, not deployment
credentials.

Resource Manager validation evaluates the disabled template and does not create resources:

```powershell
az deployment group validate `
  --resource-group rg-aipol-dev `
  --template-file deploy/azure/event-tool-dev/main.bicep `
  --parameters '@deploy/azure/event-tool-dev/main.parameters.dev.json'
```

## 2. Provision infrastructure (human approval required)

The following sections change shared Azure state. Stop after `what-if` unless the reviewed deployment has explicit
approval.

```powershell
az deployment group what-if `
  --resource-group rg-aipol-dev `
  --template-file deploy/azure/event-tool-dev/main.bicep `
  --parameters '@deploy/azure/event-tool-dev/main.parameters.dev.json' `
               deployInfrastructure=true deployApp=false
```

After approval, create only the storage, registry, environment, identity, Key Vault, and role assignments:

```powershell
az deployment group create `
  --name aipol-event-tool-dev-infra `
  --resource-group rg-aipol-dev `
  --template-file deploy/azure/event-tool-dev/main.bicep `
  --parameters '@deploy/azure/event-tool-dev/main.parameters.dev.json' `
               deployInfrastructure=true deployApp=false
```

Do not substitute `rg-aipol-prod`. This template does not create a resource group and must not be used as a
production deployment shortcut.

## 3. Build and push an immutable image

Get the generated registry name from the deployment output, then build from the repository root. Use a commit SHA
as the tag; never deploy `latest`.

```powershell
$AipolRegistry = az deployment group show `
  --resource-group rg-aipol-dev `
  --name aipol-event-tool-dev-infra `
  --query properties.outputs.registryLoginServer.value `
  --output tsv

$AipolRegistryName = ($AipolRegistry -split '\.')[0]
$AipolImageTag = git rev-parse --short=12 HEAD

az acr build `
  --registry $AipolRegistryName `
  --image "aipol/event-tool:$AipolImageTag" `
  --file deploy/azure/event-tool-dev/Dockerfile `
  .
```

Resolve and record the pushed image digest:

```powershell
$AipolDigest = az acr repository show `
  --name $AipolRegistryName `
  --image "aipol/event-tool:$AipolImageTag" `
  --query digest `
  --output tsv

$AipolImage = "$AipolRegistry/aipol/event-tool@$AipolDigest"
```

Pass `$AipolImage` to `containerImage` during the app deployment.

## 4. Add Key Vault values without putting them in Git

Create these versioned secrets in the generated vault through Azure Portal or an approved secret-management
terminal:

| Key Vault secret | Runtime variable | Requirement |
|---|---|---|
| `event-session-secret` | `EVENT_SESSION_SECRET` | cryptographically random, at least 32 characters |
| `event-admin-users-json` | `EVENT_ADMIN_USERS_JSON` | JSON object; distinct editor and approver accounts; values must be `scrypt-v1` hashes, never plaintext passwords |
| `event-admin-roles-json` | `EVENT_ADMIN_ROLES_JSON` | explicit role lists for every account; editor and approver must be different identities |
| `event-admin-totp-secrets-json` | `EVENT_ADMIN_TOTP_SECRETS_JSON` | base32 TOTP secret for every administrator; distribute provisioning data only through an approved secret channel |
| `event-credential-secrets-json` | `EVENT_CREDENTIAL_SECRETS_JSON` | JSON key-id → 32+ character secret map; retain every key referenced by an active experiment |
| `event-audit-checkpoint-secrets-json` | `AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON` | JSON key-id → 32+ character HMAC secret map for immutable audit checkpoints |
| `aipol-receipt-ed25519-public-key` (optional) | `AIPOL_RECEIPT_ED25519_PUBLIC_KEY_B64` | public key only; required for a full signed-receipt rehearsal |

Example shapes only:

```json
{"editor-dev":"scrypt-v1$...","approver-dev":"scrypt-v1$..."}
{"editor-dev":["editor"],"approver-dev":["approver"]}
{"editor-dev":"<base32-totp-secret>","approver-dev":"<different-base32-totp-secret>"}
{"event-credentials-2026-01":"<random-credential-secret>","event-credentials-2026-02":"<next-random-secret>"}
```

Do not paste real values into a tracked file, ticket, chat, shell history, or deployment parameter. Never assign
both editor and approver to the same development account. The operator creating the values needs a separately
approved Key Vault data-plane role; the app identity receives read-only `Key Vault Secrets User`.

Wait for the managed-identity role assignments to propagate, then resolve and pin all six required secret versions.
Version pinning prevents ordinary Key Vault rotation from restarting the SQLite process outside the controlled
maintenance sequence.

```powershell
$AipolVault = az deployment group show `
  --resource-group rg-aipol-dev `
  --name aipol-event-tool-dev-infra `
  --query properties.outputs.keyVaultResourceName.value `
  --output tsv

$EventSessionSecretVersion = ((az keyvault secret show --vault-name $AipolVault --name event-session-secret --query id --output tsv) -split '/')[-1]
$EventAdminUsersSecretVersion = ((az keyvault secret show --vault-name $AipolVault --name event-admin-users-json --query id --output tsv) -split '/')[-1]
$EventAdminRolesSecretVersion = ((az keyvault secret show --vault-name $AipolVault --name event-admin-roles-json --query id --output tsv) -split '/')[-1]
$EventAdminTotpSecretVersion = ((az keyvault secret show --vault-name $AipolVault --name event-admin-totp-secrets-json --query id --output tsv) -split '/')[-1]
$EventCredentialKeysetVersion = ((az keyvault secret show --vault-name $AipolVault --name event-credential-secrets-json --query id --output tsv) -split '/')[-1]
$EventAuditCheckpointKeysetVersion = ((az keyvault secret show --vault-name $AipolVault --name event-audit-checkpoint-secrets-json --query id --output tsv) -split '/')[-1]
```

## 5. Review and create the Container App

Keep all feature flags explicitly off. The normal development deployment also keeps ingress internal:

Before this step, complete the **Immutable audit-checkpoint gate** below and retain its verified
`$AipolAuditLockEvidenceId`; the app guard rejects an unlocked or unattested checkpoint container.

```powershell
az deployment group what-if `
  --resource-group rg-aipol-dev `
  --template-file deploy/azure/event-tool-dev/main.bicep `
  --parameters '@deploy/azure/event-tool-dev/main.parameters.dev.json' `
               deployInfrastructure=true `
               deployApp=true `
               containerImage=$AipolImage `
               revisionSuffix=$AipolDeploymentRevision `
               eventSessionSecretVersion=$EventSessionSecretVersion `
               eventAdminUsersSecretVersion=$EventAdminUsersSecretVersion `
               eventAdminRolesSecretVersion=$EventAdminRolesSecretVersion `
               eventAdminTotpSecretVersion=$EventAdminTotpSecretVersion `
               eventCredentialKeysetVersion=$EventCredentialKeysetVersion `
               eventCredentialActiveKeyId=event-credentials-2026-01 `
               eventAuditCheckpointKeysetVersion=$EventAuditCheckpointKeysetVersion `
               eventAuditCheckpointActiveKeyId=audit-checkpoints-2026-01 `
               auditImmutabilityPolicyLocked=true `
               auditImmutabilityLockEvidenceId=$AipolAuditLockEvidenceId `
               reviewBuildCommit=$AipolBuildCommit `
               reviewDbSeedHash=$AipolDbSeedHash `
               reviewDeploymentRevision=$AipolDeploymentRevision `
               reviewPublicOrigin=$AipolPublicOrigin `
               enableExternalIngress=false `
               collectionEnabled=false `
               chatbotEnabled=false `
               batchEnabled=false
```

Credential rotation is additive. Add the new key, select it with `eventCredentialActiveKeyId`, and create new
experiments with that key. Do not remove an old key while its experiment has registration open or any participant
is incomplete: startup fails and `/readyz` reports the missing key IDs. Existing experiments are never silently
re-keyed because their one-time seats and nonce replay records remain bound to their stored key ID.

For a full E1a → M3 synthetic rehearsal, first add the optional public-key secret and resolve its version. Then
deploy with `receiptVerifierEnabled=true`, `receiptPublicKeySecretVersion=<version>`, and reviewed
`receiptKeyId`, `receiptIssuer`, `receiptAudience`, and `receiptMaxTtlSeconds` values. The frozen calculator receipt
contract must match those values exactly. This adds `Key Vault Secrets User` only on that named public-key secret.
The readiness response must show `receipt_verifier=configured` and `collection_ready=true` before the rehearsal.

The template creates no app unless the image contains `@sha256:`, all six required secret versions are provided,
and the professor-review build commit, DB seed hash, exact revision suffix, and exact HTTPS origin are pinned. The
`reviewDeploymentRevision` value must equal the resulting full revision name
`ca-aipol-event-tool-dev--<revisionSuffix>`. After
the `what-if` output, image digest, and `appInputGuardAccepted=true` are approved, repeat with
`az deployment group create`. The deployment must show `minReplicas=1`, `maxReplicas=1`, one Uvicorn worker, and
`/data` mounted from `event-tool-state`. Collection and chatbot parameters accept only `false`; external ingress is
also `false` by default and may be enabled only for the separately approved synthetic review described below. Batch
remains OFF by default and is forbidden while external ingress is enabled; enabling it internally is a separate reviewed deployment that must
name the existing policy-news Job.

To enable only the managed-identity Job control after the app image and target Job have been reviewed, repeat
`what-if` with `batchEnabled=true policyNewsJobName=caj-aipol-policy-news-daily-dev`. Confirm that the only new
authorization assignment is `Container Apps Jobs Operator` scoped to the exact Job resource ID. The adapter can
start and read executions but cannot edit or delete the Job. Keep the database batch configuration OFF until the
operator is ready to allow individual manual requests.

## 6. Verification

Because default ingress is internal, verify readiness through the Azure revision state and an approved Container
Apps environment path rather than making the app public.

```powershell
az containerapp revision list `
  --resource-group rg-aipol-dev `
  --name ca-aipol-event-tool-dev `
  --query '[].{name:name,active:properties.active,health:properties.healthState,replicas:properties.replicas}' `
  --output table

az containerapp logs show `
  --resource-group rg-aipol-dev `
  --name ca-aipol-event-tool-dev `
  --type console `
  --tail 100
```

Acceptance checks:

1. Exactly one active revision and one replica become healthy.
2. Startup logs contain no Key Vault, ACR, SQLite, or roster errors.
3. `/healthz` and `/readyz` return HTTP 200 from an internal test path; disabled receipt verification reports
   `collection_ready=false`, while a full rehearsal requires `collection_ready=true`.
4. `/data/event.db` and `/data/roster.json` survive a normal revision restart.
5. No external FQDN is reachable, no model key exists, and collection/chatbot/batch settings remain false.
6. Login responses show the explicit editor/approver role split; no account has both roles.
7. Only synthetic development records are used.

External ingress requires a separate security and privacy review. Do not set `enableExternalIngress=true` merely to
make the internal smoke test easier.

For an explicitly approved, synthetic-only external review link, repeat the same reviewed deployment with
`enableExternalIngress=true` while keeping `collectionEnabled=false`, `chatbotEnabled=false`, and
`batchEnabled=false`. The resulting Azure-managed FQDN is HTTPS-only. Participants still require one-time admission
codes, administrators still require distinct scrypt-hashed accounts plus TOTP, replicas remain fixed at one, and
no custom DNS or production resource is created. Never share an administrator credential with a reviewer.

## 7. SQLite backup, rollback, and scaling rule

First close every general round and AIPOL collection and stop AI jobs. Create the backup through the authenticated
maintenance API so the serialized HTTP wrapper excludes concurrent operator requests. The endpoint itself rechecks
those conditions, writes to a local temporary DB with `sqlite3.Connection.backup()`, runs `integrity_check`, and only then promotes the file to Azure
Files:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri 'https://<reviewed-host>/api/admin/aipol/maintenance/backup' `
  -Headers @{ 'X-Admin-Token' = $AipolAdminToken }
```

Only an account with the `admin` role can call this endpoint. Record the returned path, SHA-256, and byte count.
The packaged `python /app/backup_sqlite.py` command is an offline recovery utility, not the normal online backup
path. Download that exact file through an approved Azure Files
data-plane identity and verify the checksum outside Azure before continuing. A raw copy of `event.db` while writes
are in progress is not a backup.

Before deploying a new image or pinned secret version, explicitly deactivate the old revision and wait for zero
active revisions:

```powershell
$ActiveRevisions = az containerapp revision list `
  --resource-group rg-aipol-dev `
  --name ca-aipol-event-tool-dev `
  --query "[?properties.active].name" `
  --output tsv

foreach ($Revision in $ActiveRevisions) {
  az containerapp revision deactivate `
    --resource-group rg-aipol-dev `
    --name ca-aipol-event-tool-dev `
    --revision $Revision
}

az containerapp revision list `
  --resource-group rg-aipol-dev `
  --name ca-aipol-event-tool-dev `
  --query "length([?properties.active])" `
  --output tsv
```

The last command must print `0`. Only then run the reviewed Bicep deployment. The deployment wrapper acquires an
atomic writer-lease directory on `/data` before importing `server.py`; an overlapping revision fails startup rather
than opening the `nolock` database.

After an unclean container exit, a stale `event-tool.writer-lease` intentionally blocks restart. Confirm that Azure
reports zero active revisions, inspect the lease owner file, then remove the stale directory through an approved
Azure Files data-plane identity. Never remove it while any revision is active.

Rollback has two independent parts:

- **Application:** redeploy the last approved image digest through this Bicep template.
- **Database:** restore only from a verified backup after stopping writes and recording the reason. Reverting an
  image does not automatically reverse a schema change.

Azure Files plus SQLite `nolock=1` is accepted here only for one replica, one process worker, and the serialized HTTP
wrapper. A Container Apps single-revision update can briefly run the old and new revisions together, so this
backend does **not** use zero-downtime updates: close collection, create and verify the backup, deactivate the old
revision, and only then deploy the new image. Never increase worker/replica counts, run concurrent maintenance
containers against the file, or attach the share to a second app. Move the state to managed PostgreSQL before
adding replicas, parallel jobs, zero-downtime revisions, or sustained concurrent event traffic.

The public registration failure budget is also process-local and deliberately bounded. This deployment's one
replica/one worker constraint is therefore a security boundary as well as a SQLite boundary. Do not scale it out
without replacing the registration limiter with a shared durable service. Only enable trusted proxy headers when
the Container Apps ingress is the sole path to the application and overwrites client-supplied forwarding headers.

The application identity receives `Key Vault Secrets User` separately on the six required named secrets and the
optional receipt public-key secret, never on the vault. Container App references remain pinned to explicit secret versions. Adding another secret requires a new
secret-scoped role assignment and review; widening the role to the vault is prohibited.

## Immutable audit-checkpoint gate

The infrastructure deployment creates `aipol-audit-checkpoints` with versioning and a 365-day immutability policy.
Azure requires a distinct, irreversible authorized operation to lock that policy, so keep `deployApp=false` during
creation. After human approval locks it, the release preflight must read Azure and require `state=Locked`:

```powershell
$AipolStorage = az storage account list --resource-group rg-aipol-dev --query "[?starts_with(name,'staipolevt')].name | [0]" -o tsv
$AipolStorageId = az storage account show --resource-group rg-aipol-dev --name $AipolStorage --query id -o tsv
$AipolPolicyUrl = "https://management.azure.com$AipolStorageId/blobServices/default/containers/aipol-audit-checkpoints/immutabilityPolicies/default?api-version=2025-01-01"
$AipolPolicy = az rest --method get --url $AipolPolicyUrl | ConvertFrom-Json
if ($AipolPolicy.properties.state -ne 'Locked') { throw 'Audit checkpoint policy is not Locked; app deployment is blocked.' }
$AipolAuditLockEvidenceId = "$($AipolPolicy.id):$($AipolPolicy.etag)"
```

Only that same reviewed workflow may pass `auditImmutabilityPolicyLocked=true` and
`auditImmutabilityLockEvidenceId=$AipolAuditLockEvidenceId`. The flag attests the Azure read; it does not lock the
policy. The app also requires a pinned version of named Key Vault secret
`event-audit-checkpoint-secrets-json` and `eventAuditCheckpointActiveKeyId`. Its custom role is scoped to the one
container and includes blob read/write but no delete, version-delete, permanent-delete, Blob Data Contributor, or
immutability superuser permission. Checkpoint verification failure makes `/readyz` return 503 and blocks admin
mutation. See `docs/aipol-audit-checkpoint-threat-model.md` for attack and recovery boundaries.

## References

- [Azure Container Apps: Azure Files mounts](https://learn.microsoft.com/azure/container-apps/storage-mounts-azure-files)
- [Azure Container Apps: managed-identity ACR pulls](https://learn.microsoft.com/azure/container-apps/managed-identity-image-pull)
- [Azure Container Apps: Key Vault secret references](https://learn.microsoft.com/azure/container-apps/manage-secrets)
