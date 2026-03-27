"""
===================================================================================
 ROTA PRINCIPAL — GET /
 O "Botão Inteligente" da Landing Page (com Entra ID SSO)
===================================================================================

 CONCEITO FUNDAMENTAL:
 No Azure Marketplace, existem DOIS botões que levam o cliente para a Landing Page:

 1. "Configure your account" (Configurar Conta)
    → Aparece IMEDIATAMENTE após a compra
    → A Microsoft adiciona ?token=xxx na URL
    → Objetivo: identificar quem comprou e iniciar o provisionamento

 2. "Open SaaS Account" (Acessar Aplicativo)
    → Aparece DEPOIS que a subscription está ativa
    → NÃO envia token — o cliente já foi identificado antes
    → Objetivo: acessar o ambiente já provisionado

 AUTENTICAÇÃO:
 Em AMBOS os cenários, o usuário deve estar autenticado via Entra ID SSO.
 Se não estiver logado, redirecionamos para /auth/login (Microsoft Login).
 Após o login, o email do usuário vem do token JWT (preferred_username).

 PONTO CRÍTICO:
 A Microsoft SEMPRE redireciona para a MESMA URL (a Landing Page configurada
 no Partner Center). Ela NÃO guarda a URL final de cada cliente.

 Então é ESTA ROTA que funciona como um "roteador inteligente":
 - Tem token? → É a primeira vez. Resolve, ativa, mostra status de provisionamento.
 - Não tem token? → É acesso posterior. Verifica quem é o usuário via SSO, busca
   a URL final no banco e faz redirect.
===================================================================================
"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from urllib.parse import urlencode

from app.services.fulfillment import mock_resolve, mock_activate
from app.services.database import resolve_token, get_subscription_by_email, save_subscription
from app.routes.auth import get_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def landing_page(
    request: Request,
    token: Optional[str] = Query(None, description="Token opaco enviado pela Microsoft no cenário 'Configure your account'"),
):
    """
    Rota principal da Landing Page.

    Dois cenários possíveis:

    CENÁRIO A — ?token=xxx (Botão "Configure your account")
    O cliente acabou de comprar. A Microsoft redireciona com um token opaco.
    O usuário DEVE estar logado (Entra SSO). Se não, redireciona para login.
    Após login: resolver o token → ativar a subscription → mostrar progresso.

    CENÁRIO B — Sem token (Botão "Open SaaS Account")
    O cliente quer acessar a plataforma. Não tem token.
    O usuário DEVE estar logado (Entra SSO). Se não, redireciona para login.
    Após login: usar email do SSO → buscar a URL final → redirecionar.
    """

    # Obter usuário autenticado da sessão (Entra ID SSO)
    user = get_user(request)
    user_name = user["name"] if user else None

    # =========================================================================
    # CENÁRIO A: Token presente → "Configure your account"
    # =========================================================================
    if token:
        # Se não está logado, redirecionar para Entra ID com o token preservado
        if not user:
            return RedirectResponse(url=f"/auth/login?token={token}")

        # Passo 1: Resolver o token (simula POST /api/saas/subscriptions/resolve)
        subscription = await resolve_token(token)

        if subscription is None:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "user_name": user_name,
                "title": "Token Inválido",
                "message": "O token do Marketplace é inválido ou já expirou. "
                           "Tokens são de uso único e expiram em 24 horas.",
                "suggestion": "Tente acessar novamente pelo portal do Azure ou entre em contato com o suporte.",
            })

        # Passo 2: Se está em PendingFulfillmentStart, ativar e iniciar provisionamento
        if subscription.status == "PendingFulfillmentStart":
            mock_activate(subscription.subscription_id, subscription.plan_id)
            subscription.status = "Deploying"

            # Associar a subscription ao email REAL do Entra ID SSO
            # (o mock tem emails fictícios como joao@contoso.com,
            #  mas o email real do usuário vem do token JWT)
            subscription.purchaser_email = user["email"]
            await save_subscription(subscription)

        # Passo 3: Renderizar a página de acordo com o status atual
        if subscription.status == "Deploying":
            return templates.TemplateResponse("provisioning.html", {
                "request": request,
                "user_name": user_name,
                "subscription_id": subscription.subscription_id,
                "plan_id": subscription.plan_id,
                "offer_id": subscription.offer_id,
                "purchaser_email": subscription.purchaser_email,
            })

        if subscription.status == "Subscribed" and subscription.permanent_url:
            return templates.TemplateResponse("ready.html", {
                "request": request,
                "user_name": user_name,
                "subscription_id": subscription.subscription_id,
                "plan_id": subscription.plan_id,
                "permanent_url": subscription.permanent_url,
                "purchaser_email": subscription.purchaser_email,
            })

        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_name": user_name,
            "title": "Erro no Provisionamento",
            "message": f"Status inesperado: {subscription.status}",
            "suggestion": "Entre em contato com o suporte.",
        })

    # =========================================================================
    # CENÁRIO B: Sem token → "Open SaaS Account"
    # =========================================================================
    if not user:
        return RedirectResponse(url="/auth/login")

    user_email = user["email"]
    user_subscription = await get_subscription_by_email(user_email)

    if user_subscription is None:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "user_name": user_name,
            "title": "Assinatura Não Encontrada",
            "message": f"Nenhuma assinatura encontrada para {user_email}.",
            "suggestion": "Verifique se a compra foi finalizada no Azure Marketplace.",
        })

    if user_subscription.status == "Subscribed" and user_subscription.permanent_url:
        return RedirectResponse(
            url=user_subscription.permanent_url,
            status_code=302,
        )

    if user_subscription.status == "Deploying":
        return templates.TemplateResponse("provisioning.html", {
            "request": request,
            "user_name": user_name,
            "subscription_id": user_subscription.subscription_id,
            "plan_id": user_subscription.plan_id,
            "offer_id": user_subscription.offer_id,
            "purchaser_email": user_subscription.purchaser_email,
        })

    return templates.TemplateResponse("error.html", {
        "request": request,
        "user_name": user_name,
        "title": "Status Inesperado",
        "message": f"Sua assinatura está com status: {user_subscription.status}",
        "suggestion": "Entre em contato com o suporte para mais informações.",
    })
