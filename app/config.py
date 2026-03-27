"""
===================================================================================
 CONFIGURAÇÃO — Variáveis de Ambiente
===================================================================================

 Em produção (Container App), estas variáveis são injetadas via:
 - Bicep: properties.template.containers[0].env
 - Ou via Azure CLI: az containerapp update --set-env-vars

 Em desenvolvimento local, crie um arquivo .env na raiz:
   USE_COSMOS=false
   ENTRA_CLIENT_ID=<App Registration Client ID>
   ENTRA_CLIENT_SECRET=<App Registration Client Secret>
   ENTRA_TENANT_ID=common
   APP_BASE_URL=http://localhost:8000
   SESSION_SECRET=change-me-in-production
===================================================================================
"""

import os


# ---------------------------------------------------------------------------
# Cosmos DB
# ---------------------------------------------------------------------------
COSMOS_ENDPOINT = os.getenv("COSMOS_ENDPOINT", "")
COSMOS_KEY = os.getenv("COSMOS_KEY", "")
COSMOS_DATABASE = os.getenv("COSMOS_DATABASE", "marketplace")
COSMOS_CONTAINER = os.getenv("COSMOS_CONTAINER", "saas-subscriptions")

# Quando False, usa o dict em memória (mock). Quando True, usa Cosmos DB.
USE_COSMOS = os.getenv("USE_COSMOS", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Microsoft Entra ID (Azure AD) SSO
# ---------------------------------------------------------------------------
ENTRA_CLIENT_ID = os.getenv("ENTRA_CLIENT_ID", "")
ENTRA_CLIENT_SECRET = os.getenv("ENTRA_CLIENT_SECRET", "")
ENTRA_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "common")  # "common" para multi-tenant
ENTRA_AUTHORITY = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}"
ENTRA_SCOPES = ["User.Read"]  # Permissão mínima para obter perfil do usuário

# URL base da aplicação (para montar redirect_uri)
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
ENTRA_REDIRECT_PATH = "/auth/callback"

# Sessão
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-in-production")


# ---------------------------------------------------------------------------
# Webhook Security
# ---------------------------------------------------------------------------
WEBHOOK_API_KEY = os.getenv("WEBHOOK_API_KEY", "dev-api-key-change-in-production")
