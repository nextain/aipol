# AIPOL daily policy-news job runbook (development)

Target resource group: `rg-aipol-dev`. This runbook does not publish public content. The scheduled process can only
collect, draft, adversarially review and write private audit/KB-candidate state. A named human approval and a separate
release action remain mandatory.

## 1. Safety and cost invariants

- Infrastructure, job, schedule and runtime AI have separate switches. All are `false` in the example parameters.
- The first job deployment is manual-only with `POLICY_NEWS_ENABLED=false`.
- At most three official-source packets, nine provider attempts and an estimated USD 1.00 application budget per run.
- Container Apps Job uses Consumption, 0.25 vCPU/0.5 GiB, one replica, 600-second timeout and one platform retry.
- Storage containers have anonymous access disabled; shared-key auth is disabled. The job identity receives Blob Data
  Contributor only on the two private containers.
- Foundry, Blob and ACR access use one user-assigned managed identity created before the job. ACR admin credentials
  are disabled, and `AcrPull` is granted before Container Apps provisions the private-image revision.
- Foundry inference uses `https://aipol-ai-mxajhqb4i5p4o.services.ai.azure.com` as the base URL. The adapter appends
  `/openai/v1/chat/completions` and requests the `https://ai.azure.com/.default` Entra scope; this is the combination
  verified by the authenticated development smoke test.
- A renewable Blob lease prevents overlapping manual/scheduled executions from paying for the same source twice.
- Runtime activation requires either `kbCompilerMode=http` with a non-secret HTTPS endpoint or
  `kbCompilerMode=command` with a non-secret JSON-stdin/stdout command. `disabled` is valid only while the master
  runtime switch is OFF; the deployment and process both fail closed if activation is attempted without a compiler.
- HTTP activation also requires the dedicated receiver application client UUID. The only accepted token scope is
  `api://<kbCompilerAppClientId>/.default`; Azure Resource Manager, Storage, and ordinary URL audiences are rejected.
- OpenRouter is optional but required by the current independent Nemotron review path. It must enter the job only as a
  Key Vault reference. Do not put it in parameters, source, an image layer, CLI output or a repository secret file.
- No code path in `scheduled_job.py` calls `human_approve` or `mark_published`.

## 2. Validate without deployment

```powershell
az bicep build --file deploy/azure/policy-news-job.bicep --stdout | Out-Null

az deployment group validate `
  --resource-group rg-aipol-dev `
  --template-file deploy/azure/policy-news-job.bicep `
  --parameters deployInfrastructure=false deployJob=false enableSchedule=false policyNewsEnabled=false
```

## 3. Provision infrastructure only

This creates Basic ACR, Standard_LRS Blob Storage and a Consumption Container Apps Environment. It does not create or
run the job.

```powershell
az deployment group create `
  --resource-group rg-aipol-dev `
  --name aipol-policy-news-infra `
  --template-file deploy/azure/policy-news-job.bicep `
  --parameters deployInfrastructure=true deployJob=false enableSchedule=false policyNewsEnabled=false
```

Capture the output names; do not infer them from a different subscription:

```powershell
az deployment group show `
  --resource-group rg-aipol-dev `
  --name aipol-policy-news-infra `
  --query properties.outputs
```

## 4. Build an immutable image in ACR

Use a Git commit SHA or another immutable release identifier; never deploy `latest`.

```powershell
$registryName = '<ACR resource name from the deployment>'
$imageTag = '<git-commit-sha>'

az acr build `
  --registry $registryName `
  --image "aipol/policy-news:$imageTag" `
  --file bots/policy_news/Dockerfile `
  bots/policy_news

$imageDigest = az acr repository show `
  --name $registryName `
  --image "aipol/policy-news:$imageTag" `
  --query digest -o tsv
$containerImageRef = "$registryName.azurecr.io/aipol/policy-news@$imageDigest"
```

The build context is only `bots/policy_news/`; its `.dockerignore` excludes local environment, key and cache files.
`data-private`, `.git`, site assets and other projects cannot enter the remote build context.

## 5. Configure the independent-review secret, if used

Put `OPENROUTER_API_KEY` in a dedicated policy-news Key Vault using the portal or an organization-controlled secret
pipeline. Record its secret name and version-pinned URI. Do not paste the secret value into command history or a JSON
parameters file. `policy-news-job.bicep` grants the job's user-assigned identity `Key Vault Secrets User` on that one
secret resource only when vault name, secret name and URI are all supplied. It never grants shared-vault-wide read.

If no secret URI is supplied, the job remains deployable but fails closed before any Foundry call when runtime AI is
enabled. This is deliberate.

## 6. Deploy a stopped, manual-only job

```powershell
az deployment group create `
  --resource-group rg-aipol-dev `
  --name aipol-policy-news-job `
  --template-file deploy/azure/policy-news-job.bicep `
  --parameters `
    deployInfrastructure=true `
    deployJob=true `
    enableSchedule=false `
    policyNewsEnabled=false `
    policyNewsDryRun=true `
    foundryEndpoint='https://aipol-ai-mxajhqb4i5p4o.services.ai.azure.com' `
    kbCompilerMode=disabled `
    kbCompilerEndpoint='' `
    kbCompilerCommand='' `
    containerImage="$containerImageRef" `
    keyVaultName='<optional-vault-name>' `
    openRouterSecretName='<optional-secret-name>' `
    openRouterSecretUri='<optional-versioned-secret-uri>'
```

The deployment creates the user-assigned identity first, grants it ACR pull, Blob contributor on the two private
containers, Cognitive Services User on `aipol-ai-mxajhqb4i5p4o`, and (when configured) secret-scoped Key Vault
Secrets User, then
creates the job. The same identity resource ID is used for private-image pull, Key Vault references and runtime
authentication; `AZURE_CLIENT_ID` selects it for the Azure SDK. Because this template owns the Foundry role, do not
also pass this principal into `policy-ai.bicep`'s `inferencePrincipalId`.

RBAC propagation can take several minutes. The initial stopped run is safe to retry:

```powershell
az containerapp job start --resource-group rg-aipol-dev --name caj-aipol-policy-news-daily-dev
az containerapp job execution list --resource-group rg-aipol-dev --name caj-aipol-policy-news-daily-dev -o table
```

Expected container result: `{"status":"stopped","reason":"POLICY_NEWS_ENABLED=false"}` and no provider calls.

## 7. Controlled manual AI run

Only after model quota, managed-identity access, the Key Vault reference, provider terms, private Blob access and a
deployed naia-kb-compiler port are confirmed, redeploy with `policyNewsEnabled=true`, `policyNewsDryRun=false`, while
keeping `enableSchedule=false`. Supply exactly one compiler boundary:

- `kbCompilerMode=http` and a credential-free `kbCompilerEndpoint`, only after its same-origin well-known receiver
  contract exactly attests the Entra tenant, receiver app client ID, audience/scope, allowed UAMI client/principal, required app role,
  issuer/JWKS validation mode, receiver version and immutable deployment digest; or
- `kbCompilerMode=command` and a credential-free `kbCompilerCommand` available inside the runtime image.

No compiler service or command is deployed in `rg-aipol-dev` yet. This is an external activation blocker, not a reason
to skip compilation: `kbCompilerMode=disabled` with `policyNewsEnabled=true` is rejected before provider calls.
The receiver must validate JWT signature, issuer, exact audience, expiry/not-before, UAMI app/client and principal
identity, and the required app-role claim. Client-side managed-token acquisition alone does not satisfy this boundary.
Run once manually. Inspect only private Blob paths:

- `policy-news-sources/sha256/*.json` — full official-source packet, private
- `policy-news-runs/idempotency/*.txt` — immutable idempotency index
- `policy-news-runs/records/*.json` — approval state, attempts and provenance

A normal automated result stops at `review_passed` (or `review_blocked`). It does not create a public content JSON.

## 8. Enable and stop the daily schedule

After the manual evidence is reviewed, redeploy with `enableSchedule=true`. The default `0 21 * * *` is evaluated in
UTC and runs daily at 06:00 KST.

Emergency stop is a redeployment with both switches false:

```powershell
az deployment group create `
  --resource-group rg-aipol-dev `
  --name aipol-policy-news-job-stop `
  --template-file deploy/azure/policy-news-job.bicep `
  --parameters `
    deployInfrastructure=true `
    deployJob=true `
    enableSchedule=false `
    policyNewsEnabled=false `
    policyNewsDryRun=true `
    foundryEndpoint='https://aipol-ai-mxajhqb4i5p4o.services.ai.azure.com' `
    kbCompilerMode=disabled `
    kbCompilerEndpoint='' `
    kbCompilerCommand='' `
    containerImage="$containerImageRef" `
    keyVaultName='<same-vault-name>' `
    openRouterSecretName='<same-secret-name>' `
    openRouterSecretUri='<same-versioned-secret-uri>'
```

Always carry forward the verified Foundry endpoint, deployed immutable image and secret-reference parameters when
redeploying. Omitting them would restore template defaults, so the operational parameter values belong in the
approved deployment pipeline.

Do not delete Blob containers during an incident. They are the audit/source record and have 14-day soft delete.
