"""
===================================================================================
 MOCK DATABASE — Subscription Model & In-Memory Store
===================================================================================

 CONCEITO CRÍTICO:
 A Microsoft NÃO guarda a URL final do cliente em nenhum lugar.
 O botão "Acessar Aplicativo" no Azure Portal sempre redireciona para a mesma
 Landing Page URL que você configurou no Partner Center. Essa URL é FIXA e IGUAL
 para TODOS os clientes.

 Então quem decide "para onde enviar cada cliente" é ESTE código.
 Este dicionário (subscriptions_db) é o "cérebro" que mapeia cada subscription
 para a URL real do ambiente provisionado pelo nosso pipeline de CI/CD.

 Em produção, isso seria um banco de dados (Cosmos DB, PostgreSQL, etc.).
 Aqui usamos um dict em memória para fins de demonstração.
===================================================================================
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Modelo de dados de uma Subscription SaaS
# ---------------------------------------------------------------------------
@dataclass
class SubscriptionData:
    """
    Representa uma assinatura SaaS comprada no Azure Marketplace.

    Campos retornados pela API de Fulfillment v2 (POST /resolve):
    - subscription_id: GUID único da assinatura atribuído pela Microsoft
    - offer_id: ID da oferta no Partner Center (ex: 'enterprise-orchestrator')
    - plan_id: Plano escolhido pelo cliente (ex: 'professional', 'enterprise')
    - purchaser_email: Email do comprador (vem do Azure AD do cliente)
    - purchaser_tenant_id: Tenant ID do Azure AD do comprador

    Campos controlados pelo PUBLISHER (nós):
    - status: Estado atual do provisionamento
    - permanent_url: URL final do ambiente do cliente (preenchida pelo pipeline CI/CD)
    """
    subscription_id: str
    offer_id: str
    plan_id: str
    purchaser_email: str
    purchaser_tenant_id: str
    status: str = "PendingFulfillmentStart"
    permanent_url: Optional[str] = None


# ---------------------------------------------------------------------------
# MOCK DATABASE — Armazena todas as subscriptions
# ---------------------------------------------------------------------------
# Em produção: Azure Cosmos DB, PostgreSQL, SQL Server, etc.
# Aqui: dicionário Python { subscription_id -> SubscriptionData }
subscriptions_db: dict[str, SubscriptionData] = {}


# ---------------------------------------------------------------------------
# MOCK TOKEN DATABASE — Simula o que a Microsoft faz internamente
# ---------------------------------------------------------------------------
# Quando o cliente compra no Marketplace, a Microsoft gera um TOKEN OPACO
# e redireciona o cliente para: https://sua-landing-page.com/?token=abc123
#
# Esse token sozinho NÃO contém informação nenhuma. Você precisa chamar
# POST /resolve para "trocar" o token pelos dados reais da compra.
#
# Aqui pré-populamos 2 tokens de teste para facilitar a demonstração.
# Em produção, os tokens são gerados dinamicamente pela Microsoft.
# ---------------------------------------------------------------------------
tokens_db: dict[str, SubscriptionData] = {
    "mock-token-contoso": SubscriptionData(
        subscription_id="sub-contoso-001",
        offer_id="enterprise-orchestrator",
        plan_id="professional",
        purchaser_email="joao@contoso.com",
        purchaser_tenant_id="tenant-contoso-aad-id",
        status="PendingFulfillmentStart",
        permanent_url=None,
    ),
    "mock-token-fabrikam": SubscriptionData(
        subscription_id="sub-fabrikam-002",
        offer_id="enterprise-orchestrator",
        plan_id="enterprise",
        purchaser_email="maria@fabrikam.com",
        purchaser_tenant_id="tenant-fabrikam-aad-id",
        status="PendingFulfillmentStart",
        permanent_url=None,
    ),
}
