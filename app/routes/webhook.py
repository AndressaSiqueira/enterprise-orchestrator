"""
===================================================================================
 WEBHOOK — POST /webhook/deploy-finished
 Endpoint chamado pelo Pipeline de CI/CD
===================================================================================

 CONTEXTO:
 Quando o cliente compra no Marketplace, a Landing Page chama Resolve + Activate
 e muda o status para "Deploying". Mas quem REALMENTE cria o ambiente do cliente
 é o nosso pipeline de CI/CD (Azure DevOps, GitHub Actions, etc.).

 O pipeline:
 1. Recebe um trigger (webhook, queue message, etc.)
 2. Executa os steps de infraestrutura (Terraform, Bicep, ARM, etc.)
 3. Cria o ambiente isolado do cliente (App Service, AKS, etc.)
 4. Gera a URL final do ambiente (ex: https://contoso.saas.com)
 5. CHAMA ESTE ENDPOINT para nos avisar que terminou e entregar a URL

 A PARTIR DESSE MOMENTO:
 - O status muda de "Deploying" para "Subscribed"
 - A permanent_url é salva no nosso banco
 - Da próxima vez que o cliente clicar em "Acessar Aplicativo" no Azure Portal,
   a rota GET / vai encontrar essa URL e fazer um Redirect 302 para ela

 POR QUE ISSO É NECESSÁRIO:
 A Microsoft NÃO tem um campo "URL final do cliente" na API de Fulfillment.
 O PATCH /subscriptions/{id} só permite mudar planId ou quantity.
 Então a URL final é 100% responsabilidade nossa — este webhook é quem
 "conecta" a subscription à URL real do ambiente provisionado.
===================================================================================
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.database import get_subscription, update_subscription_status

router = APIRouter(prefix="/webhook", tags=["Webhook"])


class DeployFinishedPayload(BaseModel):
    """
    Payload enviado pelo pipeline de CI/CD quando o deploy termina.

    Em produção, este endpoint teria autenticação (API key, Azure AD, etc.)
    para garantir que apenas o pipeline autorizado pode chamá-lo.
    """
    subscription_id: str
    permanent_url: str


@router.post("/deploy-finished")
async def deploy_finished(payload: DeployFinishedPayload):
    """
    Recebe a notificação do pipeline de CI/CD de que o ambiente do cliente
    foi provisionado com sucesso.

    Exemplo de chamada (curl):
    curl -X POST http://localhost:8000/webhook/deploy-finished \
      -H "Content-Type: application/json" \
      -d '{"subscription_id":"sub-contoso-001","permanent_url":"https://www.google.com/search?q=cliente1.saas.com"}'

    Exemplo de chamada (PowerShell):
    Invoke-RestMethod -Uri http://localhost:8000/webhook/deploy-finished `
      -Method POST -ContentType "application/json" `
      -Body '{"subscription_id":"sub-contoso-001","permanent_url":"https://www.google.com/search?q=cliente1.saas.com"}'

    O que acontece:
    1. Valida que a subscription existe no nosso banco
    2. Atualiza o status de "Deploying" para "Subscribed"
    3. Salva a permanent_url — a URL real do ambiente do cliente
    4. A partir de agora, GET /?user=email faz redirect para essa URL
    """
    subscription = await get_subscription(payload.subscription_id)

    if subscription is None:
        raise HTTPException(
            status_code=404,
            detail=f"Subscription '{payload.subscription_id}' não encontrada. "
                   "Verifique se o token já foi resolvido via Landing Page.",
        )

    # Atualizar o status para "Subscribed" e salvar a URL final
    # Esta é a URL que o pipeline de CI/CD gerou
    # Ex: https://contoso.saas.com, https://app.plataforma.com/org/contoso
    await update_subscription_status(
        payload.subscription_id,
        status="Subscribed",
        permanent_url=payload.permanent_url,
    )

    return {
        "message": "Deploy registrado com sucesso.",
        "subscription_id": subscription.subscription_id,
        "status": "Subscribed",
        "permanent_url": payload.permanent_url,
        "next_step": (
            f"Agora, quando o cliente ({subscription.purchaser_email}) clicar em "
            "'Acessar Aplicativo' no Azure Portal, será redirecionado para: "
            f"{payload.permanent_url}"
        ),
    }
