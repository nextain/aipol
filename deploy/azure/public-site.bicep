@description('Deployment environment. The resource group is selected by the az deployment group command.')
@allowed([
  'dev'
  'prod'
])
param environment string = 'prod'

@description('Optional Azure Static Web Apps resource-name override. Empty uses swa-aipol-{environment}.')
param name string = ''

@description('Static Web Apps supported Azure region nearest to Korea')
param location string = 'eastasia'

@description('Intended temporary custom host. This template records intent only and does not bind DNS.')
param currentHostIntent string = ''

var expectedResourceGroupName = 'rg-aipol-${environment}'
var resourceGroupScopeAccepted = resourceGroup().name == expectedResourceGroupName
var resourceGroupNameValidated = resourceGroupScopeAccepted ? resourceGroup().name : fail('public-site.bicep resource group must exactly match rg-aipol-{environment}')
var resourceName = empty(name) ? 'swa-aipol-${environment}' : name
var effectiveCurrentHostIntent = empty(currentHostIntent)
  ? (environment == 'prod' ? 'aipol.kaps.or.kr' : 'not-assigned')
  : currentHostIntent

resource publicSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: resourceName
  location: location
  tags: {
    project: 'AIPOL'
    owner: 'nextain'
    workload: 'public-site'
    environment: environment
    searchIndexing: 'disabled'
    currentHostIntent: effectiveCurrentHostIntent
    futureOfficialHost: 'aipol.kaps.or.kr'
  }
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    allowConfigFileUpdates: true
    enterpriseGradeCdnStatus: 'Disabled'
  }
}

output resourceName string = publicSite.name
output resourceId string = publicSite.id
output defaultHostname string = publicSite.properties.defaultHostname
output deploymentEnvironment string = environment
output currentCustomHostIntent string = effectiveCurrentHostIntent
output futureOfficialHostIntent string = 'aipol.kaps.or.kr'
output expectedResourceGroup string = expectedResourceGroupName
output resourceGroupScopeAccepted bool = resourceGroupNameValidated == expectedResourceGroupName
