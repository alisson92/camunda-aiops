"""
Servidor FastAPI que recebe payloads do Alertmanager e aciona o agente reativo.

Uso:
  uvicorn webhook_receiver:app --host 0.0.0.0 --port 5001
"""

import json
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from reactive_agent import run_agent
from teams_notifier import send_alert_to_teams

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
