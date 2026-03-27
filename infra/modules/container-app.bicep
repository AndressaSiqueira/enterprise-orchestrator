/*
  Azure Container App — a Landing Page (FastAPI).

  Roda a imagem Docker do ACR em um Container Apps Environment.
  Recebe variáveis de ambiente para Cosmos DB.
  Ingress externo na porta 8000 (acessível pela internet).
*/
param containerAppEnvName string
param containerAppName string
param location string
param acrLoginServer string
param containerImageTag string
param cosmosEndpoint string
@secure()
param cosmosKey string
param logAnalyticsCustomerId string
@secure()
param logAnalyticsSharedKey string
param acrAdminUsername string
@secure()
param acrAdminPassword string

// Container Apps Environment
resource containerAppEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
  }
}

// Container App
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  properties: {
    managedEnvironmentId: containerAppEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: [
        { name: 'cosmos-key', value: cosmosKey }
        { name: 'acr-password', value: acrAdminPassword }
      ]
      registries: [
        {
          server: acrLoginServer
          username: acrAdminUsername
          passwordSecretRef: 'acr-password'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'landing-page'
          image: '${acrLoginServer}/landing-page:${containerImageTag}'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'USE_COSMOS', value: 'true' }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_KEY', secretRef: 'cosmos-key' }
            { name: 'COSMOS_DATABASE', value: 'marketplace' }
            { name: 'COSMOS_CONTAINER', value: 'saas-subscriptions' }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
        rules: [
          {
            name: 'http-rule'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

output fqdn string = containerApp.properties.configuration.ingress.fqdn
