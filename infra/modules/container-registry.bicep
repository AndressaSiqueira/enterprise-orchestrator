/*
  Azure Container Registry — armazena a imagem Docker da Landing Page.
  O Container App puxa a imagem daqui.
*/
param name string
param location string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true // Necessário para Container App puxar imagem
  }
}

output loginServer string = acr.properties.loginServer
output name string = acr.name
output adminUsername string = acr.listCredentials().username
output adminPassword string = acr.listCredentials().passwords[0].value
