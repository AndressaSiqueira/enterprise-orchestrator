# Enterprise Orchestrator — SaaS Marketplace Landing Page

Simulador e implementação real da **Landing Page** de uma oferta SaaS publicada no **Azure Marketplace**.

Demonstra o fluxo completo: **Resolve → Activate → Provisioning → Redirect** — incluindo o webhook que o pipeline de CI/CD chama para entregar a URL final do ambiente do cliente.

## Arquitetura

```
┌──────────────────┐     ┌──────────────────────────┐     ┌──────────────────┐
│  Azure Marketplace│     │   Container App (FastAPI)  │     │  Pipeline CI/CD  │
│                  │     │   Landing Page             │     │  (Azure DevOps)  │
│  1. Cliente compra├────►│  GET /?token=xxx           │     │                  │
│                  │     │  → Resolve + Activate      │     │                  │
│  2. "Configurar  │     │  → Status: "Deploying"     ├────►│  3. Provisiona   │
│      Conta"      │     │  → Mostra progresso        │     │     RG + VM      │
│                  │     │                            │     │                  │
│  5. "Acessar     │     │  Cosmos DB ◄───────────────┤◄────┤  4. Webhook      │
│      Aplicativo" ├────►│  → Busca permanent_url     │     │     (Function)   │
│                  │     │  → Redirect 302            │     │                  │
└──────────────────┘     └──────────────────────────┘     └──────────────────┘
```

## Componentes Azure

| Componente | Recurso | Função |
|---|---|---|
| **Landing Page** | Container App | FastAPI — resolve token, mostra status, redireciona |
| **Webhook** | Azure Function | Recebe notificação do pipeline (deploy-finished) |
| **Banco de dados** | Cosmos DB (NoSQL, Serverless) | Armazena subscriptions + permanent_url |
| **Imagem Docker** | Container Registry (ACR) | Armazena imagem da Landing Page |
| **Pipeline de deploy** | Azure DevOps | Provisiona RG + VM do cliente |
| **Infra como código** | Bicep | Templates para Container App, Function, Cosmos, ACR |

## Estrutura do Projeto

```
├── app/                          # Landing Page (Container App)
│   ├── main.py                   # Entry point FastAPI
│   ├── config.py                 # Variáveis de ambiente
│   ├── routes/
│   │   ├── landing.py            # GET / — Resolve, Provisioning, Redirect
│   │   └── webhook.py            # POST /webhook/deploy-finished (dev local)
│   ├── services/
│   │   ├── fulfillment.py        # Mock da Fulfillment API v2
│   │   └── database.py           # Abstração Cosmos DB / in-memory
│   ├── models/
│   │   └── subscription.py       # Modelo de dados + mock
│   ├── templates/                # Jinja2 HTML templates
│   └── static/                   # CSS
├── function/                     # Azure Function (webhook)
│   ├── function_app.py
│   ├── requirements.txt
│   └── host.json
├── infra/                        # Bicep IaC
│   ├── main.bicep
│   └── modules/
│       ├── container-app.bicep
│       ├── container-registry.bicep
│       ├── cosmos-db.bicep
│       ├── function.bicep
│       └── log-analytics.bicep
├── pipelines/                    # Azure DevOps
│   ├── azure-pipelines.yml       # Deploy da Landing Page + Function
│   └── provision-customer.yml    # Provisiona RG + VM do cliente
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Desenvolvimento Local (Mock)

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Iniciar o servidor (usa dict em memória, sem Cosmos)
uvicorn app.main:app --reload

# 3. Abrir no navegador
# http://localhost:8000
```

### Testar o Fluxo Completo Local

**Passo 1** — Simular a compra:
```
http://localhost:8000/?token=mock-token-contoso
```

**Passo 2** — Simular pipeline finalizando:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/webhook/deploy-finished `
  -Method POST -ContentType "application/json" `
  -Body '{"subscription_id":"sub-contoso-001","permanent_url":"http://20.123.45.67:8080"}'
```

**Passo 3** — Acessar como cliente:
```
http://localhost:8000/?user=joao@contoso.com
→ Redirect 302 para http://20.123.45.67:8080
```

### Tokens de Teste

| Token | Cliente | Plano | Email |
|-------|---------|-------|-------|
| `mock-token-contoso` | Contoso | Professional | joao@contoso.com |
| `mock-token-fabrikam` | Fabrikam | Enterprise | maria@fabrikam.com |

---

## Deploy no Azure

### Pré-requisitos

1. **Azure CLI** instalada e autenticada
2. **Azure DevOps** com Service Connection configurada
3. **Variable Group** `marketplace-vars` com:
   - `AZURE_SUBSCRIPTION_ID`
   - `RESOURCE_GROUP_NAME` (ex: `rg-marketplace-landing`)
   - `APP_NAME` (ex: `saas-landing`)
   - `LOCATION` (ex: `eastus2`)

### Deploy via Azure DevOps

1. Importe os pipelines no Azure DevOps:
   - `pipelines/azure-pipelines.yml` — Deploy da infra + Landing Page + Function
   - `pipelines/provision-customer.yml` — Provisiona ambiente de cada cliente

2. Execute `azure-pipelines.yml` primeiro (cria toda a infra)

3. Para cada cliente novo, execute `provision-customer.yml` com os parâmetros

### Deploy manual (CLI)

```bash
# 1. Criar Resource Group
az group create --name rg-marketplace-landing --location eastus2

# 2. Deploy Bicep
az deployment group create \
  --resource-group rg-marketplace-landing \
  --template-file infra/main.bicep \
  --parameters appName=saas-landing

# 3. Build e push da imagem Docker
ACR_NAME=$(az acr list --resource-group rg-marketplace-landing --query "[0].name" -o tsv)
az acr build --registry $ACR_NAME --image landing-page:latest .

# 4. Deploy da Azure Function
cd function
func azure functionapp publish <function-app-name>
```

---

## Conceito Crítico

> **A Microsoft NÃO guarda a URL final de cada cliente.**
>
> O botão "Acessar Aplicativo" no Azure Portal sempre redireciona para a **mesma Landing Page URL**
> configurada no Partner Center. É **esta aplicação** (o "cérebro") que sabe para onde redirecionar
> cada cliente, baseado no que o pipeline de CI/CD informou via webhook.
>
> A URL final fica no **Cosmos DB**, colocada lá pelo **webhook da Azure Function**,
> que foi chamado pelo **pipeline do Azure DevOps**.

## Quando tiver acesso ao Partner Center

Troque **apenas** o arquivo `app/services/fulfillment.py` para usar a API real:
- `mock_resolve()` → `POST https://marketplaceapi.microsoft.com/api/saas/subscriptions/resolve`
- `mock_activate()` → `POST https://marketplaceapi.microsoft.com/api/saas/subscriptions/{id}/activate`

Todo o resto (Container App, Function, Cosmos, Pipeline, templates) **não muda nada**.

## Documentação Oficial

- [SaaS Fulfillment API v2](https://learn.microsoft.com/azure/marketplace/partner-center-portal/pc-saas-fulfillment-subscription-api)
- [Landing Page para ofertas SaaS](https://learn.microsoft.com/azure/marketplace/azure-ad-transactable-saas-landing-page)
- [Acelerador SaaS (GitHub)](https://github.com/Azure/Commercial-Marketplace-SaaS-Accelerator)
- [Ciclo de vida da oferta SaaS](https://learn.microsoft.com/azure/marketplace/partner-center-portal/pc-saas-fulfillment-life-cycle)
