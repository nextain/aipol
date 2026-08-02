targetScope = 'resourceGroup'

param deployFoundation bool = false
param configureRuntimeAccess bool = false
param deployApp bool = false
@description('Create/reconcile the immutability policy only before it is locked. Set false after lock.')
param manageAuditPolicy bool = false

@allowed(['rg_aipol'])
param expectedResourceGroupName string = 'rg_aipol'
@allowed(['koreacentral'])
param location string = 'koreacentral'

@description('Exact approved ACR repository plus sha256:64 lowercase hex.')
param containerImage string = 'acraipolprod01.azurecr.io/policy-lab-event@sha256:REPLACE_WITH_64_LOWERCASE_HEX'
param revisionSuffix string = 'not-deployed'

@allowed([true])
param enableExternalIngress bool = true
@allowed([false])
param collectionEnabled bool = false
@allowed([false])
param chatbotEnabled bool = false
@allowed([false])
param batchEnabled bool = false
@allowed([false])
param receiptVerifierEnabled bool = false

param auditImmutabilityPolicyLocked bool = false
param auditImmutabilityLockEvidenceId string = ''
param eventSessionSecretVersion string = ''
param eventAdminUsersSecretVersion string = ''
param eventAdminRolesSecretVersion string = ''
param eventAdminTotpSecretVersion string = ''
param eventCredentialKeysetVersion string = ''
param eventAuditCheckpointKeysetVersion string = ''
param eventCredentialActiveKeyId string = ''
param eventAuditCheckpointActiveKeyId string = ''
@minValue(900)
@maxValue(2592000)
param syntheticReviewTtlSeconds int = 604800

@allowed(['aipol-session-prod'])
param containerAppName string = 'aipol-session-prod'
@allowed(['cae-aipol-prod'])
param environmentName string = 'cae-aipol-prod'
@allowed(['eventstore'])
param environmentStorageName string = 'eventstore'
@allowed(['eventdata'])
param fileShareName string = 'eventdata'
@allowed(['staipolprod01'])
param storageAccountName string = 'staipolprod01'
@allowed(['aipol-audit-checkpoints'])
param auditCheckpointContainerName string = 'aipol-audit-checkpoints'
@allowed(['uami-aipol-prod'])
param identityName string = 'uami-aipol-prod'
@allowed(['acraipolprod01'])
param registryName string = 'acraipolprod01'
@allowed(['policy-lab-event'])
param containerRepository string = 'policy-lab-event'
@allowed(['kv-aipol-prod-01'])
param keyVaultName string = 'kv-aipol-prod-01'
@allowed(['aipol.kaps.or.kr'])
param dnsZoneName string = 'aipol.kaps.or.kr'
@allowed(['rg-nextain-koreacentral'])
param dnsZoneResourceGroupName string = 'rg-nextain-koreacentral'
param trustedProxyCidrs string = ''
param customDomainName string = ''
param customDomainCertificateId string = ''

@description('Exact Git commit presented in the professor-review snapshot (40 lowercase hex).')
param reviewBuildCommit string = ''
@description('SHA-256 of the reviewed database seed (64 lowercase hex).')
param reviewDbSeedHash string = ''
@description('Immutable deployment revision presented in the professor-review snapshot.')
param reviewDeploymentRevision string = ''
@description('Exact HTTPS origin used by the professor-review browser.')
param reviewPublicOrigin string = ''

var tags = {
  project: 'AIPOL'
  component: 'event-tool'
  environment: 'production'
  owner: 'nextain'
  managedBy: 'bicep'
  stateful: 'true'
}
var expectedImagePrefix = '${registryName}.azurecr.io/${containerRepository}@sha256:'
var imageParts = split(containerImage, '@sha256:')
var imageDigest = length(imageParts) == 2 ? imageParts[1] : ''
var digestRemainder = replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(imageDigest, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), 'f', '')
var imageGuard = startsWith(containerImage, expectedImagePrefix) && length(containerImage) == length(expectedImagePrefix) + 64 && length(imageDigest) == 64 && empty(digestRemainder)
var safetyGuard = enableExternalIngress && !collectionEnabled && !chatbotEnabled && !batchEnabled && !receiptVerifierEnabled
var secretsGuard = !empty(eventSessionSecretVersion) && !empty(eventAdminUsersSecretVersion) && !empty(eventAdminRolesSecretVersion) && !empty(eventAdminTotpSecretVersion) && !empty(eventCredentialKeysetVersion) && !empty(eventAuditCheckpointKeysetVersion) && !empty(eventCredentialActiveKeyId) && !empty(eventAuditCheckpointActiveKeyId)
var reviewPinGuard = length(reviewBuildCommit) == 40 && length(reviewDbSeedHash) == 64 && reviewDeploymentRevision == '${containerAppName}--${revisionSuffix}' && revisionSuffix != 'not-deployed' && startsWith(reviewPublicOrigin, 'https://')
var resourceGroupGuard = resourceGroup().name == expectedResourceGroupName
var foundationGuard = deployFoundation && resourceGroupGuard
var provisionAuditPolicy = foundationGuard && manageAuditPolicy
var configureAccess = foundationGuard && configureRuntimeAccess
var provisionApp = foundationGuard && configureRuntimeAccess && deployApp && imageGuard && safetyGuard && secretsGuard && reviewPinGuard && auditImmutabilityPolicyLocked && !empty(auditImmutabilityLockEvidenceId)


resource dnsZone 'Microsoft.Network/dnsZones@2018-05-01' existing = {
  name: dnsZoneName
  scope: resourceGroup(subscription().subscriptionId, dnsZoneResourceGroupName)
}

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = if (foundationGuard) {
  name: registryName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    dataEndpointEnabled: false
    publicNetworkAccess: 'Enabled'
    policies: {
      azureADAuthenticationAsArmPolicy: { status: 'enabled' }
    }
  }
  tags: tags
}

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = if (foundationGuard) {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    // Required by the current Container Apps Azure Files environment-storage contract.
    allowSharedKeyAccess: true
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
  }
  tags: tags
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2025-01-01' = if (foundationGuard) {
  parent: storage
  name: 'default'
  properties: {
    shareDeleteRetentionPolicy: { enabled: true, days: 14 }
  }
}
resource stateShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2025-01-01' = if (foundationGuard) {
  parent: fileService
  name: fileShareName
  properties: {
    accessTier: 'TransactionOptimized'
    enabledProtocols: 'SMB'
    shareQuota: 5
  }
}
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = if (foundationGuard) {
  parent: storage
  name: 'default'
  properties: {
    containerDeleteRetentionPolicy: { enabled: true, days: 30 }
    deleteRetentionPolicy: { enabled: true, days: 30 }
    isVersioningEnabled: true
  }
}
resource auditContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = if (foundationGuard) {
  parent: blobService
  name: auditCheckpointContainerName
  properties: {
    immutableStorageWithVersioning: { enabled: true }
    publicAccess: 'None'
  }
}
resource auditPolicy 'Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies@2025-01-01' = if (provisionAuditPolicy) {
  parent: auditContainer
  name: 'default'
  properties: {
    allowProtectedAppendWrites: false
    allowProtectedAppendWritesAll: false
    immutabilityPeriodSinceCreationInDays: 365
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = if (foundationGuard) {
  name: environmentName
  location: location
  properties: { zoneRedundant: false }
  tags: tags
}
resource environmentStorage 'Microsoft.App/managedEnvironments/storages@2025-01-01' = if (foundationGuard) {
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
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = if (foundationGuard) {
  name: identityName
  location: location
  tags: tags
}
resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' = if (foundationGuard) {
  name: keyVaultName
  location: location
  properties: {
    accessPolicies: []
    enablePurgeProtection: true
    enableRbacAuthorization: true
    enableSoftDelete: true
    publicNetworkAccess: 'Enabled'
    softDeleteRetentionInDays: 90
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
  }
  tags: tags
}

resource sessionSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-session-secret'
}
resource usersSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-admin-users-json-b64'
}
resource rolesSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-admin-roles-json-b64'
}
resource totpSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-admin-totp-secrets-json-b64'
}
resource credentialSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-credential-secrets-json-b64'
}
resource auditSecret 'Microsoft.KeyVault/vaults/secrets@2024-11-01' existing = {
  parent: keyVault
  name: 'event-audit-checkpoint-secrets-json-b64'
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var secretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (configureAccess) {
  name: guid(registry.id, identity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: identity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

resource sessionSecretRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (configureAccess) {
  name: guid(sessionSecret.id, identity.id, secretsUserRoleId)
  scope: sessionSecret
  properties: {
    principalId: identity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
  }
}
resource usersSecretRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (configureAccess) {
  name: guid(usersSecret.id, identity.id, secretsUserRoleId)
  scope: usersSecret
  properties: {
    principalId: identity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
  }
}
resource rolesSecretRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (configureAccess) {
  name: guid(rolesSecret.id, identity.id, secretsUserRoleId)
  scope: rolesSecret
  properties: {
    principalId: identity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
  }
}
resource totpSecretRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (configureAccess) {
  name: guid(totpSecret.id, identity.id, secretsUserRoleId)
  scope: totpSecret
  properties: {
    principalId: identity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
  }
}
resource credentialSecretRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (configureAccess) {
  name: guid(credentialSecret.id, identity.id, secretsUserRoleId)
  scope: credentialSecret
  properties: {
    principalId: identity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
  }
}
resource auditSecretRead 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (configureAccess) {
  name: guid(auditSecret.id, identity.id, secretsUserRoleId)
  scope: auditSecret
  properties: {
    principalId: identity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRoleId)
  }
}

resource auditWriterRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = if (foundationGuard) {
  name: guid(resourceGroup().id, 'aipol-audit-create-only-prod')
  properties: {
    roleName: 'AIPOL Production Audit Create-only Writer'
    description: 'Read and create immutable audit blobs without delete or policy-management actions.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [
      {
        actions: ['Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies/read']
        notActions: []
        dataActions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'
        ]
        notDataActions: [
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/delete'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/deleteBlobVersion/action'
          'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/permanentDelete/action'
        ]
      }
    ]
  }
}
resource auditWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (foundationGuard) {
  name: guid(auditContainer.id, identity.id, auditWriterRole.id)
  scope: auditContainer
  properties: {
    principalId: identity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: auditWriterRole.id
  }
}

var vaultUri = 'https://${keyVaultName}${az.environment().suffixes.keyvaultDns}/'
var appSecrets = [
  { name: 'session-secret', identity: identity.id, keyVaultUrl: '${vaultUri}secrets/event-session-secret/${eventSessionSecretVersion}' }
  { name: 'admin-users-b64', identity: identity.id, keyVaultUrl: '${vaultUri}secrets/event-admin-users-json-b64/${eventAdminUsersSecretVersion}' }
  { name: 'admin-roles-b64', identity: identity.id, keyVaultUrl: '${vaultUri}secrets/event-admin-roles-json-b64/${eventAdminRolesSecretVersion}' }
  { name: 'admin-totp-b64', identity: identity.id, keyVaultUrl: '${vaultUri}secrets/event-admin-totp-secrets-json-b64/${eventAdminTotpSecretVersion}' }
  { name: 'credential-secrets-b64', identity: identity.id, keyVaultUrl: '${vaultUri}secrets/event-credential-secrets-json-b64/${eventCredentialKeysetVersion}' }
  { name: 'audit-checkpoint-secrets-b64', identity: identity.id, keyVaultUrl: '${vaultUri}secrets/event-audit-checkpoint-secrets-json-b64/${eventAuditCheckpointKeysetVersion}' }
]
var runtimeEnv = [
  { name: 'EVENT_ENV', value: 'production' }
  { name: 'EVENT_DEMO_ENABLED', value: 'false' }
  { name: 'EVENT_DB_PATH', value: '/data/event.db' }
  { name: 'EVENT_ROSTER_PATH', value: '/data/roster.json' }
  { name: 'EVENT_SQLITE_NOLOCK', value: 'true' }
  { name: 'EVENT_SESSION_TTL_SECONDS', value: '3600' }
  { name: 'AIPOL_SYNTHETIC_REVIEW_TTL_SECONDS', value: string(syntheticReviewTtlSeconds) }
  { name: 'AIPOL_CHATBOT_PUBLIC_ENABLED', value: 'false' }
  { name: 'AIPOL_BATCH_AZURE_ENABLED', value: 'false' }
  { name: 'AIPOL_RECEIPT_VERIFIER_MODE', value: 'disabled' }
  { name: 'AIPOL_TRUSTED_PROXY_CIDRS', value: trustedProxyCidrs }
  { name: 'AIPOL_BUILD_COMMIT', value: reviewBuildCommit }
  { name: 'AIPOL_IMAGE_DIGEST', value: 'sha256:${imageDigest}' }
  { name: 'AIPOL_DB_INSTANCE_ID', value: '${storageAccountName}/${fileShareName}/event.db' }
  { name: 'AIPOL_DB_SEED_HASH', value: reviewDbSeedHash }
  { name: 'AIPOL_DEPLOYMENT_REVISION', value: reviewDeploymentRevision }
  { name: 'AIPOL_PUBLIC_ORIGIN', value: reviewPublicOrigin }
  { name: 'AZURE_CLIENT_ID', value: identity!.properties.clientId }
  { name: 'EVENT_SESSION_SECRET', secretRef: 'session-secret' }
  { name: 'EVENT_ADMIN_USERS_JSON_B64', secretRef: 'admin-users-b64' }
  { name: 'EVENT_ADMIN_ROLES_JSON_B64', secretRef: 'admin-roles-b64' }
  { name: 'EVENT_ADMIN_TOTP_SECRETS_JSON_B64', secretRef: 'admin-totp-b64' }
  { name: 'EVENT_CREDENTIAL_SECRETS_JSON_B64', secretRef: 'credential-secrets-b64' }
  { name: 'EVENT_CREDENTIAL_ACTIVE_KEY_ID', value: eventCredentialActiveKeyId }
  { name: 'AIPOL_AUDIT_CHECKPOINT_MODE', value: 'azure_blob' }
  { name: 'AIPOL_AUDIT_CHECKPOINT_CONTAINER_URL', value: 'https://${storageAccountName}.blob.${az.environment().suffixes.storage}/${auditCheckpointContainerName}' }
  { name: 'AIPOL_AUDIT_IMMUTABILITY_POLICY_RESOURCE_ID', value: auditPolicy.id }
  { name: 'AIPOL_AUDIT_CHECKPOINT_SECRETS_JSON_B64', secretRef: 'audit-checkpoint-secrets-b64' }
  { name: 'AIPOL_AUDIT_CHECKPOINT_ACTIVE_KEY_ID', value: eventAuditCheckpointActiveKeyId }
]

resource app 'Microsoft.App/containerApps@2025-01-01' = if (provisionApp) {
  name: containerAppName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: true
        targetPort: 8100
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        transport: 'auto'
        customDomains: !empty(customDomainName) && !empty(customDomainCertificateId) ? [
          {
            name: customDomainName
            bindingType: 'SniEnabled'
            certificateId: customDomainCertificateId
          }
        ] : []
      }
      registries: [
        {
          identity: identity.id
          server: '${registryName}.azurecr.io'
        }
      ]
      secrets: appSecrets
    }
    template: {
      revisionSuffix: revisionSuffix
      containers: [
        {
          name: 'aipol-session-prod'
          image: containerImage
          command: ['uvicorn']
          args: ['serialized_app:app', '--host', '0.0.0.0', '--port', '8100', '--workers', '1', '--no-proxy-headers']
          env: runtimeEnv
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8100
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
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
              volumeName: 'eventdata'
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
          name: 'eventdata'
          storageName: environmentStorage.name
          storageType: 'AzureFile'
        }
      ]
    }
  }
  tags: tags
  dependsOn: [
    acrPull
    sessionSecretRead
    usersSecretRead
    rolesSecretRead
    totpSecretRead
    credentialSecretRead
    auditSecretRead
    auditWriter
  ]
}

output dedicatedResourceGroup string = expectedResourceGroupName
output approvedImagePrefix string = expectedImagePrefix
output immutableImageAccepted bool = imageGuard
output safetyFlagsAccepted bool = safetyGuard
output resourceGroupAccepted bool = resourceGroupGuard
output foundationConfigured bool = foundationGuard
output runtimeAccessConfigured bool = configureAccess
output appConfigured bool = provisionApp
output appFqdn string = provisionApp ? app!.properties.configuration.ingress.fqdn : ''
output externalDnsZoneResourceId string = dnsZone.id
output dnsMutationIncluded bool = false
output auditPolicyResourceId string = resourceId('Microsoft.Storage/storageAccounts/blobServices/containers/immutabilityPolicies', storageAccountName, 'default', auditCheckpointContainerName, 'default')
