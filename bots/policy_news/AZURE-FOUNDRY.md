# Azure Foundry + naia-kb-compiler execution contract

This is the production-oriented adapter path for AIPOL overseas AI-policy news. It is additive: the existing
Solar draft → Nemotron review path remains available through `SolarDraftAdapter` and `NemotronReviewAdapter`.

## Verified development deployment (2026-07-28)

| Item | Value |
|---|---|
| Resource group | `rg-aipol-dev` |
| Foundry account | `aipol-ai-mxajhqb4i5p4o` (`eastus2`, local auth disabled) |
| Inference endpoint | `https://aipol-ai-mxajhqb4i5p4o.services.ai.azure.com` |
| Deployment | `aipol-policy-news-draft-v2` |
| Model | `gpt-5.4-mini` `2026-03-17`, `DataZoneStandard`, capacity 1 |
| Runtime switch | OFF unless `POLICY_NEWS_ENABLED=true` is set explicitly |

An authenticated OpenAI v1 smoke call and one end-to-end draft → mock adversarial review → mock KB compile run both
passed. The latter stopped at `kb_compiled`; it was not human-approved or published. The temporary smoke source and
run records live under gitignored `tmp/`, not in public site assets.

## Safety boundary

- The default is stopped twice: `deployFoundry=false` in Bicep and `POLICY_NEWS_ENABLED=false` at runtime.
- `POLICY_NEWS_DRY_RUN=true` permits only deterministic mock adapters.
- No pipeline result is published automatically. A PASS review moves a run only to `review_passed`; a successful KB
  compile moves it to `kb_compiled`. A named human must explicitly move it to `human_approved` before a publisher can
  mark it `published`.
- Provider calls are capped by calls/run and estimated cost/run. Retries consume call budget and only transient HTTP
  failures (408/409/425/429/5xx, timeout/unavailable) are retried.
- The original official-source text is stored under `data-private/` with a SHA-256 digest. Public/run metadata keeps
  its URL, fetch time and digest but does not republish the full text.
- `naia-kb-compiler` remains replaceable. It is called through an HTTPS port or a JSON-stdio command port. Its portable
  JSON is the source of truth; a managed vector/graph index is only a rebuildable projection. The response must attest
  `safety.mode=block`, or the adapter rejects the artifact. The current compiler's generic HTTP handler does not yet
  expose its `safety` input, so the command wrapper should call `createClient().compile()` directly (or the deployed
  HTTP wrapper must preserve that field); silently stripping it is not accepted.
- HTTP mode is fail-closed until the same origin serves
  `/.well-known/aipol-kb-compiler-receiver.json`. Before obtaining a token or sending source text, the client reads
  that document with a 64 KiB limit and requires exact tenant, audience/scope, UAMI client and principal IDs, app
  role, Entra v2 issuer/JWKS validation mode, receiver version, immutable deployment digest, and `/compile` path.
  The exact canonical contract hash is stored in KB provenance. A bearer token sent by this client is not evidence
  that the receiver authenticated it.
- The naia-kb-compiler receiver itself must validate the Entra v2 JWT signature from the declared issuer/JWKS and
  reject wrong tenant, exact `aud`, `exp`/`nbf`, UAMI `appid`/`azp` and object/principal identity, or missing required
  app-role claims. The repository currently contains no attested production receiver, so HTTP mode and the Azure job
  remain disabled. Command mode remains a local argv-based JSON-stdio port executed with `shell=False`.

## Contracts

- Input: `schemas/source-packet.schema.json`
- Run/output: `schemas/run-record.schema.json`
- KB compiler boundary: `schemas/kb-compile-request.schema.json`
- Python validation and state machine: `contracts.py`
- Provider ports: `ports.py`; concrete/test adapters: `adapters.py`
- Idempotent orchestration and private file store: `orchestrator.py`

Each idempotency key covers source URL, source-content digest, configuration revision and prompt digest. Re-running the
same packet returns the existing run without another model or compiler call.

## Pre-deployment discovery (required)

Do not guess model availability or quota. Create the Foundry account only after selecting a region, then record the
actual `name`, `format`, `version`, SKU and minimum capacity reported by Azure:

```powershell
az cognitiveservices account list-models `
  --name <foundry-account> `
  --resource-group rg-aipol-dev `
  --query "[].{name:name,format:format,version:version,skus:skus}"
```

Partner/community models can require Azure Marketplace acceptance. Confirm commercial terms and quota before setting
`deployModel=true`. Also verify that the selected deployment supports JSON-object structured output used by the
editorial contract. Template defaults perform no billable AI deployment.

The checked development deployment uses `gpt-5.4-mini` version `2026-03-17`, `OpenAI` format and
`DataZoneStandard` SKU because Azure reported available quota in `eastus2` and it supports the OpenAI v1 route used by
the adapter. Its deployment name is `aipol-policy-news-draft-v2`; the version suffix prevents stale runtime routing
when the catalog model changes. Do not replace it with a non-OpenAI
catalog model without repeating an authenticated endpoint compatibility test.

For keyless inference, pass the runtime managed identity's Entra object ID as `inferencePrincipalId` and set
`inferencePrincipalType=ServicePrincipal`. The template then grants the built-in `Cognitive Services User` role only
at the Foundry account scope. A developer user may be supplied for a development smoke test, but production must use
the scheduled job's managed identity. Role assignments can take several minutes to propagate.

Validate the template without creating resources:

```powershell
az bicep build --file deploy/azure/policy-ai.bicep
az deployment group validate `
  --resource-group rg-aipol-dev `
  --template-file deploy/azure/policy-ai.bicep `
  --parameters deployFoundry=false deployModel=false
```

The template follows Microsoft's current AIServices resource and OpenAI/v1 model deployment pattern:

- https://learn.microsoft.com/azure/foundry/foundry-models/how-to/create-model-deployments
- https://learn.microsoft.com/azure/foundry/foundry-models/concepts/endpoints

## Runtime configuration

| Variable | Default | Boundary |
|---|---:|---|
| `POLICY_NEWS_ENABLED` | `false` | Master runtime kill switch |
| `POLICY_NEWS_DRY_RUN` | `true` | Allows deterministic mock adapters only |
| `POLICY_NEWS_MAX_ITEMS` | `3` | Candidate cap per scheduled invocation |
| `POLICY_NEWS_MAX_CALLS` | `9` | Includes retry attempts |
| `POLICY_NEWS_MAX_COST_USD` | `1.00` | Estimated application-side run cap |
| `POLICY_NEWS_ESTIMATED_DRAFT_COST_USD` | `0.30` | Conservative reservation per draft attempt; operator updates after pricing check |
| `POLICY_NEWS_ESTIMATED_REVIEW_COST_USD` | `0.30` | Conservative reservation per review attempt |
| `POLICY_NEWS_ESTIMATED_KB_COST_USD` | `0.05` | Conservative reservation per remote KB compile attempt |
| `POLICY_NEWS_MAX_ATTEMPTS` | `3` | Transient retry cap |
| `AZURE_AI_FOUNDRY_REGION` | empty | Recorded provenance; must match deployed resource |
| `AZURE_AI_FOUNDRY_ENDPOINT` | empty | Resource endpoint, without `/openai/v1` |
| `AZURE_AI_FOUNDRY_DEPLOYMENT` | empty | Deployment name sent as `model` |
| `AZURE_AI_FOUNDRY_REASONING_EFFORT` | `low` | Bounded reasoning level for the current GPT deployment |
| `AZURE_AI_FOUNDRY_MAX_COMPLETION_TOKENS` | `1024` | Hard output cap for one editorial draft |
| `AZURE_AI_FOUNDRY_AUTH_MODE` | `api_key` | `api_key`, `bearer`, or `managed_identity` (scheduled Azure job) |
| `AZURE_AI_FOUNDRY_KEY_ENV` | `AZURE_OPENAI_API_KEY` | Name of key environment variable, not the key |
| `AZURE_AI_FOUNDRY_BEARER_TOKEN_ENV` | `AZURE_AI_FOUNDRY_BEARER_TOKEN` | Name of Entra token variable |
| `POLICY_NEWS_REVIEW_PROVIDER` | `nemotron` | `nemotron` or `mock` |
| `POLICY_NEWS_KB_COMPILER_MODE` | `disabled` | OFF-only default; enabled real runs require `http` or `command` |
| `NAIA_KB_COMPILER_ENDPOINT` | empty | Exact HTTPS origin of the `/compile` service; no path/query/credentials |
| `NAIA_KB_COMPILER_ALLOWED_ORIGINS` | empty | Explicit comma-separated allowlist; the endpoint must match one entry exactly |
| `NAIA_KB_COMPILER_APP_CLIENT_ID` | empty | Dedicated receiver app registration's canonical client UUID |
| `NAIA_KB_COMPILER_SCOPE` | empty | Exact `api://<NAIA_KB_COMPILER_APP_CLIENT_ID>/.default`; ARM, Storage, and ordinary URL audiences are rejected |
| `AZURE_TENANT_ID` | empty | Exact Entra tenant asserted by the receiver contract |
| `NAIA_KB_COMPILER_UAMI_PRINCIPAL_ID` | empty | Exact UAMI object/principal ID the receiver must authorize |
| `NAIA_KB_COMPILER_REQUIRED_APP_ROLE` | empty | Exact app role required by the receiver |
| `NAIA_KB_COMPILER_RECEIVER_VERSION` | empty | Exact immutable receiver software version |
| `NAIA_KB_COMPILER_RECEIVER_DEPLOYMENT_ID` | empty | Exact `sha256:<64 lowercase hex>` deployment identity |
| `NAIA_KB_COMPILER_VALIDATION_MODE` | `entra-jwt-v2-strict` | Requires issuer/JWKS, exact audience, expiry, UAMI identity, and app-role validation |
| `NAIA_KB_COMPILER_MAX_RESPONSE_BYTES` | `1000000` | Streaming cap applied before compile JSON parsing |
| `NAIA_KB_COMPILER_CONTRACT_MAX_BYTES` | `65536` | Streaming cap applied before well-known contract parsing |
| `NAIA_KB_COMPILER_COMMAND` | empty | JSON-stdin/stdout wrapper command; never invoked through a shell |
| `AZURE_STORAGE_BLOB_URL` | empty | Managed-identity Blob account URL used by the scheduled job's durable private store |

Example mock-only rehearsal (writes only to the specified private/temp directory):

```powershell
$env:POLICY_NEWS_ENABLED='true'
$env:POLICY_NEWS_DRY_RUN='true'
$env:POLICY_NEWS_REVIEW_PROVIDER='mock'
$env:POLICY_NEWS_KB_COMPILER_MODE='mock'
python bots/policy_news/run_v2.py packet.json --draft-provider mock --state-dir data-private/policy-news-rehearsal
```

For real providers set `POLICY_NEWS_DRY_RUN=false` and pass `--confirm-provider-call`. That flag is an operator
confirmation only; it does not bypass review, human approval, call/cost limits or the kill switch.
