"""
Servidor FastAPI que recebe payloads do Alertmanager e aciona o agente reativo.

Uso:
  uvicorn webhook_receiver:app --host 0.0.0.0 --port 5001
  # ou via Makefile:
  make run
"""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta, timezone

import httpx
from config import (
    AGENT_PUBLIC_URL,
    ALERTMANAGER_URL,
    DEDUP_TTL_SECONDS,
    setup_logging,
)
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from knowledge_base import KnowledgeBase
from metrics import (
    ALERTS_DEDUPLICATED,
    ALERTS_FILTERED,
    ALERTS_PROCESSED,
    ANALYSIS_DURATION,
    TEAMS_NOTIFICATIONS,
    WEBHOOKS_RECEIVED,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from reactive_agent import run_agent
from runbook_generator import generate_runbook, render_runbook_html
from teams_notifier import send_alert_to_teams

# Cache de deduplicação: fingerprint → timestamp do último processamento
_dedup_cache: dict[str, datetime] = {}

# Armazena runbooks gerados em memória: alert_id → (alert_name, runbook_markdown)
_runbooks: dict[str, tuple[str, str]] = {}

# Índice por nome de alerta → alert_id mais recente.
# Permite que runbook_url nas PrometheusRules use uma URL estática por alertname
# em vez de um ID dinâmico por ocorrência: GET /runbook/by-alert/{alert_name}
_latest_runbook_by_name: dict[str, str] = {}

setup_logging()

# Base de conhecimento — carregada uma vez na inicialização do processo
_kb = KnowledgeBase()

logger = logging.getLogger(__name__)


def _make_fingerprint(alert: dict) -> str:
    """Retorna o fingerprint do alerta (campo nativo) ou deriva um via hash de labels."""
    fp = alert.get("fingerprint")
    if fp:
        return str(fp)
    labels = alert.get("labels", {})
    key = labels.get("alertname", "unknown") + "|" + "|".join(
        f"{k}={v}" for k, v in sorted(labels.items())
    )
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _is_duplicate(fingerprint: str, status: str) -> bool:
    """Retorna True se o alerta já foi processado dentro do DEDUP_TTL_SECONDS.

    Alertas resolved nunca são deduplicados — o encerramento deve sempre ser
    notificado independente do TTL. Entradas expiradas são removidas a cada chamada
    para manter o cache limitado em memória.
    """
    if status == "resolved":
        return False

    now = datetime.now(UTC)

    expired = [fp for fp, ts in _dedup_cache.items() if (now - ts).total_seconds() > DEDUP_TTL_SECONDS]
    for fp in expired:
        del _dedup_cache[fp]

    if fingerprint in _dedup_cache:
        return True

    _dedup_cache[fingerprint] = now
    return False


def _reload_runbooks_from_kb() -> None:
    """Repovoar stores de runbooks a partir da KB (runbooks persistidos em ciclos anteriores).
    Garante que /runbook/{id} e /runbook/by-alert/{name} funcionem após restart do agente."""
    for doc_id, doc in _kb.get_runbooks().items():
        _runbooks[doc_id] = (doc.alert_name, doc.content)
        if doc.alert_name:
            _latest_runbook_by_name[doc.alert_name] = doc_id


_reload_runbooks_from_kb()

app = FastAPI(title="Camunda AIOps Webhook Receiver")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(UTC).isoformat(),
        "knowledge_base": {"documents": len(_kb)},
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics_endpoint():
    """Expõe métricas do agente no formato Prometheus text/plain."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _process_alert(alert: dict, alert_id: str) -> None:
    """Executa o ciclo completo de análise para um alerta: LLM → runbook → Teams.

    Chamado como BackgroundTask após o webhook retornar 202. O Alertmanager recebe
    a confirmação imediatamente; o processamento acontece em paralelo sem bloquear
    novos webhooks.
    """
    status      = alert.get("status", "firing")
    labels      = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    alert_name  = labels.get("alertname", "unknown")
    starts_at   = alert.get("startsAt", "")
    ends_at     = alert.get("endsAt", "")

    context_docs = _kb.search(alert_name, k=2)
    if context_docs:
        logger.info("[%s] KB: %d doc(s) relevante(s) para %s", alert_id, len(context_docs), alert_name)

    with ANALYSIS_DURATION.time():
        analysis = run_agent(
            alert_name=alert_name,
            alert_labels=labels,
            alert_annotations=annotations,
            status=status,
            context_docs=context_docs,
            alert_id=alert_id,
        )

    severity = labels.get("severity", "unknown")
    ALERTS_PROCESSED.labels(alertname=alert_name, severity=severity).inc()
    logger.info("[%s] Análise concluída para %s:\n%s", alert_id, alert_name, analysis)

    runbook_id = ""
    if status != "resolved":
        runbook_id, runbook_md = generate_runbook(
            alert_name=alert_name,
            alert_labels=labels,
            analysis=analysis,
            starts_at=starts_at,
        )
        _runbooks[runbook_id] = (alert_name, runbook_md)
        _latest_runbook_by_name[alert_name] = runbook_id
        logger.info("[%s] Runbook armazenado: id=%s alertname=%s", alert_id, runbook_id, alert_name)
        _kb.add_document(
            doc_id=runbook_id,
            title=f"Runbook: {alert_name}",
            content=runbook_md,
            alert_name=alert_name,
        )

    generated_runbook_url = f"{AGENT_PUBLIC_URL}/runbook/{runbook_id}" if runbook_id else ""

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


@app.post("/webhook", status_code=202)
async def alertmanager_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe payload do Alertmanager e enfileira cada alerta para análise assíncrona.

    Retorna 202 Accepted imediatamente após validação e deduplicação — o Alertmanager
    não bloqueia aguardando o LLM. A análise, geração de runbook e notificação Teams
    ocorrem em background via BackgroundTasks do FastAPI.
    """
    try:
        payload = await request.json()
    except Exception:
        WEBHOOKS_RECEIVED.labels(status="invalid_json").inc()
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    alerts = payload.get("alerts", [])
    if not alerts:
        WEBHOOKS_RECEIVED.labels(status="empty").inc()
        return JSONResponse({"message": "Nenhum alerta no payload", "queued": 0})

    WEBHOOKS_RECEIVED.labels(status="success").inc()

    queued = 0
    for alert in alerts:
        status     = alert.get("status", "firing")
        labels     = alert.get("labels", {})
        alert_name = labels.get("alertname", "unknown")
        alert_id   = uuid.uuid4().hex[:8]

        logger.info("[%s] Alerta recebido: %s | status: %s | labels: %s",
                    alert_id, alert_name, status, json.dumps(labels))

        if labels.get("agentia") != "true":
            logger.debug("[%s] Alerta %s ignorado (sem label agentia=true)", alert_id, alert_name)
            ALERTS_FILTERED.inc()
            continue

        fingerprint = _make_fingerprint(alert)
        if _is_duplicate(fingerprint, status):
            logger.info("[%s] Alerta %s duplicado (fingerprint=%s) — ignorado dentro do TTL de %ds",
                        alert_id, alert_name, fingerprint, DEDUP_TTL_SECONDS)
            ALERTS_DEDUPLICATED.inc()
            continue

        logger.info("[%s] Alerta %s enfileirado para análise em background", alert_id, alert_name)
        background_tasks.add_task(_process_alert, alert, alert_id)
        queued += 1

    return JSONResponse(
        {"message": f"{queued} alerta(s) enfileirado(s)", "queued": queued},
        status_code=202,
    )


@app.get("/runbook/{alert_id}", response_class=HTMLResponse)
async def get_runbook(alert_id: str):
    """Serve o runbook gerado para um alerta específico (gerado pelo agente após análise)."""
    if alert_id not in _runbooks:
        raise HTTPException(status_code=404, detail=f"Runbook '{alert_id}' não encontrado.")
    alert_name, runbook_md = _runbooks[alert_id]
    return HTMLResponse(render_runbook_html(alert_name, runbook_md))


@app.get("/runbook/by-alert/{alert_name}", response_class=HTMLResponse)
async def get_runbook_by_alert(alert_name: str):
    """
    Serve o runbook mais recente para um alertname.

    Usado como runbook_url estático nas PrometheusRules — a URL não muda entre ocorrências
    do mesmo alerta, mas sempre retorna o conteúdo do runbook mais recentemente gerado.
    Formato: GET /runbook/by-alert/ZeebeMemoryPredictedHigh
    """
    alert_id = _latest_runbook_by_name.get(alert_name)
    if not alert_id or alert_id not in _runbooks:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum runbook encontrado para '{alert_name}'. O agente ainda não analisou este alerta.",
        )
    name, runbook_md = _runbooks[alert_id]
    return HTMLResponse(render_runbook_html(name, runbook_md))


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

    now     = datetime.now(UTC)
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
