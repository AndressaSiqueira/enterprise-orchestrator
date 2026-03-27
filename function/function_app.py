"""
===================================================================================
 AZURE FUNCTION — Webhook: Deploy Finished
===================================================================================

 Esta Function é chamada pelo pipeline de CI/CD (Azure DevOps) quando o
 provisionamento do ambiente do cliente termina com sucesso.

 FLUXO:
 1. Pipeline executa IaC (Bicep/Terraform) → cria RG + VM + recursos
 2. Pipeline pega o IP/URL do ambiente criado
 3. Pipeline chama esta Function com: { subscription_id, permanent_url }
 4. Function repassa para o Container App (Landing Page) 
 5. Landing Page atualiza status → "Subscribed" e grava permanent_url
 6. Próxima vez que o cliente acessa a Landing Page → redirect para a URL

 POR QUE UMA AZURE FUNCTION SEPARADA?
 - O Container App (Landing Page) é público — acessível pelo cliente
 - O webhook precisa de autenticação — só o pipeline pode chamar
 - A Function Key garante que somente o pipeline autorizado notifica
 - Separar permite aplicar políticas de rede distintas
===================================================================================
"""

import json
import logging
import os
import urllib.request
import azure.functions as func

app = func.FunctionApp()

# URL da Landing Page (Container App)
LANDING_PAGE_URL = os.environ.get("LANDING_PAGE_URL", "")


@app.function_name(name="DeployFinished")
@app.route(route="deploy-finished", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def deploy_finished(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP Trigger — Recebe notificação do pipeline de CI/CD.

    Body esperado:
    {
        "subscription_id": "sub-contoso-001",
        "permanent_url": "http://20.123.45.67:8080"
    }
    """
    logging.info("Webhook deploy-finished recebido.")

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "Body JSON inválido."}),
            status_code=400,
            mimetype="application/json",
        )

    subscription_id = body.get("subscription_id")
    permanent_url = body.get("permanent_url")

    if not subscription_id or not permanent_url:
        return func.HttpResponse(
            json.dumps({"error": "Campos obrigatórios: subscription_id, permanent_url"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        # Repassa para o webhook do Container App (Landing Page)
        target_url = f"{LANDING_PAGE_URL}/webhook/deploy-finished"
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            target_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))

        logging.info(f"Subscription {subscription_id} atualizada. URL: {permanent_url}")

        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logging.error(f"Erro ao repassar para Landing Page: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": f"Falha ao notificar Landing Page: {str(e)}"}),
            status_code=502,
            mimetype="application/json",
        )
