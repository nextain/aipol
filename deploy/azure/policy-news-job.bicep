targetScope = 'resourceGroup'

@description('Create low-cost Container Apps/ACR/Blob infrastructure. Default false for validation-only use.')
param deployInfrastructure bool = false

@description('Create the job definition. Requires deployInfrastructure=true and an image already present in ACR.')
param deployJob bool = false

@description('Enable the UTC cron trigger. False creates a manual-only job.')
param enableSchedule bool = false

@description('Runtime AI kill switch passed to the container. Keep false until model, quota, secrets and review are verified.')
param policyNewsEnabled bool = false

@description('Dry-run flag. Scheduled entrypoint requires false only when policyNewsEnabled is explicitly enabled.')
param policyNewsDryRun bool = true

@description('Container Apps/Storage/ACR region. Korea Central supports all three services.')
param location string = 'koreacentral'

param environmentName string = 'cae-aipol-policy-news-dev'
param jobName string = 'caj-aipol-policy-news-daily-dev'
param jobIdentityName string = 'uami-aipol-policy-news-dev'
param storageAccountName string = 'staipol${uniqueString(subscription().id, resourceGroup().id)}'
param registryName string = 'acraipol${uniqueString(subscription().id, resourceGroup().id)}'

@description('Immutable image tag or digest built and pushed before deployJob=true.')
param containerImage string = '${registryName}.azurecr.io/aipol/policy-news:bootstrap-not-built'

@description('Daily cron in UTC. Default 21:00 UTC = 06:00 KST.')
param cronExpression string = '0 21 * * *'

@minValue(1)
@maxValue(3)
param maxItemsPerRun int = 3

@minValue(60)
@maxValue(1800)
param replicaTimeoutSeconds int = 600

@minValue(0)
@maxValue(2)
param replicaRetryLimit int = 1

@description('Existing Foundry resource created by policy-ai.bicep.')
param foundryAccountName string = 'aipol-ai-mxajhqb4i5p4o'

@description('Foundry OpenAI-v1 base endpoint, without /openai/v1. Keep aligned with policy-ai.bicep output.')
param foundryEndpoint string = 'https://${foundryAccountName}.services.ai.azure.com'

param foundryRegion string = 'eastus2'
param foundryDeployment string = 'aipol-policy-news-draft-v2'

@allowed([
  'disabled'
  'http'
  'command'
])
@description('KB compiler adapter mode. Runtime activation is rejected unless http/endpoint or command/command is configured.')
param kbCompilerMode string = 'disabled'

@description('Non-secret HTTPS base URL for the separately deployed naia-kb-compiler HTTP port.')
param kbCompilerEndpoint string = ''

@description('The one exact HTTPS origin allowed for the KB compiler. Must equal kbCompilerEndpoint in http mode.')
param kbCompilerAllowedOrigin string = ''

@description('Microsoft Entra scope for the dedicated KB receiver app: api://<app-client-id>/.default.')
param kbCompilerScope string = ''

@description('Canonical application (client) UUID of the dedicated KB compiler receiver app registration.')
param kbCompilerAppClientId string = ''

@description('App role the receiver must require after Entra JWT validation.')
param kbCompilerRequiredAppRole string = ''

@description('Exact immutable receiver software version exposed by the well-known contract.')
param kbCompilerReceiverVersion string = ''

@description('Immutable receiver deployment digest, formatted sha256:<64 lowercase hex>.')
param kbCompilerReceiverDeploymentId string = ''

@allowed([
  'entra-jwt-v2-strict'
])
@description('Receiver-side validation contract: Entra v2 issuer/JWKS, exact audience, expiry, UAMI identity, and app role.')
param kbCompilerValidationMode string = 'entra-jwt-v2-strict'

@description('Non-secret JSON-stdin/stdout compiler command. Never include credentials in this parameter.')
param kbCompilerCommand string = ''

@minValue(5)
@maxValue(600)
param kbCompilerTimeoutSeconds int = 120

@minValue(1024)
@maxValue(10000000)
param kbCompilerMaxResponseBytes int = 1000000

@minValue(1024)
@maxValue(262144)
param kbCompilerContractMaxBytes int = 65536

@description('Optional version-pinned Key Vault secret URI for OPENROUTER_API_KEY. Empty keeps the secret unset.')
param openRouterSecretUri string = ''

@description('Secret name contained in openRouterSecretUri. Required with the URI so RBAC can be scoped to this secret only.')
param openRouterSecretName string = ''

@description('Existing dedicated policy-news Key Vault in this resource group. No vault-wide role is granted.')
param keyVaultName string = ''

param runsContainerName string = 'policy-news-runs'
param sourcesContainerName string = 'policy-news-sources'

param tags object = {
  project: 'AIPOL'
  component: 'policy-news-job'
  environment: 'dev'
  owner: 'nextain'
  managedBy: 'bicep'
}

var expectedResourceGroupName = 'rg-aipol-dev'
var resourceGroupScopeAccepted = resourceGroup().name == expectedResourceGroupName
var resourceGroupNameValidated = resourceGroupScopeAccepted ? resourceGroup().name : fail('policy-news-job.bicep may only target rg-aipol-dev')
var kbCompilerAuthority = length(kbCompilerEndpoint) > 8 ? substring(kbCompilerEndpoint, 8) : ''
var kbCompilerEndpointValidated = empty(kbCompilerEndpoint) || (startsWith(kbCompilerEndpoint, 'https://') && kbCompilerEndpoint == toLower(kbCompilerEndpoint) && !empty(kbCompilerAuthority) && !contains(kbCompilerAuthority, '/') && !contains(kbCompilerAuthority, ':') && !contains(kbCompilerAuthority, '@') && !contains(kbCompilerAuthority, '?') && !contains(kbCompilerAuthority, '#') && !contains(kbCompilerAuthority, ' ')) ? kbCompilerEndpoint : fail('kbCompilerEndpoint must be a lowercase credential-free HTTPS origin without path, port, query, or fragment')
var kbCompilerAllowedOriginValidated = empty(kbCompilerAllowedOrigin) || kbCompilerAllowedOrigin == kbCompilerEndpointValidated ? kbCompilerAllowedOrigin : fail('kbCompilerAllowedOrigin must exactly equal kbCompilerEndpoint')
var appClientIdRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(kbCompilerAppClientId, '-', ''), '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var appClientIdShapeValid = length(kbCompilerAppClientId) == 36 ? (substring(kbCompilerAppClientId, 8, 1) == '-' && substring(kbCompilerAppClientId, 13, 1) == '-' && substring(kbCompilerAppClientId, 18, 1) == '-' && substring(kbCompilerAppClientId, 23, 1) == '-') : false
var appClientIdValid = appClientIdShapeValid && length(replace(kbCompilerAppClientId, '-', '')) == 32 && kbCompilerAppClientId == toLower(kbCompilerAppClientId) && empty(appClientIdRemainder)
var kbCompilerAppClientIdValidated = empty(kbCompilerAppClientId) || appClientIdValid ? kbCompilerAppClientId : fail('kbCompilerAppClientId must be a canonical lowercase application client UUID')
var expectedKbCompilerScope = empty(kbCompilerAppClientIdValidated) ? '' : 'api://${kbCompilerAppClientIdValidated}/.default'
var kbCompilerScopeValidated = empty(kbCompilerScope) || kbCompilerScope == expectedKbCompilerScope ? kbCompilerScope : fail('kbCompilerScope must exactly target the approved receiver app client ID')
var receiverDigestBody = length(kbCompilerReceiverDeploymentId) == 71 ? substring(kbCompilerReceiverDeploymentId, 7, 64) : ''
var receiverDigestRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(receiverDigestBody, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var receiverDeploymentValidated = empty(kbCompilerReceiverDeploymentId) || (startsWith(kbCompilerReceiverDeploymentId, 'sha256:') && length(kbCompilerReceiverDeploymentId) == 71 && kbCompilerReceiverDeploymentId == toLower(kbCompilerReceiverDeploymentId) && empty(receiverDigestRemainder)) ? kbCompilerReceiverDeploymentId : fail('kbCompilerReceiverDeploymentId must be an immutable lowercase sha256 digest')
var compilerConfigured = (kbCompilerMode == 'http' && !empty(kbCompilerEndpointValidated) && !empty(kbCompilerAllowedOriginValidated) && !empty(kbCompilerAppClientIdValidated) && !empty(kbCompilerScopeValidated) && !empty(kbCompilerRequiredAppRole) && !empty(kbCompilerReceiverVersion) && !empty(receiverDeploymentValidated)) || (kbCompilerMode == 'command' && !empty(kbCompilerCommand))
var secretParametersEmpty = empty(keyVaultName) && empty(openRouterSecretName) && empty(openRouterSecretUri)
var secretConfigured = !empty(keyVaultName) && !empty(openRouterSecretName) && !empty(openRouterSecretUri)
var policyNewsEnabledValidated = !policyNewsEnabled || compilerConfigured ? policyNewsEnabled : fail('policyNewsEnabled requires an attested HTTP receiver contract or local command KB compiler configuration')
var containerImageValidated = !deployJob || contains(containerImage, '@sha256:') ? containerImage : fail('deployJob requires containerImage pinned by @sha256 digest')
var secretConfiguredValidated = secretParametersEmpty || secretConfigured ? secretConfigured : fail('keyVaultName, openRouterSecretName, and openRouterSecretUri must be supplied together')
var secretVersionMarker = '/secrets/${toLower(openRouterSecretName)}/'
var openRouterSecretUriValidated = !secretConfiguredValidated || (contains(toLower(openRouterSecretUri), secretVersionMarker) && !endsWith(toLower(openRouterSecretUri), secretVersionMarker)) ? openRouterSecretUri : fail('openRouterSecretUri must be version-pinned and match openRouterSecretName')

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = if (deployInfrastructure) {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
  }
  tags: tags
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = if (deployInfrastructure) {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 14
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 14
    }
  }
}

resource runsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = if (deployInfrastructure) {
  parent: blobService
  name: runsContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource sourcesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = if (deployInfrastructure) {
  parent: blobService
  name: sourcesContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = if (deployInfrastructure) {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    dataEndpointEnabled: false
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = if (deployInfrastructure) {
  name: environmentName
  location: location
  properties: {
    zoneRedundant: false
  }
  tags: tags
}

// A user-assigned identity exists before the private-registry job. This lets
// AcrPull be granted before Container Apps tries to provision the revision and
// avoids the system-identity/ACR bootstrap cycle.
resource jobIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (deployInfrastructure && deployJob) {
  name: jobIdentityName
  location: location
  tags: tags
}

var baseEnv = [
  { name: 'POLICY_NEWS_ENABLED', value: string(policyNewsEnabledValidated) }
  { name: 'POLICY_NEWS_DRY_RUN', value: string(policyNewsDryRun) }
  { name: 'POLICY_NEWS_MAX_ITEMS', value: string(maxItemsPerRun) }
  { name: 'POLICY_NEWS_MAX_CALLS', value: '9' }
  { name: 'POLICY_NEWS_MAX_COST_USD', value: '1.00' }
  { name: 'POLICY_NEWS_MAX_ATTEMPTS', value: '2' }
  { name: 'POLICY_NEWS_TIMEOUT_SECONDS', value: '90' }
  { name: 'POLICY_NEWS_DRAFT_PROVIDER', value: 'foundry' }
  { name: 'POLICY_NEWS_REVIEW_PROVIDER', value: 'nemotron' }
  { name: 'POLICY_NEWS_KB_COMPILER_MODE', value: kbCompilerMode }
  { name: 'NAIA_KB_COMPILER_ENDPOINT', value: kbCompilerEndpointValidated }
  { name: 'NAIA_KB_COMPILER_ALLOWED_ORIGINS', value: kbCompilerAllowedOriginValidated }
  { name: 'NAIA_KB_COMPILER_SCOPE', value: kbCompilerScopeValidated }
  { name: 'NAIA_KB_COMPILER_APP_CLIENT_ID', value: kbCompilerAppClientIdValidated }
  { name: 'AZURE_TENANT_ID', value: tenant().tenantId }
  { name: 'NAIA_KB_COMPILER_UAMI_PRINCIPAL_ID', value: jobIdentity!.properties.principalId }
  { name: 'NAIA_KB_COMPILER_REQUIRED_APP_ROLE', value: kbCompilerRequiredAppRole }
  { name: 'NAIA_KB_COMPILER_RECEIVER_VERSION', value: kbCompilerReceiverVersion }
  { name: 'NAIA_KB_COMPILER_RECEIVER_DEPLOYMENT_ID', value: receiverDeploymentValidated }
  { name: 'NAIA_KB_COMPILER_VALIDATION_MODE', value: kbCompilerValidationMode }
  { name: 'NAIA_KB_COMPILER_COMMAND', value: kbCompilerCommand }
  { name: 'NAIA_KB_COMPILER_TIMEOUT_SECONDS', value: string(kbCompilerTimeoutSeconds) }
  { name: 'NAIA_KB_COMPILER_MAX_RESPONSE_BYTES', value: string(kbCompilerMaxResponseBytes) }
  { name: 'NAIA_KB_COMPILER_CONTRACT_MAX_BYTES', value: string(kbCompilerContractMaxBytes) }
  { name: 'AZURE_AI_FOUNDRY_REGION', value: foundryRegion }
  { name: 'AZURE_AI_FOUNDRY_ENDPOINT', value: foundryEndpoint }
  { name: 'AZURE_AI_FOUNDRY_DEPLOYMENT', value: foundryDeployment }
  { name: 'AZURE_AI_FOUNDRY_REASONING_EFFORT', value: 'low' }
  { name: 'AZURE_AI_FOUNDRY_MAX_COMPLETION_TOKENS', value: '1024' }
  { name: 'AZURE_AI_FOUNDRY_AUTH_MODE', value: 'managed_identity' }
  { name: 'AZURE_CLIENT_ID', value: jobIdentity!.properties.clientId }
  { name: 'AZURE_STORAGE_BLOB_URL', value: 'https://${storageAccountName}.blob.${az.environment().suffixes.storage}' }
]

var openRouterEnv = secretConfiguredValidated ? [
  { name: 'OPENROUTER_API_KEY', secretRef: 'openrouter-api-key' }
] : []

var effectiveSchedule = enableSchedule && policyNewsEnabledValidated && !policyNewsDryRun && compilerConfigured && secretConfiguredValidated

var jobTrigger = effectiveSchedule ? {
  triggerType: 'Schedule'
  scheduleTriggerConfig: {
    cronExpression: cronExpression
    parallelism: 1
    replicaCompletionCount: 1
  }
} : {
  triggerType: 'Manual'
  manualTriggerConfig: {
    parallelism: 1
    replicaCompletionCount: 1
  }
}

resource job 'Microsoft.App/jobs@2025-01-01' = if (deployInfrastructure && deployJob) {
  name: jobName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${jobIdentity!.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: union({
      replicaRetryLimit: replicaRetryLimit
      replicaTimeout: replicaTimeoutSeconds
      registries: [
        {
          server: '${registryName}.azurecr.io'
          identity: jobIdentity!.id
        }
      ]
      secrets: secretConfiguredValidated ? [
        {
          name: 'openrouter-api-key'
          keyVaultUrl: openRouterSecretUriValidated
          identity: jobIdentity!.id
        }
      ] : []
    }, jobTrigger)
    template: {
      containers: [
        {
          name: 'policy-news'
          image: containerImageValidated
          env: concat(baseEnv, openRouterEnv)
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
  }
  tags: tags
  dependsOn: [
    acrPullRole
    keyVaultSecretRole
  ]
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = if (secretConfiguredValidated) {
  name: keyVaultName
}

resource openRouterSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = if (secretConfiguredValidated) {
  parent: keyVault
  name: openRouterSecretName
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var storageBlobContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployInfrastructure && deployJob) {
  name: guid(registry.id, jobIdentity!.id, acrPullRoleId)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: jobIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource runsBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployInfrastructure && deployJob) {
  name: guid(runsContainer.id, jobIdentity!.id, storageBlobContributorRoleId)
  scope: runsContainer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobContributorRoleId)
    principalId: jobIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource sourcesBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployInfrastructure && deployJob) {
  name: guid(sourcesContainer.id, jobIdentity!.id, storageBlobContributorRoleId)
  scope: sourcesContainer
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobContributorRoleId)
    principalId: jobIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource foundryInferenceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployInfrastructure && deployJob) {
  name: guid(foundry.id, jobIdentity!.id, cognitiveServicesUserRoleId)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: jobIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVaultSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployInfrastructure && deployJob && secretConfiguredValidated) {
  name: guid(openRouterSecret!.id, jobIdentity!.id, keyVaultSecretsUserRoleId)
  scope: openRouterSecret
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: jobIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output infrastructureConfigured bool = deployInfrastructure
output jobConfigured bool = deployInfrastructure && deployJob
output scheduleEnabled bool = deployInfrastructure && deployJob && effectiveSchedule
output runtimeEnabled bool = policyNewsEnabledValidated
output jobPrincipalId string = deployInfrastructure && deployJob ? jobIdentity!.properties.principalId : ''
output jobIdentityClientId string = deployInfrastructure && deployJob ? jobIdentity!.properties.clientId : ''
output jobIdentityResourceId string = deployInfrastructure && deployJob ? jobIdentity!.id : ''
output storageBlobUrl string = deployInfrastructure ? 'https://${storageAccountName}.blob.${az.environment().suffixes.storage}' : ''
output registryLoginServer string = deployInfrastructure ? '${registryName}.azurecr.io' : ''
output expectedResourceGroup string = expectedResourceGroupName
output resourceGroupScopeAccepted bool = resourceGroupNameValidated == expectedResourceGroupName
