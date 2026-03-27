"""
===================================================================================
 DATABASE SERVICE — Abstração sobre Cosmos DB e Mock (in-memory)
===================================================================================

 Este módulo fornece uma interface única para operações de banco de dados.
 - Em DEV LOCAL (USE_COSMOS=false): usa dicionário Python em memória
 - Em PRODUÇÃO (USE_COSMOS=true): usa Azure Cosmos DB for NoSQL

 A Landing Page e o Webhook usam as mesmas funções, sem saber qual
 backend está por trás. Isso permite desenvolver 100% local e deployar
 no Azure sem mudar nenhuma linha de código nas rotas.
===================================================================================
"""

from typing import Optional
from app.models.subscription import SubscriptionData, subscriptions_db, tokens_db
from app.config import USE_COSMOS, COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE, COSMOS_CONTAINER

# ---------------------------------------------------------------------------
# Cosmos DB client (inicializado sob demanda, apenas se USE_COSMOS=true)
# ---------------------------------------------------------------------------
_cosmos_container = None


def _get_cosmos_container():
    """Inicializa o client do Cosmos DB apenas uma vez (singleton)."""
    global _cosmos_container
    if _cosmos_container is None:
        from azure.cosmos import CosmosClient
        client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
        database = client.get_database_client(COSMOS_DATABASE)
        _cosmos_container = database.get_container_client(COSMOS_CONTAINER)
    return _cosmos_container


# ---------------------------------------------------------------------------
# OPERAÇÕES DE BANCO DE DADOS
# ---------------------------------------------------------------------------

async def get_subscription(subscription_id: str) -> Optional[SubscriptionData]:
    """Busca uma subscription pelo ID."""
    if USE_COSMOS:
        container = _get_cosmos_container()
        try:
            item = container.read_item(item=subscription_id, partition_key=subscription_id)
            return SubscriptionData(**item)
        except Exception:
            return None
    else:
        return subscriptions_db.get(subscription_id)


async def get_subscription_by_email(email: str) -> Optional[SubscriptionData]:
    """Busca uma subscription pelo email do comprador."""
    if USE_COSMOS:
        container = _get_cosmos_container()
        query = "SELECT * FROM c WHERE c.purchaser_email = @email"
        params = [{"name": "@email", "value": email}]
        items = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        if items:
            return SubscriptionData(**items[0])
        return None
    else:
        for sub in subscriptions_db.values():
            if sub.purchaser_email == email:
                return sub
        return None


async def save_subscription(subscription: SubscriptionData) -> None:
    """Salva ou atualiza uma subscription no banco."""
    if USE_COSMOS:
        container = _get_cosmos_container()
        item = {
            "id": subscription.subscription_id,
            "subscription_id": subscription.subscription_id,
            "offer_id": subscription.offer_id,
            "plan_id": subscription.plan_id,
            "purchaser_email": subscription.purchaser_email,
            "purchaser_tenant_id": subscription.purchaser_tenant_id,
            "status": subscription.status,
            "permanent_url": subscription.permanent_url,
        }
        container.upsert_item(item)
    else:
        subscriptions_db[subscription.subscription_id] = subscription


async def update_subscription_status(subscription_id: str, status: str, permanent_url: Optional[str] = None) -> bool:
    """Atualiza o status (e opcionalmente a URL) de uma subscription."""
    if USE_COSMOS:
        container = _get_cosmos_container()
        try:
            item = container.read_item(item=subscription_id, partition_key=subscription_id)
            item["status"] = status
            if permanent_url is not None:
                item["permanent_url"] = permanent_url
            container.upsert_item(item)
            return True
        except Exception:
            return False
    else:
        sub = subscriptions_db.get(subscription_id)
        if sub is None:
            return False
        sub.status = status
        if permanent_url is not None:
            sub.permanent_url = permanent_url
        return True


async def resolve_token(token: str) -> Optional[SubscriptionData]:
    """
    Resolve um token do Marketplace.
    Em produção: chamaria a Fulfillment API v2 POST /resolve.
    No mock: busca no tokens_db.
    """
    subscription = tokens_db.get(token)
    if subscription is None:
        return None

    # Salvar no banco se ainda não existe
    existing = await get_subscription(subscription.subscription_id)
    if existing is None:
        await save_subscription(subscription)

    return subscription
