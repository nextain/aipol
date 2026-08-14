targetScope = 'resourceGroup'

param environmentName string = 'cae-aipol-prod'
param registryName string = 'acraipolprod01'
param storageAccountName string = 'staipolprod01'
param identityName string = 'uami-aipol-policy-news-prod'
param keyVaultName string = 'kv-aipol-prod-01'
param jobName string = 'aipol-policy-news-daily'

@description('Immutable ACR image reference. Tags are rejected.')
param containerImage string

@allowed(['0 21 * * *'])
@description('Fixed daily 06:00 KST schedule, expressed in UTC.')
param cronExpression string = '0 21 * * *'

@description('Switch to schedule only after a verified manual execution of this exact digest.')
param enableSchedule bool = false
param policyNewsEnabled bool = false
param manualRunVerified bool = false
param manualRunImageDigest string = ''
param manualRunExecutionName string = ''
param manualRunConfigurationFingerprint string = ''
param manualRunEvidenceSha256 string = ''

@allowed(['pending', 'passed', 'failed'])
param providerQualityStatus string = 'pending'
param providerQualityEvidenceSha256 string = ''

@secure()
@description('Versioned policy-news-anyllm-key URI.')
param anyllmSecretUri string = ''

@allowed(['https://api.nextain.io/v1'])
param anyllmEndpoint string = 'https://api.nextain.io/v1'

@allowed(['upstage:solar-pro4'])
param anyllmAnalysisModel string = 'upstage:solar-pro4'

@allowed(['azure:deepseek-v4-pro'])
param anyllmVerificationModel string = 'azure:deepseek-v4-pro'

@allowed(['azure:gpt-5.6-luna'])
param anyllmTranslationModel string = 'azure:gpt-5.6-luna'

@allowed(['azure:deepseek-v4-flash'])
param anyllmReviewModel string = 'azure:deepseek-v4-flash'

@minValue(1)
@maxValue(3)
param maxItemsPerRun int = 3

@allowed(['2.00'])
@description('Conservative per-execution reservation ceiling for three draft and review pairs.')
param maxEstimatedCostUsd string = '2.00'

@allowed([2048])
@description('Fixed completion ceiling large enough for the strict adversarial-review JSON envelope.')
param maxCompletionTokens int = 2048

@minValue(60)
@maxValue(1800)
param replicaTimeoutSeconds int = 600

@allowed([0])
param replicaRetryLimit int = 0

param runsContainerName string = 'policy-news-runs'
param sourcesContainerName string = 'policy-news-sources'

var tags = {
  project: 'AIPOL'
  component: 'policy-news-job'
  environment: 'prod'
  owner: 'nextain'
  managedBy: 'bicep'
}

var expectedResourceGroupName = 'rg_aipol'
var resourceGroupNameValidated = resourceGroup().name == expectedResourceGroupName ? true : fail('This template may only target rg_aipol')
var fixedResourceNamesValid = environmentName == 'cae-aipol-prod' && registryName == 'acraipolprod01' && storageAccountName == 'staipolprod01' && identityName == 'uami-aipol-policy-news-prod' && keyVaultName == 'kv-aipol-prod-01' && jobName == 'aipol-policy-news-daily'
var fixedResourceNamesValidated = fixedResourceNamesValid ? true : fail('Production resource names are fixed for the AIPOL policy-news job')

var approvedImagePrefix = '${registryName}.azurecr.io/aipol/policy-news@sha256:'
var imageDigest = startsWith(containerImage, approvedImagePrefix) ? substring(containerImage, length(approvedImagePrefix)) : ''
var imageDigestRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(imageDigest, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var imageValidated = length(imageDigest) == 64 && imageDigest == toLower(imageDigest) && empty(imageDigestRemainder) ? containerImage : fail('containerImage must use the exact AIPOL policy-news ACR repository and a lowercase sha256 digest')

var qualityDigest = length(providerQualityEvidenceSha256) == 64 ? providerQualityEvidenceSha256 : ''
var qualityDigestRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(qualityDigest, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var qualityApproved = providerQualityStatus == 'passed' && length(qualityDigest) == 64 && qualityDigest == toLower(qualityDigest) && empty(qualityDigestRemainder)

var manualDigest = length(manualRunEvidenceSha256) == 64 ? manualRunEvidenceSha256 : ''
var manualDigestRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(manualDigest, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var vaultSecretPrefix = 'https://${keyVaultName}${az.environment().suffixes.keyvaultDns}/secrets/'
var anyllmSecretPrefix = '${vaultSecretPrefix}policy-news-anyllm-key/'
var anyllmVersion = startsWith(anyllmSecretUri, anyllmSecretPrefix) ? substring(anyllmSecretUri, length(anyllmSecretPrefix)) : ''
var anyllmVersionRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(anyllmVersion, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var secretsValid = length(anyllmVersion) == 32 && anyllmVersion == toLower(anyllmVersion) && empty(anyllmVersionRemainder)
var runtimeConfigurationFingerprint = base64('${imageDigest}|${qualityDigest}|${anyllmVersion}|${anyllmEndpoint}|${anyllmAnalysisModel}|${anyllmVerificationModel}|${anyllmTranslationModel}|${anyllmReviewModel}|${maxItemsPerRun}|${maxEstimatedCostUsd}|${maxCompletionTokens}|${cronExpression}|${replicaTimeoutSeconds}|${replicaRetryLimit}')
var manualReceiptValid = manualRunVerified && manualRunImageDigest == imageDigest && startsWith(manualRunExecutionName, '${jobName}-') && manualRunConfigurationFingerprint == runtimeConfigurationFingerprint && length(manualDigest) == 64 && manualDigest == toLower(manualDigest) && empty(manualDigestRemainder)
var runtimeEnabled = !policyNewsEnabled ? false : qualityApproved && secretsValid ? true : fail('policyNewsEnabled requires passed private quality evidence and exact versioned AIPOL secrets')
var scheduleEnabled = !enableSchedule ? false : runtimeEnabled && manualReceiptValid ? true : fail('enableSchedule requires a successful manual execution receipt for this exact image digest')

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = { name: environmentName }
resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' existing = { name: registryName }
resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' existing = { name: storageAccountName }
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' existing = { parent: storage, name: 'default' }

resource runsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: runsContainerName
  properties: { publicAccess: 'None' }
}
resource sourcesContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobService
  name: sourcesContainerName
  properties: { publicAccess: 'None' }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
  location: resourceGroup().location
  tags: tags
}
resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' existing = { name: keyVaultName }
resource anyllmSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = if (runtimeEnabled) { parent: keyVault, name: 'policy-news-anyllm-key' }

module blobRole 'blob-role.bicep' = {
  name: 'aipol-policy-news-blob-no-delete-role'
  scope: subscription()
  params: { assignableScope: resourceGroup().id }
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var blobNoDeleteRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', guid(subscription().id, 'aipol-policy-news-blob-no-delete'))

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, identity.id, acrPullRoleId)
  scope: registry
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId), principalId: identity.properties.principalId, principalType: 'ServicePrincipal' }
}
resource runsBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (runtimeEnabled) {
  name: guid(runsContainer.id, identity.id, blobNoDeleteRoleId)
  scope: runsContainer
  properties: { roleDefinitionId: blobNoDeleteRoleId, principalId: identity.properties.principalId, principalType: 'ServicePrincipal' }
  dependsOn: [blobRole]
}
resource sourcesBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (runtimeEnabled) {
  name: guid(sourcesContainer.id, identity.id, blobNoDeleteRoleId)
  scope: sourcesContainer
  properties: { roleDefinitionId: blobNoDeleteRoleId, principalId: identity.properties.principalId, principalType: 'ServicePrincipal' }
  dependsOn: [blobRole]
}
resource anyllmSecretRole 'Microsoft.KeyVault/vaults/secrets/providers/roleAssignments@2022-04-01' = if (runtimeEnabled) {
  name: '${keyVaultName}/policy-news-anyllm-key/Microsoft.Authorization/${guid(anyllmSecret!.id, identity.id, keyVaultSecretsUserRoleId, 'secret-scope-v2')}'
  properties: { roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId), principalId: identity.properties.principalId, principalType: 'ServicePrincipal' }
}

var baseEnv = [
  { name: 'POLICY_NEWS_ENABLED', value: string(runtimeEnabled) }
  { name: 'POLICY_NEWS_DRY_RUN', value: 'false' }
  { name: 'POLICY_NEWS_MAX_ITEMS', value: string(maxItemsPerRun) }
  { name: 'POLICY_NEWS_MAX_CALLS', value: '12' }
  { name: 'POLICY_NEWS_MAX_COST_USD', value: maxEstimatedCostUsd }
  { name: 'POLICY_NEWS_ESTIMATED_ANALYSIS_COST_USD', value: '0.10' }
  { name: 'POLICY_NEWS_ESTIMATED_VERIFICATION_COST_USD', value: '0.10' }
  { name: 'POLICY_NEWS_ESTIMATED_TRANSLATION_COST_USD', value: '0.10' }
  { name: 'POLICY_NEWS_ESTIMATED_REVIEW_COST_USD', value: '0.05' }
  { name: 'POLICY_NEWS_MAX_ATTEMPTS', value: '2' }
  { name: 'POLICY_NEWS_TIMEOUT_SECONDS', value: '240' }
  { name: 'AZURE_AI_FOUNDRY_MAX_COMPLETION_TOKENS', value: string(maxCompletionTokens) }
  { name: 'POLICY_NEWS_DRAFT_PROVIDER', value: 'anyllm' }
  { name: 'POLICY_NEWS_REVIEW_PROVIDER', value: 'anyllm' }
  { name: 'POLICY_NEWS_PROVIDER_APPROVAL', value: providerQualityStatus }
  { name: 'POLICY_NEWS_PROVIDER_EVIDENCE_SHA256', value: providerQualityEvidenceSha256 }
  { name: 'POLICY_NEWS_REQUIRE_KB_COMPILE', value: 'false' }
  { name: 'POLICY_NEWS_KB_COMPILER_MODE', value: 'disabled' }
  { name: 'ANYLLM_ENDPOINT', value: anyllmEndpoint }
  { name: 'ANYLLM_ANALYSIS_MODEL', value: anyllmAnalysisModel }
  { name: 'ANYLLM_VERIFICATION_MODEL', value: anyllmVerificationModel }
  { name: 'ANYLLM_MODEL', value: anyllmTranslationModel }
  { name: 'ANYLLM_REVIEW_MODEL', value: anyllmReviewModel }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
  { name: 'AZURE_STORAGE_BLOB_URL', value: 'https://${storageAccountName}.blob.${az.environment().suffixes.storage}' }
]
var providerEnv = runtimeEnabled ? [
  { name: 'ANYLLM_API_KEY', secretRef: 'anyllm-api-key' }
] : []
var jobSecrets = runtimeEnabled ? [
  { name: 'anyllm-api-key', keyVaultUrl: anyllmSecretUri, identity: identity.id }
] : []
var trigger = scheduleEnabled ? {
  triggerType: 'Schedule'
  scheduleTriggerConfig: { cronExpression: cronExpression, parallelism: 1, replicaCompletionCount: 1 }
} : {
  triggerType: 'Manual'
  manualTriggerConfig: { parallelism: 1, replicaCompletionCount: 1 }
}

resource job 'Microsoft.App/jobs@2025-01-01' = {
  name: jobName
  location: resourceGroup().location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: union({
      replicaRetryLimit: replicaRetryLimit
      replicaTimeout: replicaTimeoutSeconds
      registries: [{ server: '${registryName}.azurecr.io', identity: identity.id }]
      secrets: jobSecrets
    }, trigger)
    template: {
      containers: [{
        name: 'policy-news'
        image: imageValidated
        command: ['python']
        args: ['scheduled_job.py']
        env: concat(baseEnv, providerEnv)
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
      }]
    }
  }
  tags: tags
  dependsOn: [acrPullRole, runsBlobRole, sourcesBlobRole, anyllmSecretRole]
}

output resourceGroupScopeAccepted bool = resourceGroupNameValidated
output fixedResourceNamesAccepted bool = fixedResourceNamesValidated
output runtimeEnabled bool = runtimeEnabled
output scheduleEnabled bool = scheduleEnabled
output selectedAnalysisModel string = anyllmAnalysisModel
output selectedVerificationModel string = anyllmVerificationModel
output selectedTranslationModel string = anyllmTranslationModel
output selectedReviewModel string = anyllmReviewModel
output runtimeConfigurationFingerprint string = runtimeConfigurationFingerprint
output jobName string = job.name
output jobIdentityPrincipalId string = identity.properties.principalId
output storageBlobUrl string = 'https://${storageAccountName}.blob.${az.environment().suffixes.storage}'
