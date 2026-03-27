/*
  Azure Cosmos DB for NoSQL — banco de dados das subscriptions.

  Partition key: /id (subscription_id)
  Cada documento = 1 subscription SaaS com status e permanent_url.

  A Microsoft NÃO guarda a URL final do cliente. É o Cosmos DB que
  mapeia cada subscription para a URL do ambiente provisionado.
*/
param accountName string
param location string
param databaseName string = 'marketplace'
param containerName string = 'subscriptions'

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: accountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

// Container é criado via CLI após o deploy do Bicep (workaround para
// bug no management proxy do Cosmos DB Serverless com ARM):
//   az cosmosdb sql container create \
//     --account-name <account> --resource-group <rg> \
//     --database-name marketplace --name saas-subscriptions \
//     --partition-key-path "/id"

output endpoint string = cosmosAccount.properties.documentEndpoint
output primaryKey string = cosmosAccount.listKeys().primaryMasterKey
