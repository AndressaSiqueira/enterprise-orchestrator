/*
===================================================================================
 BICEP — Infraestrutura da Landing Page SaaS Marketplace
===================================================================================

 Este template provisiona TODOS os recursos necessários para rodar a
 Landing Page em produção no Azure:

 1. Azure Container Registry (ACR) — para armazenar a imagem Docker
 2. Azure Cosmos DB — banco de dados das subscriptions
 3. Azure Container App — a Landing Page (FastAPI)
 4. Azure Function App — webhook chamado pelo pipeline

 DEPLOY:
 az deployment sub create \
   --location eastus2 \
   --template-file infra/main.bicep \
   --parameters appName=saas-landing

===================================================================================
*/

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// PARÂMETROS
// ---------------------------------------------------------------------------
@description('Nome base para todos os recursos (ex: saas-landing)')
param appName string

@description('Localização dos recursos')
param location string = resourceGroup().location

@description('Tag da imagem Docker no ACR')
param containerImageTag string = 'latest'

// ---------------------------------------------------------------------------
// VARIÁVEIS
// ---------------------------------------------------------------------------
var uniqueSuffix = uniqueString(resourceGroup().id)
var acrName = replace('acr${appName}${uniqueSuffix}', '-', '')
var cosmosAccountName = 'cosmos-${appName}-${uniqueSuffix}'
var containerAppEnvName = 'cae-${appName}'
var containerAppName = 'ca-${appName}'
var functionAppName = 'func-${appName}-${uniqueSuffix}'
var storageAccountName = replace('st${appName}${uniqueSuffix}', '-', '')
var logAnalyticsName = 'log-${appName}'

// ---------------------------------------------------------------------------
// MÓDULOS
// ---------------------------------------------------------------------------

// 1. Log Analytics (necessário para Container Apps Environment)
module logAnalytics 'modules/log-analytics.bicep' = {
  name: 'log-analytics'
  params: {
    name: logAnalyticsName
    location: location
  }
}

// 2. Container Registry (ACR)
module acr 'modules/container-registry.bicep' = {
  name: 'container-registry'
  params: {
    name: acrName
    location: location
  }
}

// 3. Cosmos DB
module cosmos 'modules/cosmos-db.bicep' = {
  name: 'cosmos-db'
  params: {
    accountName: cosmosAccountName
    location: location
    databaseName: 'marketplace'
    containerName: 'saas-subscriptions'
  }
}

// 4. Container App (Landing Page)
module containerApp 'modules/container-app.bicep' = {
  name: 'container-app'
  params: {
    containerAppEnvName: containerAppEnvName
    containerAppName: containerAppName
    location: location
    acrLoginServer: acr.outputs.loginServer
    containerImageTag: containerImageTag
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosKey: cosmos.outputs.primaryKey
    logAnalyticsCustomerId: logAnalytics.outputs.customerId
    logAnalyticsSharedKey: logAnalytics.outputs.sharedKey
    acrAdminUsername: acr.outputs.adminUsername
    acrAdminPassword: acr.outputs.adminPassword
  }
}

// 5. Azure Function (Webhook)
module functionApp 'modules/function.bicep' = {
  name: 'function-app'
  params: {
    functionAppName: functionAppName
    storageAccountName: storageAccountName
    location: location
    landingPageUrl: 'https://${containerApp.outputs.fqdn}'
  }
}

// ---------------------------------------------------------------------------
// OUTPUTS — URLs e informações importantes para o pipeline
// ---------------------------------------------------------------------------
output acrLoginServer string = acr.outputs.loginServer
output containerAppUrl string = containerApp.outputs.fqdn
output functionAppUrl string = functionApp.outputs.functionAppUrl
output cosmosEndpoint string = cosmos.outputs.endpoint
