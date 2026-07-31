targetScope = 'subscription'

param assignableScope string

resource role 'Microsoft.Authorization/roleDefinitions@2022-05-01-preview' = {
  name: guid(subscription().id, 'aipol-policy-news-blob-no-delete')
  properties: {
    roleName: 'AIPOL Policy News Blob Writer (No Delete)'
    description: 'Read and write AIPOL policy-news blobs without blob or container deletion.'
    type: 'CustomRole'
    permissions: [{
      actions: ['Microsoft.Storage/storageAccounts/blobServices/containers/read']
      notActions: []
      dataActions: [
        'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'
        'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/write'
        'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/add/action'
      ]
      notDataActions: []
    }]
    assignableScopes: [assignableScope]
  }
}

output roleDefinitionId string = role.id
