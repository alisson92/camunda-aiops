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

from config import AGENT_PUBLIC_URL, ALERTMANAGER_URL, setup_logging
from metrics import (
    ALERTS_FILTERED,
    ALERTS_PROCESSED,
    ANALYSIS_DURATION,
    TEAMS_NOTIFICATIONS,
    WEBHOOKS_RECEIVED,
)
from knowledge_base import KnowledgeBase
from reactive_agent import run_agent
from runbook_generator import generate_runbook, render_runbook_html
from teams_notifier import send_alert_to_teams

# Armazena runbooks gerados em memória: alert_id → (alert_name, runbook_markdown)
_runbooks: dict[str, tuple[str, str]] = {}

setup_logging()

# Base de conhecimento — carregada uma vez na inicialização do processo
_kb = KnowledgeBase()
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

        context_docs = _kb.search(alert_name, k=2)
        if context_docs:
            logger.info("KB: %d doc(s) relevante(s) para %s", len(context_docs), alert_name)

        with ANALYSIS_DURATION.time():
            analysis = run_agent(
                alert_name=alert_name,
                alert_labels=labels,
                alert_annotations=annotations,
                status=status,
                context_docs=context_docs,
            )

        severity = labels.get("severity", "unknown")
        ALERTS_PROCESSED.labels(alertname=alert_name, severity=severity).inc()
        logger.info("Análise concluída para %s:\n%s", alert_name, analysis)

        runbook_id = ""
        if status != "resolved":
            runbook_id, runbook_md = generate_runbook(
                alert_name=alert_name,
                alert_labels=labels,
                analysis=analysis,
                starts_at=starts_at,
            )
            _runbooks[runbook_id] = (alert_name, runbook_md)
            logger.info("Runbook armazenado: id=%s", runbook_id)
            _kb.add_document(
                doc_id=runbook_id,
                title=f"Runbook: {alert_name}",
                content=runbook_md,
                alert_name=alert_name,
            )

        generated_runbook_url = (
            f"{AGENT_PUBLIC_URL}/runbook/{runbook_id}" if runbook_id else ""
        )

        notified = send_alert_to_teams(
            alert_name=alert_name,
            alert_labels=labels,
            alert_annotations=annotations,
            status=status,
            analysis=analysis,
            starts_at=starts_at,
            ends_at=ends_at,
            runbook_url=generated_runbook_url,
        )
        TEAMS_NOTIFICATIONS.labels(success=str(notified).lower()).inc()

        analyses.append({
            "alertname": alert_name,
            "status": status,
            "analysis": analysis,
            "runbook_id": runbook_id,
        })

    return JSONResponse({
        "message": f"{len(analyses)} alerta(s) analisado(s)",
        "analyses": analyses,
    })


@app.get("/runbook/{alert_id}", response_class=HTMLResponse)
async def get_runbook(alert_id: str):
    """Serve o runbook gerado para um alerta específico (gerado pelo agente após análise)."""
    if alert_id not in _runbooks:
        raise HTTPException(status_code=404, detail=f"Runbook '{alert_id}' não encontrado.")
    alert_name, runbook_md = _runbooks[alert_id]
    return HTMLResponse(render_runbook_html(alert_name, runbook_md))


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
