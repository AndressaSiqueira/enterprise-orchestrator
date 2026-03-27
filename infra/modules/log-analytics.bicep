// Log Analytics Workspace (necessário para Container Apps Environment)
param name string
param location string

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: name
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

output customerId string = logAnalytics.properties.customerId
output sharedKey string = logAnalytics.listKeys().primarySharedKey
