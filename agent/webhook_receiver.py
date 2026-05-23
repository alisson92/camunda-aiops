"""
Servidor FastAPI que recebe payloads do Alertmanager e aciona o agente reativo.

Uso:
  uvicorn webhook_receiver:app --host 0.0.0.0 --port 5001
"""

import json
import os
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Query, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import httpx
from reactive_agent import run_agent
from teams_notifier import send_alert_to_teams

_ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://localhost:9093")

app = FastAPI(title="Camunda AIOps Webhook Receiver")


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.post("/webhook")
async def alertmanager_webhook(request: Request):
    """
    Recebe payload do Alertmanager (formato padrão webhook_configs).
    Aciona o agente para cada alerta firing no payload.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    alerts = payload.get("alerts", [])
    if not alerts:
        return JSONResponse({"message": "Nenhum alerta no payload", "processed": 0})

    analyses = []
    for alert in alerts:
        status = alert.get("status", "firing")
        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        alert_name = labels.get("alertname", "unknown")

        print(f"\n{'='*60}")
        print(f"Alerta recebido: {alert_name} | status: {status}")
        print(f"Labels: {json.dumps(labels, ensure_ascii=False)}")
        print(f"{'='*60}")

        # Apenas alertas Camunda/Zeebe disparam análise
        if not any(kw in alert_name for kw in ("Zeebe", "Camunda")):
            print(f"[webhook] Alerta {alert_name} ignorado (fora do escopo Camunda)")
            continue

        analysis = run_agent(
            alert_name=alert_name,
            alert_labels=labels,
            alert_annotations=annotations,
            status=status,
        )

        print(f"\n{'='*60}")
        print("ANÁLISE DO AGENTE:")
        print(analysis)
        print(f"{'='*60}\n")

        send_alert_to_teams(
            alert_name=alert_name,
            alert_labels=labels,
            alert_annotations=annotations,
            status=status,
            analysis=analysis,
        )

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

    Exemplos de duration: 30m, 1h, 4h, 24h
    """
    # Converte duração simples (ex: 1h, 30m) para timedelta
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
        raise HTTPException(status_code=400, detail=f"Unidade não suportada: {unit}. Use h (horas) ou m (minutos).")

    now = datetime.now(timezone.utc)
    ends_at = now + delta

    silence_payload = {
        "matchers": [{"name": "alertname", "value": alert, "isRegex": False}],
        "startsAt": now.isoformat(),
        "endsAt": ends_at.isoformat(),
        "createdBy": "aiops-agent",
        "comment": f"Silence criado via card Teams — duração: {duration}",
    }

    try:
        resp = httpx.post(
            f"{_ALERTMANAGER_URL}/api/v2/silences",
            json=silence_payload,
            timeout=10,
        )
        resp.raise_for_status()
        silence_id = resp.json().get("silenceID", "—")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha ao criar silence no Alertmanager: {e}")

    ends_local = ends_at.astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M (Brasília)")
    return f"""
    <html><body style="font-family:sans-serif;max-width:480px;margin:40px auto;text-align:center">
      <h2>🔕 Silence criado</h2>
      <p><strong>Alerta:</strong> {alert}</p>
      <p><strong>Duração:</strong> {duration} — expira em {ends_local}</p>
      <p><strong>ID:</strong> <code>{silence_id}</code></p>
      <p style="color:#666;font-size:0.9em">Você pode fechar esta aba.</p>
    </body></html>
    """
