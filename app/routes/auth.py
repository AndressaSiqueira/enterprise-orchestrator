"""
===================================================================================
 ROTAS DE AUTENTICAÇÃO — Microsoft Entra ID (Azure AD) SSO
===================================================================================

 O Azure Marketplace exige que a Landing Page autentique o usuário via Entra ID.
 Isso identifica QUEM está acessando (tenantId + email) para:

 1. No cenário "Configure your account":
    Saber quem comprou e associar a subscription ao email.

 2. No cenário "Open SaaS Account":
    Identificar o cliente e redirecioná-lo para sua URL final.

 FLUXO:
 ------
 GET /auth/login          → Redireciona para Microsoft Login
 GET /auth/callback       → Recebe o code, troca por token, salva na sessão
 GET /auth/logout         → Limpa sessão e redireciona para home

 REFERÊNCIA:
 https://learn.microsoft.com/azure/marketplace/azure-ad-transactable-saas-landing-page
===================================================================================
"""

import msal
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.config import (
    ENTRA_CLIENT_ID,
    ENTRA_CLIENT_SECRET,
    ENTRA_AUTHORITY,
    ENTRA_SCOPES,
    APP_BASE_URL,
    ENTRA_REDIRECT_PATH,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_msal_app():
    """Cria a instância MSAL ConfidentialClientApplication."""
    return msal.ConfidentialClientApplication(
        client_id=ENTRA_CLIENT_ID,
        client_credential=ENTRA_CLIENT_SECRET,
        authority=ENTRA_AUTHORITY,
    )


@router.get("/login")
async def login(request: Request):
    """
    Inicia o fluxo Authorization Code do Entra ID.
    Redireciona o navegador para https://login.microsoftonline.com/.../authorize
    """
    msal_app = _build_msal_app()

    # Preservar query params originais (ex: ?token=xxx) no state
    # para que após o login voltemos para o fluxo correto
    original_query = str(request.query_params)

    auth_url = msal_app.get_authorization_request_url(
        scopes=ENTRA_SCOPES,
        redirect_uri=f"{APP_BASE_URL}{ENTRA_REDIRECT_PATH}",
        state=original_query,  # preserva token= ou outros params
    )

    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def callback(request: Request):
    """
    Callback do Entra ID após o login.
    Recebe o authorization code e troca por um token JWT.
    Salva os dados do usuário na sessão.
    """
    code = request.query_params.get("code")
    if not code:
        return RedirectResponse(url="/")

    msal_app = _build_msal_app()

    result = msal_app.acquire_token_by_authorization_code(
        code=code,
        scopes=ENTRA_SCOPES,
        redirect_uri=f"{APP_BASE_URL}{ENTRA_REDIRECT_PATH}",
    )

    if "error" in result:
        # Login falhou — limpar e redirecionar
        request.session.clear()
        return RedirectResponse(url="/")

    # Salvar dados do usuário na sessão
    id_token_claims = result.get("id_token_claims", {})
    request.session["user"] = {
        "name": id_token_claims.get("name", ""),
        "email": id_token_claims.get("preferred_username", ""),
        "oid": id_token_claims.get("oid", ""),          # Object ID no Entra
        "tid": id_token_claims.get("tid", ""),           # Tenant ID
    }

    # Restaurar o fluxo original (ex: se tinha ?token=xxx antes do login)
    state = request.query_params.get("state", "")
    if state and "token=" in state:
        return RedirectResponse(url=f"/?{state}")

    return RedirectResponse(url="/")


@router.get("/logout")
async def logout(request: Request):
    """Limpa a sessão e redireciona para home."""
    request.session.clear()
    return RedirectResponse(url="/")


def get_user(request: Request) -> dict | None:
    """
    Helper para obter o usuário autenticado da sessão.
    Retorna None se não está logado.

    Usado pelas rotas da landing page para verificar autenticação.
    """
    return request.session.get("user")
