"""
Envia notificações de alertas AIOps para um canal do Microsoft Teams
via Incoming Webhook, usando Adaptive Card para formatação rica.

Configuração:
  Definir TEAMS_WEBHOOK_URL no arquivo agent/.env
  (nunca commitar a URL do webhook — ela é um segredo)
"""

import os
from datetime import datetime, timezone

import httpx

# Carregado via .env pelo reactive_agent — disponível em os.environ ao importar após ele
TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL", "")

_SEVERITY_STYLE = {
    "critical": ("attention", "🔴"),
    "warning":  ("warning",   "🟡"),
    "info":     ("accent",    "🔵"),
}
_RESOLVED_STYLE = ("good", "✅")


def _card_style(severity: str, status: str) -> tuple[str, str]:
    """Retorna (container_style, emoji) baseado em severidade e status."""
    if status == "resolved":
        return _RESOLVED_STYLE
    return _SEVERITY_STYLE.get(severity.lower(), ("accent", "🔵"))


def _truncate(text: str, limit: int = 4000) -> str:
    """Limita o texto para não exceder o tamanho máximo do card."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n*(análise truncada — veja o terminal para o texto completo)*"


def send_alert_to_teams(
    alert_name: str,
    alert_labels: dict,
    alert_annotations: dict,
    status: str,
    analysis: str,
) -> bool:
    """
    Envia um card formatado para o Teams.
    Retorna True se enviado com sucesso, False caso contrário.
    Se TEAMS_WEBHOOK_URL não estiver configurado, apenas loga e retorna False.
    """
    if not TEAMS_WEBHOOK_URL:
        print("[teams] TEAMS_WEBHOOK_URL não configurado — notificação ignorada.")
        return False

    severity = alert_labels.get("severity", "info")
    namespace = alert_labels.get("namespace", "—")
    pod = alert_labels.get("pod", alert_labels.get("instance", "—"))
    summary = alert_annotations.get("summary", "Sem resumo disponível.")
    timestamp = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    container_style, emoji = _card_style(severity, status)
    status_label = "✅ Resolvido" if status == "resolved" else f"🚨 {status.upper()}"

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        # Cabeçalho: ícone + nome do alerta + status
                        {
                            "type": "Container",
                            "style": container_style,
                            "bleed": True,
                            "items": [
                                {
                                    "type": "ColumnSet",
                                    "columns": [
                                        {
                                            "type": "Column",
                                            "width": "auto",
                                            "items": [
                                                {
                                                    "type": "TextBlock",
                                                    "text": emoji,
                                                    "size": "ExtraLarge",
                                                    "wrap": False,
                                                }
                                            ],
                                        },
                                        {
                                            "type": "Column",
                                            "width": "stretch",
                                            "items": [
                                                {
                                                    "type": "TextBlock",
                                                    "text": alert_name,
                                                    "weight": "Bolder",
                                                    "size": "Large",
                                                    "wrap": True,
                                                },
                                                {
                                                    "type": "TextBlock",
                                                    "text": f"{status_label} · severity: **{severity}**",
                                                    "isSubtle": True,
                                                    "spacing": "None",
                                                    "wrap": True,
                                                },
                                            ],
                                        },
                                    ],
                                }
                            ],
                        },
                        # Resumo e metadados
                        {
                            "type": "TextBlock",
                            "text": summary,
                            "wrap": True,
                            "spacing": "Medium",
                        },
                        {
                            "type": "FactSet",
                            "spacing": "Small",
                            "facts": [
                                {"title": "Namespace", "value": namespace},
                                {"title": "Pod / Instância", "value": pod},
                                {"title": "Horário", "value": timestamp},
                            ],
                        },
                        # Análise gerada pelo agente
                        {
                            "type": "TextBlock",
                            "text": "**Análise do Agente AIOps (Ollama)**",
                            "weight": "Bolder",
                            "separator": True,
                            "spacing": "Large",
                        },
                        {
                            "type": "TextBlock",
                            "text": _truncate(analysis),
                            "wrap": True,
                            "spacing": "Small",
                        },
                    ],
                },
            }
        ],
    }

    try:
        resp = httpx.post(TEAMS_WEBHOOK_URL, json=card, timeout=10)
        resp.raise_for_status()
        print(f"[teams] Notificação enviada para o canal. Status HTTP: {resp.status_code}")
        return True
    except httpx.HTTPError as e:
        print(f"[teams] Falha ao enviar notificação: {e}")
        return False
