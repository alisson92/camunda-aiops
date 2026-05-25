"""
Servidor FastAPI que recebe payloads do Alertmanager e aciona o agente reativo.

Uso:
  uvicorn webhook_receiver:app --host 0.0.0.0 --port 5001
  # ou via Makefile:
  make run
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from config import ALERTMANAGER_URL, setup_logging
from metrics import (
    ALERTS_FILTERED,
    ALERTS_PROCESSED,
    ANALYSIS_DURATION,
    TEAMS_NOTIFICATIONS,
    WEBHOOKS_RECEIVED,
)
from reactive_agent import run_agent
from teams_notifier import send_alert_to_teams

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Camunda AIOps Webhook Receiver")


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics_endpoint():
    """Expõe métricas do agente no formato Prometheus text/plain."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/webhook")
async def alertmanager_webhook(request: Request):
    """
    Recebe payload do Alertmanager (formato padrão webhook_configs).
    Aciona o agente para cada alerta firing no payload.
    """
    try:
        payload = await request.json()
    except Exception:
        WEBHOOKS_RECEIVED.labels(status="invalid_json").inc()
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    alerts = payload.get("alerts", [])
    if not alerts:
        WEBHOOKS_RECEIVED.labels(status="empty").inc()
        return JSONResponse({"message": "Nenhum alerta no payload", "processed": 0})

    WEBHOOKS_RECEIVED.labels(status="success").inc()

    analyses = []
    for alert in alerts:
        status      = alert.get("status", "firing")
        labels      = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alert_name  = labels.get("alertname", "unknown")
        starts_at   = alert.get("startsAt", "")
        ends_at     = alert.get("endsAt", "")

        logger.info("Alerta recebido: %s | status: %s | labels: %s", alert_name, status, json.dumps(labels))

        if not any(kw in alert_name for kw in ("Zeebe", "Camunda")):
            logger.debug("Alerta %s ignorado (fora do escopo Camunda)", alert_name)
            ALERTS_FILTERED.inc()
            continue

        with ANALYSIS_DURATION.time():
            analysis = run_agent(
                alert_name=alert_name,
                alert_labels=labels,
                alert_annotations=annotations,
                status=status,
            )

        severity = labels.get("severity", "unknown")
        ALERTS_PROCESSED.labels(alertname=alert_name, severity=severity).inc()
        logger.info("Análise concluída para %s:\n%s", alert_name, analysis)

        notified = send_alert_to_teams(
            alert_name=alert_name,
            alert_labels=labels,
            alert_annotations=annotations,
            status=status,
            analysis=analysis,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        TEAMS_NOTIFICATIONS.labels(success=str(notified).lower()).inc()

        analyses.append({"alertname": alert_name, "status": status, "analysis": analysis})

    return JSONResponse({
        "message": f"{len(analyses)} alerta(s) analisado(s)",
        "analyses": analyses,
    })


@app.get("/silence", response_class=HTMLResponse)
async def create_silence(
    alert: str = Query(..., description="Nome do alerta a silenciar"),
    duration: str = Query("1h", description="Duração: ex. 1h, 2h, 30m"),
):
    """
    Cria um silence no Alertmanager para o alerta informado.
    Acionado via botão do card do Teams.
    """
    unit = duration[-1]
    try:
        value = int(duration[:-1])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Duração inválida: {duration}. Use formato como 1h ou 30m.")

    if unit == "h":
        delta = timedelta(hours=value)
    elif unit == "m":
        delta = timedelta(minutes=value)
    else:
        raise HTTPException(status_code=400, detail=f"Unidade não suportada: {unit}. Use h ou m.")

    now     = datetime.now(timezone.utc)
    ends_at = now + delta

    silence_payload = {
        "matchers": [{"name": "alertname", "value": alert, "isRegex": False}],
        "startsAt":  now.isoformat(),
        "endsAt":    ends_at.isoformat(),
        "createdBy": "aiops-agent",
        "comment":   f"Silence criado via card Teams — duração: {duration}",
    }

    try:
        resp = httpx.post(
            f"{ALERTMANAGER_URL}/api/v2/silences",
            json=silence_payload,
            timeout=10,
        )
        resp.raise_for_status()
        silence_id = resp.json().get("silenceID", "—")
    except httpx.HTTPError as e:
        logger.error("Falha ao criar silence para %s: %s", alert, e)
        raise HTTPException(status_code=502, detail=f"Falha ao criar silence no Alertmanager: {e}")

    ends_local = ends_at.astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
    logger.info("Silence criado: alerta=%s duração=%s id=%s", alert, duration, silence_id)

    return f"""
    <html><body style="font-family:sans-serif;max-width:480px;margin:40px auto;text-align:center">
      <h2>🔕 Silence criado</h2>
      <p><strong>Alerta:</strong> {alert}</p>
      <p><strong>Duração:</strong> {duration} — expira em {ends_local}</p>
      <p><strong>ID:</strong> <code>{silence_id}</code></p>
      <p style="color:#666;font-size:0.9em">Você pode fechar esta aba.</p>
    </body></html>
    """
