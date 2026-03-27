"""
===================================================================================
 MOCK — Azure Marketplace SaaS Fulfillment API v2
===================================================================================

 Em produção, estas funções fariam chamadas HTTP reais para:
   https://marketplaceapi.microsoft.com/api/saas/subscriptions

 A autenticação usa um token Azure AD (client_credentials flow) com:
   - Resource: 20e940b3-4c77-4b0b-9a53-9e16a1b010a7 (Marketplace API)

 Documentação oficial:
   https://learn.microsoft.com/azure/marketplace/partner-center-portal/pc-saas-fulfillment-subscription-api

 Aqui simulamos tudo localmente com dicionários em memória.
===================================================================================
"""

from typing import Optional
from app.models.subscription import (
    SubscriptionData,
    subscriptions_db,
    tokens_db,
)


def mock_resolve(token: str) -> Optional[SubscriptionData]:
    """
    Simula: POST /api/saas/subscriptions/resolve?api-version=2018-08-31
    Header obrigatório: x-ms-marketplace-token: <token>

    O QUE FAZ EM PRODUÇÃO:
    - Recebe o token opaco que a Microsoft coloca na URL da Landing Page
    - Retorna os dados completos da compra: subscriptionId, offerId, planId,
      purchaser (email, tenantId, objectId), beneficiary, etc.
    - Esse token é DE USO ÚNICO e expira em 24 horas

    ANALOGIA:
    É como receber um ticket de bagagem no aeroporto. O ticket (token)
    sozinho não é a bagagem — você precisa apresentar no balcão (Resolve)
    pra receber a bagagem real (dados da compra).

    AQUI NO MOCK:
    - Buscamos o token no tokens_db (dicionário pré-populado)
    - Se encontrar, retornamos os dados da subscription
    - Se não encontrar, retornamos None (token inválido/expirado)
    """
    subscription = tokens_db.get(token)

    if subscription is None:
        return None

    # Em produção, após o resolve, você salva os dados no seu banco.
    # Aqui copiamos para o subscriptions_db se ainda não existir.
    if subscription.subscription_id not in subscriptions_db:
        subscriptions_db[subscription.subscription_id] = subscription

    return subscription


def mock_activate(subscription_id: str, plan_id: str) -> bool:
    """
    Simula: POST /api/saas/subscriptions/{subscriptionId}/activate?api-version=2018-08-31
    Body: { "planId": "<planId>" }

    O QUE FAZ EM PRODUÇÃO:
    - Diz à Microsoft: "Eu aceito essa compra e vou provisionar o ambiente"
    - A Microsoft muda o estado da subscription para 'Subscribed' do lado dela
    - A partir desse momento, a cobrança do cliente começa

    IMPORTANTE — ORDEM DE OPERAÇÕES:
    A imagem que discutimos mostra dois cenários:
    1. Manual: Resolve → Provisiona manualmente → Activate (humano no loop)
    2. Automático: Resolve → Activate → Provisiona em background (pipeline faz tudo)

    Nesta implementação, usamos o cenário AUTOMÁTICO:
    - Chamamos Activate imediatamente (confirma a compra)
    - Mudamos o status interno para 'Deploying'
    - O pipeline de CI/CD faz o provisionamento e avisa via webhook quando terminar

    AQUI NO MOCK:
    - Simplesmente retornamos True (sucesso)
    - Em produção, verificaríamos o HTTP status 200 da resposta
    """
    subscription = subscriptions_db.get(subscription_id)
    if subscription is None:
        return False

    # Em produção: HTTP POST para a API do Marketplace
    # Aqui: apenas registramos que a ativação foi feita
    return True
