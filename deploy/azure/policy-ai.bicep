targetScope = 'resourceGroup'

@description('Master infrastructure kill switch. Default false so template validation creates no billable AI resource.')
param deployFoundry bool = false

@description('Model deployment kill switch. Requires deployFoundry=true and explicit quota/model discovery first.')
param deployModel bool = false

@description('Azure region verified by `az cognitiveservices account list-models` before deployment.')
param location string = 'eastus2'

@minLength(2)
@maxLength(64)
@description('Globally unique Microsoft Foundry (AIServices) resource name.')
param foundryAccountName string = 'aipol-ai-${uniqueString(subscription().id, resourceGroup().id)}'

@description('Disable API keys and require Entra ID. Keep true for the production managed-identity path.')
param disableLocalAuth bool = true

@description('Optional Entra object ID allowed to call Foundry inference. Empty creates no role assignment.')
param inferencePrincipalId string = ''

@allowed([
  'User'
  'ServicePrincipal'
  'Group'
])
@description('Principal type for inferencePrincipalId.')
param inferencePrincipalType string = 'ServicePrincipal'

@description('Deployment name supplied as the `model` field to the OpenAI/v1 API.')
param modelDeploymentName string = 'aipol-policy-news-draft-v2'

@description('Catalog model name confirmed by quota/model discovery.')
param modelName string = 'gpt-5.4-mini'

@description('Catalog model version confirmed by quota/model discovery.')
param modelVersion string = '2026-03-17'

@allowed([
  'AI21 Labs'
  'Cohere'
  'Core42'
  'DeepSeek'
  'xAI'
  'Meta'
  'Microsoft'
  'Mistral AI'
  'OpenAI'
])
@description('Provider/format exactly as reported by Azure model discovery.')
param modelPublisherFormat string = 'OpenAI'

@allowed([
  'GlobalStandard'
  'DataZoneStandard'
  'Standard'
  'GlobalProvisioned'
  'Provisioned'
])
@description('Deployment SKU confirmed by Azure model discovery.')
param modelSkuName string = 'DataZoneStandard'

@minValue(1)
@maxValue(1000)
@description('Model capacity. Start at the discovered minimum and use application call/cost caps as a second gate.')
param modelCapacity int = 1

@description('Azure content filtering policy. Microsoft.DefaultV2 is the safe default.')
param contentFilterPolicyName string = 'Microsoft.DefaultV2'

@description('Resource tags used for cost attribution.')
param tags object = {
  project: 'AIPOL'
  component: 'policy-news'
  owner: 'nextain'
  managedBy: 'bicep'
}

var expectedResourceGroupName = 'rg-aipol-dev'
var resourceGroupScopeAccepted = resourceGroup().name == expectedResourceGroupName
var resourceGroupNameValidated = resourceGroupScopeAccepted ? resourceGroup().name : fail('policy-ai.bicep may only target rg-aipol-dev')

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = if (deployFoundry) {
  name: foundryAccountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryAccountName
    disableLocalAuth: disableLocalAuth
    dynamicThrottlingEnabled: false
    publicNetworkAccess: 'Enabled'
    restrictOutboundNetworkAccess: false
  }
  tags: tags
}

var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource inferenceRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployFoundry && !empty(inferencePrincipalId)) {
  name: guid(foundry.id, inferencePrincipalId, cognitiveServicesUserRoleId)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: inferencePrincipalId
    principalType: inferencePrincipalType
  }
}

// Partner/community models may require a Marketplace subscription.  This
// resource remains disabled until an operator records model name, version,
// format, SKU, regional availability, quota, and commercial terms.
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-04-01-preview' = if (deployFoundry && deployModel) {
  parent: foundry
  name: modelDeploymentName
  sku: {
    name: modelSkuName
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: modelPublisherFormat
      name: modelName
      version: modelVersion
    }
    raiPolicyName: contentFilterPolicyName
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

output infrastructureEnabled bool = deployFoundry
output modelEnabled bool = deployFoundry && deployModel
output foundryRegion string = location
output foundryEndpoint string = deployFoundry ? 'https://${foundryAccountName}.services.ai.azure.com' : ''
output foundryDeployment string = deployFoundry && deployModel ? modelDeploymentName : ''
output requiredRuntimeKillSwitch string = 'POLICY_NEWS_ENABLED=true'
output requiredAuthMode string = disableLocalAuth ? 'AZURE_AI_FOUNDRY_AUTH_MODE=managed_identity' : 'AZURE_AI_FOUNDRY_AUTH_MODE=api_key'
output inferenceRoleConfigured bool = deployFoundry && !empty(inferencePrincipalId)
output expectedResourceGroup string = expectedResourceGroupName
output resourceGroupScopeAccepted bool = resourceGroupNameValidated == expectedResourceGroupName
