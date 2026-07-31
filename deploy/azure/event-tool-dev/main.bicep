targetScope = 'resourceGroup'

@description('Provision the isolated development infrastructure. False makes validation and compilation the default behavior.')
param deployInfrastructure bool = false

@description('Create the Container App after the image and Key Vault secrets exist. Requires deployInfrastructure=true.')
param deployApp bool = false

@description('Azure region for the development backend.')
param location string = 'koreacentral'

@description('Container image pinned to an immutable tag or digest. Build and push it before deployApp=true.')
param containerImage string = '${registryName}.azurecr.io/aipol/event-tool:bootstrap-not-built'

@description('Keep public ingress off until an explicit exposure review is complete.')
@allowed([false])
param enableExternalIngress bool = false

@description('Top-level collection kill switch. The development deployment defaults to disabled.')
@allowed([false])
param collectionEnabled bool = false

@description('Grounded chatbot kill switch. The development deployment defaults to disabled.')
@allowed([false])
param chatbotEnabled bool = false

@description('Background or scheduled batch kill switch. The development deployment defaults to disabled.')
param batchEnabled bool = false

@description('Existing policy-news Container Apps Job controlled by the admin when batchEnabled=true.')
param policyNewsJobName string = 'caj-aipol-policy-news-daily-dev'

@description('Pinned Key Vault version for event-session-secret. Required only when deployApp=true.')
param eventSessionSecretVersion string = ''

@description('Pinned Key Vault version for event-admin-users-json. Required only when deployApp=true.')
param eventAdminUsersSecretVersion string = ''

@description('Pinned Key Vault version for event-admin-roles-json. Required only when deployApp=true.')
param eventAdminRolesSecretVersion string = ''

@description('Pinned Key Vault version for event-admin-totp-secrets-json. Required only when deployApp=true.')
param eventAdminTotpSecretVersion string = ''

@description('Pinned Key Vault version for event-credential-secrets-json. Required when deployApp=true.')
param eventCredentialKeysetVersion string = ''

@description('Active credential key id used only for newly created experiments.')
param eventCredentialActiveKeyId string = ''

@description('Pinned Key Vault version for event-audit-checkpoint-secrets-json. Required when deployApp=true.')
param eventAuditCheckpointKeysetVersion string = ''

@description('Active HMAC key id for newly created audit checkpoints.')
param eventAuditCheckpointActiveKeyId string = ''

@description('True only after the runbook records Azure state=Locked for the named policy. Never set manually.')
param auditImmutabilityPolicyLocked bool = false

@description('Immutable deployment evidence id emitted by the policy-lock preflight. Required with auditImmutabilityPolicyLocked=true.')
param auditImmutabilityLockEvidenceId string = ''

@description('Enable the Ed25519 calculator receipt verifier for a reviewed rehearsal.')
param receiptVerifierEnabled bool = false

@description('Pinned Key Vault version for aipol-receipt-ed25519-public-key when receiptVerifierEnabled=true.')
param receiptPublicKeySecretVersion string = ''

@description('Pinned receipt key id expected in JWS protected headers and frozen contracts.')
param receiptKeyId string = ''

@description('Expected calculator receipt issuer.')
param receiptIssuer string = ''

@description('Expected calculator receipt audience.')
param receiptAudience string = ''

@minValue(30)
@maxValue(3600)
param receiptMaxTtlSeconds int = 600

@minValue(1)
@maxValue(20)
@description('Azure Files share quota in GiB. Five GiB is sufficient for the development SQLite state.')
param fileShareQuotaGiB int = 5

param containerAppName string = 'ca-aipol-event-tool-dev'
param environmentName string = 'cae-aipol-event-tool-dev'
param environmentStorageName string = 'eventtoolstate'
param fileShareName string = 'event-tool-state'
param auditCheckpointContainerName string = 'aipol-audit-checkpoints'
param identityName string = 'uami-aipol-event-tool-dev'
param storageAccountName string = 'staipolevt${uniqueString(subscription().id, resourceGroup().id)}'
param registryName string = 'acraipolevt${uniqueString(subscription().id, resourceGroup().id)}'
param keyVaultName string = 'kv-aipol-evt-${take(uniqueString(subscription().id, resourceGroup().id), 8)}'

@description('Optional comma-separated proxy CIDRs allowed to supply X-Forwarded-For. Empty trusts no forwarded headers.')
param trustedProxyCidrs string = ''

var tags = {
  project: 'AIPOL'
  component: 'event-tool'
  environment: 'dev'
  owner: 'nextain'
  managedBy: 'bicep'
  stateful: 'true'
}

var resourceGroupGuardPassed = resourceGroup().name == 'rg-aipol-dev'
var receiptInputGuardPassed = !receiptVerifierEnabled || (!empty(receiptPublicKeySecretVersion) && !empty(receiptKeyId) && !empty(receiptIssuer) && !empty(receiptAudience))
var appInputGuardPassed = contains(containerImage, '@sha256:') && !empty(eventSessionSecretVersion) && !empty(eventAdminUsersSecretVersion) && !empty(eventAdminRolesSecretVersion) && !empty(eventAdminTotpSecretVersion) && !empty(eventCredentialKeysetVersion) && !empty(eventCredentialActiveKeyId) && !empty(eventAuditCheckpointKeysetVersion) && !empty(eventAuditCheckpointActiveKeyId) && receiptInputGuardPassed
var featureGuardPassed = !enableExternalIngress && !collectionEnabled && !chatbotEnabled
var provisionInfrastructure = deployInfrastructure && resourceGroupGuardPassed

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = if (provisionInfrastructure) {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    allowBlobPublicAccess: false
    // Container Apps Azure Files (SMB) environment storage currently uses an
    // account key. The key is resolved by ARM and is never stored in this repo.
    allowSharedKeyAccess: true
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
  }
  tags: tags
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2025-01-01' = if (provisionInfrastructure) {
  parent: storage
  name: 'default'
  properties: {
    shareDeleteRetentionPolicy: {
      enabled: true
      days: 14
    }
  }
}

resource stateShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2025-01-01' = if (provisionInfrastructure) {
  parent: fileService
  name: fileShareName
  properties: {
    accessTier: 'TransactionOptimized'
    enabledProtocols: 'SMB'
    shareQuota: fileShareQuotaGiB
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = if (provisionInfrastructure) {
  parent: storage
  name: 'default'
}

// This container is a separate monotonic trust boundary for the SQLite audit
// ledger. immutableStorageWithVersioning can only be enabled at creation.
resource auditCheckpointContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = if (provisionInfrastructure) {
  parent: blobService
  name: auditCheckpointContainerName
  properties: {
    immutableStorageWithVersioning: {
      enabled: true
    }
    publicAccess: 'None'
  }
}

resource auditImmutabilityPolicy 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2025-01-01' = if (provisionInfrastructure) {
  parent: auditCheckpointContainer
  name: 'default'
  properties: {
    allowProtectedAppendWrites: false
    allowProtectedAppendWritesAll: false
    immutabilityPeriodSinceCreationInDays: 365
  }
}

// Azure requires the policy to be locked in a distinct authorized operation.
// The deployment workflow/runbook reads Azure state=Locked and produces the
// evidence id; the app guard rejects a missing or incomplete attestation.
var auditImmutabilityLockGuardPassed = auditImmutabilityPolicyLocked && !empty(auditImmutabilityLockEvidenceId)
var provisionApp = provisionInfrastructure && deployApp && appInputGuardPassed && featureGuardPassed && auditImmutabilityLockGuardPassed

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = if (provisionInfrastructure) {
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
    policies: {
      azureADAuthenticationAsArmPolicy: {
        status: 'enabled'
      }
    }
  }
  tags: tags
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = if (provisionInfrastructure) {
  name: environmentName
  location: location
  properties: {
    zoneRedundant: false
  }
  tags: tags
}

resource environmentStorage 'Microsoft.App/managedEnvironments/storages@2025-01-01' = if (provisionInfrastructure) {
  parent: environment
  name: environmentStorageName
  properties: {
    azureFile: {
      accessMode: 'ReadWrite'
      accountKey: storage!.listKeys().keys[0].value
      accountName: storage.name
      shareName: stateShare.name
    }
  }
}

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (provisionInfrastructure) {
  name: identityName
  location: location
  tags: tags
}

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' = if (provisionInfrastructure) {
  name: keyVaultName
  location: location
  properties: {
    enablePurgeProtection: true
    enableRbacAuthorization: true
    enableSoftDelete: true
    publicNetworkAccess: 'Enabled'
    softDeleteRetentionInDays: 7
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
  }
  tags: tags
}

resource eventSessionSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-session-secret'
}

resource eventAdminUsersSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-admin-users-json'
}

resource eventAdminRolesSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-admin-roles-json'
}

resource eventAdminTotpSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-admin-totp-secrets-json'
}

resource eventCredentialSecrets 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-credential-secrets-json'
}

resource eventAuditCheckpointSecrets 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-audit-checkpoint-secrets-json'
}

resource receiptPublicKeySecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'aipol-receipt-ed25519-public-key'
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var containerAppsJobsOperatorRoleId = 'b9a307c4-5aa3-4b52-ba60-2b17c136cd7b'

// The runtime can list/read and create blobs. It has no delete, permanent
// delete, version-delete, or immutability-policy superuser data action.
resource auditCheckpointWriterRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (provisionInfrastructure) {
  name: guid(resourceGroup().id, 'aipol-audit-checkpoint-create-only')
  properties: {
    roleName: 'AIPOL Audit Checkpoint Create-only Writer'
    description: 'Read and create immutable AIPOL audit checkpoint blobs without delete or policy-management data actions.'
    type: 'CustomRole'
    assignableScopes: [
      resourceGroup().id
    ]
    permissions: [
      {
        actions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/read'
        ]
        notActions: []
        dataActions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'
        ]
        notDataActions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/deleteBlobVersion/action'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/permanentDelete/action'
          'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/runAsSuperUser/action'
        ]
      }
    ]
  }
}

resource policyNewsJob 'Microsoft.App/jobs@2025-01-01' existing = if (provisionApp && batchEnabled) {
  name: policyNewsJobName
}

resource acrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionInfrastructure) {
  name: guid(registry.id, appIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

resource eventSessionSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp) {
  name: guid(eventSessionSecret.id, appIdentity.id, keyVaultSecretsUserRoleId)
  scope: eventSessionSecret
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

resource eventAdminUsersSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp) {
  name: guid(eventAdminUsersSecret.id, appIdentity.id, keyVaultSecretsUserRoleId)
  scope: eventAdminUsersSecret
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

resource eventAdminRolesSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp) {
  name: guid(eventAdminRolesSecret.id, appIdentity.id, keyVaultSecretsUserRoleId)
  scope: eventAdminRolesSecret
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

resource eventAdminTotpSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp) {
  name: guid(eventAdminTotpSecret.id, appIdentity.id, keyVaultSecretsUserRoleId)
  scope: eventAdminTotpSecret
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

resource eventCredentialSecretsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp) {
  name: guid(eventCredentialSecrets.id, appIdentity.id, keyVaultSecretsUserRoleId)
  scope: eventCredentialSecrets
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

resource eventAuditCheckpointSecretsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp) {
  name: guid(eventAuditCheckpointSecrets.id, appIdentity.id, keyVaultSecretsUserRoleId)
  scope: eventAuditCheckpointSecrets
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

resource auditCheckpointWriterRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp) {
  name: guid(auditCheckpointContainer.id, appIdentity.id, auditCheckpointWriterRole.id)
  scope: auditCheckpointContainer
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: auditCheckpointWriterRole.id
  }
}

resource receiptPublicKeySecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp && receiptVerifierEnabled) {
  name: guid(receiptPublicKeySecret.id, appIdentity.id, keyVaultSecretsUserRoleId)
  scope: receiptPublicKeySecret
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
  }
}

// Start and read executions on this one Job only. This role cannot write or
// delete the Job and is not granted at resource-group scope.
resource policyNewsJobOperatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (provisionApp && batchEnabled) {
  name: guid(policyNewsJob.id, appIdentity.id, containerAppsJobsOperatorRoleId)
  scope: policyNewsJob
  properties: {
    principalId: appIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', containerAppsJobsOperatorRoleId)
  }
}

var baseRuntimeEnvironment = [
  { name: 'EVENT_ENV', value: 'development' }
  { name: 'EVENT_DEMO_ENABLED', value: 'false' }
  { name: 'EVENT_DB_PATH', value: '/data/event.db' }
  { name: 'EVENT_ROSTER_PATH', value: '/data/roster.json' }
  { name: 'EVENT_SQLITE_NOLOCK', value: 'true' }
  { name: 'EVENT_SESSION_TTL_SECONDS', value: '3600' }
  { name: 'AIPOL_CHATBOT_PUBLIC_ENABLED', value: string(chatbotEnabled) }
  { name: 'AIPOL_BATCH_AZURE_ENABLED', value: string(batchEnabled) }
  { name: 'AIPOL_BATCH_AZURE_JOB_RESOURCE_ID', value: batchEnabled ? policyNewsJob.id : '' }
  { name: 'AIPOL_TRUSTED_PROXY_CIDRS', value: trustedProxyCidrs }
  { name: 'AZURE_CLIENT_ID', value: appIdentity!.properties.clientId }
  { name: 'EVENT_SESSION_SECRET', secretRef: 'event-session-secret' }
  { name: 'EVENT_ADMIN_USERS_JSON', secretRef: 'event-admin-users-json' }
  { name: 'EVENT_ADMIN_ROLES_JSON', secretRef: 'event-admin-roles-json' }
  { name: 'EVENT_ADMIN_TOTP_SECRETS_JSON', secretRef: 'event-admin-totp-secrets-json' }
  { name: 'EVENT_CREDENTIAL_SECRETS_JSON', secretRef: 'event-credential-secrets-json' }
  { name: 'EVENT_CREDENTIAL_ACTIVE_KEY_ID', value: eventCredentialActiveKeyId }
  { name: 'AIPOL_AUDIT_CHECKPOINT_MODE', value: 'azure_blob' }
  { name: 'AIPOL_AUDIT_CHECKPOINT_CONTAINER_URL', value: 'https://${storage.name}.blob.${az.environment().suffixes.storage}/${auditCheckpointContainer.name}' }
  { name: 'AIPOL_AUDIT_IMMUTABILITY_POLICY_RESOURCE_ID', value: auditImmutabilityPolicy.id }
  { name: 'AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON', secretRef: 'event-audit-checkpoint-secrets-json' }
  { name: 'AIPOL_AUDIT_CHECKPOINT_ACTIVE_KEY_ID', value: eventAuditCheckpointActiveKeyId }
  { name: 'AIPOL_RECEIPT_VERIFIER_MODE', value: receiptVerifierEnabled ? 'ed25519_jws' : 'disabled' }
]

var receiptRuntimeEnvironment = receiptVerifierEnabled ? [
  { name: 'AIPOL_RECEIPT_ED25519_PUBLIC_KEY_B64', secretRef: 'aipol-receipt-ed25519-public-key' }
  { name: 'AIPOL_RECEIPT_KEY_ID', value: receiptKeyId }
  { name: 'AIPOL_RECEIPT_EXPECTED_ISSUER', value: receiptIssuer }
  { name: 'AIPOL_RECEIPT_EXPECTED_AUDIENCE', value: receiptAudience }
  { name: 'AIPOL_RECEIPT_MAX_TTL_SECONDS', value: string(receiptMaxTtlSeconds) }
] : []

var runtimeEnvironment = concat(baseRuntimeEnvironment, receiptRuntimeEnvironment)

var baseAppSecrets = [
  {
    identity: appIdentity.id
    keyVaultUrl: '${keyVault!.properties.vaultUri}secrets/event-session-secret/${eventSessionSecretVersion}'
    name: 'event-session-secret'
  }
  {
    identity: appIdentity.id
    keyVaultUrl: '${keyVault!.properties.vaultUri}secrets/event-admin-users-json/${eventAdminUsersSecretVersion}'
    name: 'event-admin-users-json'
  }
  {
    identity: appIdentity.id
    keyVaultUrl: '${keyVault!.properties.vaultUri}secrets/event-admin-roles-json/${eventAdminRolesSecretVersion}'
    name: 'event-admin-roles-json'
  }
  {
    identity: appIdentity.id
    keyVaultUrl: '${keyVault!.properties.vaultUri}secrets/event-admin-totp-secrets-json/${eventAdminTotpSecretVersion}'
    name: 'event-admin-totp-secrets-json'
  }
  {
    identity: appIdentity.id
    keyVaultUrl: '${keyVault!.properties.vaultUri}secrets/event-credential-secrets-json/${eventCredentialKeysetVersion}'
    name: 'event-credential-secrets-json'
  }
  {
    identity: appIdentity.id
    keyVaultUrl: '${keyVault!.properties.vaultUri}secrets/event-audit-checkpoint-secrets-json/${eventAuditCheckpointKeysetVersion}'
    name: 'event-audit-checkpoint-secrets-json'
  }
]

var receiptAppSecrets = receiptVerifierEnabled ? [
  {
    identity: appIdentity.id
    keyVaultUrl: '${keyVault!.properties.vaultUri}secrets/aipol-receipt-ed25519-public-key/${receiptPublicKeySecretVersion}'
    name: 'aipol-receipt-ed25519-public-key'
  }
] : []

resource app 'Microsoft.App/containerApps@2025-01-01' = if (provisionApp) {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${appIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: enableExternalIngress
        targetPort: 8100
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        transport: 'auto'
      }
      registries: [
        {
          identity: appIdentity.id
          server: '${registryName}.azurecr.io'
        }
      ]
      secrets: concat(baseAppSecrets, receiptAppSecrets)
    }
    template: {
      containers: [
        {
          name: 'event-tool'
          image: containerImage
          env: runtimeEnvironment
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8100
                scheme: 'HTTP'
              }
              initialDelaySeconds: 15
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/readyz'
                port: 8100
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          volumeMounts: [
            {
              mountPath: '/data'
              volumeName: 'event-data'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
      volumes: [
        {
          name: 'event-data'
          storageName: environmentStorageName
          storageType: 'AzureFile'
        }
      ]
    }
  }
  tags: tags
  dependsOn: [
    acrPullRole
    environmentStorage
    eventSessionSecretRole
    eventAdminUsersSecretRole
    eventAdminRolesSecretRole
    eventAdminTotpSecretRole
    eventCredentialSecretsRole
    eventAuditCheckpointSecretsRole
    auditCheckpointWriterRoleAssignment
    receiptPublicKeySecretRole
    policyNewsJobOperatorRole
  ]
}

output expectedResourceGroup string = 'rg-aipol-dev'
output resourceGroupScopeAccepted bool = resourceGroupGuardPassed
output appInputGuardAccepted bool = appInputGuardPassed
output auditImmutabilityLockGuardPassed bool = auditImmutabilityLockGuardPassed
output auditImmutabilityLockEvidenceId string = auditImmutabilityLockEvidenceId
output featureGuardAccepted bool = featureGuardPassed
output infrastructureConfigured bool = provisionInfrastructure
output appConfigured bool = provisionApp
output publicIngressEnabled bool = provisionApp && enableExternalIngress
output batchAzureEnabled bool = provisionApp && batchEnabled
output batchJobResourceId string = provisionApp && batchEnabled ? policyNewsJob.id : ''
output registryLoginServer string = provisionInfrastructure ? '${registryName}.azurecr.io' : ''
output keyVaultResourceName string = provisionInfrastructure ? keyVaultName : ''
output appFqdn string = provisionApp ? app!.properties.configuration.ingress.fqdn : ''
output keyVaultSecretsUserScopeMode string = receiptVerifierEnabled ? 'six-named-secrets-only' : 'five-named-secrets-only'
output vaultWideKeyVaultSecretsUserAllowed bool = false
output blobDataContributorAllowed bool = false
output auditCheckpointDeleteAllowed bool = false
output receiptVerifierConfigured bool = provisionApp && receiptVerifierEnabled
