/*
  Azure Function App — Webhook chamado pelo pipeline de CI/CD.

  HTTP Trigger: POST /api/deploy-finished
  Protegido por Function Key (auth_level = FUNCTION).

  Quando o pipeline termina de provisionar o ambiente do cliente,
  chama esta Function para atualizar o Cosmos DB com a URL final.
*/
param functionAppName string
param storageAccountName string
param location string
param landingPageUrl string

// Storage Account (obrigatório para Azure Functions)
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
}

// App Service Plan (Consumption / Serverless)
resource hostingPlan 'Microsoft.Web/serverfarms@2023-01-01' = {
  name: '${functionAppName}-plan'
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    reserved: true // Linux
  }
}

// Function App
resource functionApp 'Microsoft.Web/sites@2023-01-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: hostingPlan.id
    siteConfig: {
      pythonVersion: '3.12'
      linuxFxVersion: 'PYTHON|3.12'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount.name};AccountKey=${storageAccount.listKeys().keys[0].value};EndpointSuffix=core.windows.net' }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'LANDING_PAGE_URL', value: landingPageUrl }
      ]
    }
    httpsOnly: true
  }
}

output functionAppUrl string = 'https://${functionApp.properties.defaultHostName}'
output functionAppName string = functionApp.name
