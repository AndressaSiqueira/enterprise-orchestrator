"""
===================================================================================
 ENTERPRISE ORCHESTRATOR — SaaS Marketplace Landing Page (Simulador)
===================================================================================

 Este aplicativo simula a Landing Page de uma oferta SaaS publicada no
 Azure Marketplace. Ele demonstra o fluxo completo que acontece quando um
 cliente compra sua oferta:

 FLUXO REAL DO AZURE MARKETPLACE:
 ================================

 1. COMPRA:
    - Cliente encontra sua oferta no Azure Marketplace
    - Clica em "Get It Now" → "Subscribe" → escolhe plano → confirma

 2. BOTÃO "CONFIGURE YOUR ACCOUNT" (com token):
    - Microsoft redireciona para: https://sua-landing-page.com/?token=abc123
    - O token é opaco e de uso único (expira em 24h)
    - Sua Landing Page chama POST /resolve para trocar o token por dados reais
    - Sua Landing Page chama POST /activate para confirmar a compra
    - Seu pipeline de CI/CD provisiona o ambiente do cliente

 3. BOTÃO "OPEN SAAS ACCOUNT" (sem token):
    - O cliente clica neste botão no Azure Portal para acessar a plataforma
    - A Microsoft redireciona para a MESMA URL da Landing Page
    - Sua Landing Page identifica o usuário (via Azure AD SSO)
    - Busca a URL final no banco de dados e faz redirect

 PONTO CRÍTICO:
 ==============
 A Microsoft NÃO armazena a URL final do ambiente de cada cliente.
 O botão "Acessar Aplicativo" no Azure Portal SEMPRE leva para a mesma
 Landing Page URL configurada no Partner Center. É ESTA APLICAÇÃO que
 sabe para onde redirecionar cada cliente, baseado no que o pipeline de
 CI/CD informou via webhook.

 Este script é o "CÉREBRO" que faz o redirecionamento inteligente.

 COMO RODAR:
 ===========
 pip install -r requirements.txt
 uvicorn app.main:app --reload

 DOCUMENTAÇÃO OFICIAL:
 =====================
 - SaaS Fulfillment API v2:
   https://learn.microsoft.com/azure/marketplace/partner-center-portal/pc-saas-fulfillment-subscription-api
 - Landing Page:
   https://learn.microsoft.com/azure/marketplace/azure-ad-transactable-saas-landing-page
 - Acelerador SaaS (GitHub):
   https://github.com/Azure/Commercial-Marketplace-SaaS-Accelerator

===================================================================================
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import SESSION_SECRET
from app.routes.landing import router as landing_router
from app.routes.webhook import router as webhook_router
from app.routes.auth import router as auth_router


# ---------------------------------------------------------------------------
# Criar a aplicação FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Enterprise Orchestrator — SaaS Landing Page",
    description=(
        "Landing Page de uma oferta SaaS do Azure Marketplace com Entra ID SSO. "
        "Demonstra o fluxo de Login → Resolve → Activate → Provisioning → Redirect."
    ),
    version="2.0.0",
    docs_url="/docs",  # Swagger UI em http://localhost:8000/docs
)


# ---------------------------------------------------------------------------
# Middleware de sessão (necessário para MSAL / Entra ID SSO)
# ---------------------------------------------------------------------------
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="saas_session",
    max_age=3600,  # 1 hora
    same_site="lax",
    https_only=False,  # True em produção com HTTPS
)


# ---------------------------------------------------------------------------
# Montar arquivos estáticos (CSS)
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="app/static"), name="static")


# ---------------------------------------------------------------------------
# Registrar routers
# ---------------------------------------------------------------------------
# Autenticação: /auth/login, /auth/callback, /auth/logout
app.include_router(auth_router)

# Rota principal: GET / (Landing Page — resolve, provisioning, redirect)
app.include_router(landing_router)

# Webhook: POST /webhook/deploy-finished (chamado pelo pipeline de CI/CD)
app.include_router(webhook_router)
