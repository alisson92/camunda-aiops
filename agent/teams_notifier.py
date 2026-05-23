"""
Envia notificações de alertas AIOps para um canal do Microsoft Teams
via Incoming Webhook, usando Adaptive Card v1.2.

Configuração (agent/.env):
  TEAMS_WEBHOOK_URL    — URL do webhook (obrigatório)
  GRAFANA_URL          — Base URL do Grafana (padrão: http://localhost:3000)
  GRAFANA_DASHBOARD_UID — UID do dashboard de forecasting
  AGENT_PUBLIC_URL     — URL base do agente, para montar link do /silence
"""

import os
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import httpx

TEAMS_WEBHOOK_URL    = os.environ.get("TEAMS_WEBHOOK_URL", "")
GRAFANA_URL          = os.environ.get("GRAFANA_URL", "http://localhost:3000").rstrip("/")
GRAFANA_DASHBOARD_UID = os.environ.get("GRAFANA_DASHBOARD_UID", "camunda-local-forecasting")
AGENT_PUBLIC_URL     = os.environ.get("AGENT_PUBLIC_URL", "http://localhost:5001").rstrip("/")

# UTC-3 fixo (Brasília — sem horário de verão desde 2019)
_BRT = timezone(timedelta(hours=-3))

_SEVERITY_COLOR = {
    "critical": "attention",
    "warning":  "warning",
    "info":     "accent",
}

_SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning":  "🟡",
    "info":     "🔵",
}

# Prefixos que identificam linhas de comando/script
_CMD_PREFIXES = (
    "kubectl", "helm", "grep", "curl", "bash", "sh ",
    "docker", "python", "pip", "cat ", "echo ", "export ",
)


# ---------------------------------------------------------------------------
# Processamento do texto de análise
# ---------------------------------------------------------------------------

def _clean_markdown(text: str) -> str:
    """
    Normaliza texto para Adaptive Card do Teams:
    - Headings (#/##/###) → **negrito** (evita H2 gigante)
    - Fenced code blocks → conteúdo sem marcadores
    - Inline code (`texto`) → texto simples (evita retângulos)
    """
    text = re.sub(r"^#{1,3}\s+(.+)$", r"**\1**", text, flags=re.MULTILINE)
    text = re.sub(r"```[^\n]*\n(.*?)```", lambda m: m.group(1).strip(), text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


def _build_analysis_blocks(text: str) -> list[dict]:
    """
    Converte o texto de análise em TextBlocks Adaptive Card:
    - **Header:** vira linha em negrito com separador visual acima
    - Linhas de comando (kubectl, helm, etc.) ficam em azul monospace
    - Demais linhas ficam como texto normal
    """
    blocks: list[dict] = []
    pending_lines: list[str] = []
    first_header = True

    def flush_pending():
        content = "\n".join(pending_lines).strip()
        pending_lines.clear()
        if content:
            blocks.append({
                "type": "TextBlock",
                "text": content,
                "wrap": True,
                "spacing": "Small",
            })

    for line in text.split("\n"):
        stripped = line.strip()

        # Cabeçalho de seção: **Texto:**
        if re.match(r"^\*\*[^*]+:\*\*$", stripped):
            flush_pending()
            block: dict = {
                "type": "TextBlock",
                "text": stripped,
                "weight": "Bolder",
                "wrap": True,
                "spacing": "Medium",
            }
            if not first_header:
                block["separator"] = True
            first_header = False
            blocks.append(block)

        # Linha de comando: indentada ou começa com prefixo conhecido
        elif stripped and (
            stripped.lower().startswith(_CMD_PREFIXES)
            or (line.startswith("   ") and stripped)
        ):
            flush_pending()
            blocks.append({
                "type": "TextBlock",
                "text": f"  {stripped}",
                "color": "accent",
                "fontType": "Monospace",
                "wrap": True,
                "spacing": "None",
            })

        else:
            pending_lines.append(line)

    flush_pending()
    return blocks


def _truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n*(análise truncada — veja o terminal para o texto completo)*"


# ---------------------------------------------------------------------------
# Montagem dos botões de ação
# ---------------------------------------------------------------------------

def _build_actions(alert_name: str, alert_annotations: dict, analysis_blocks: list[dict]) -> list[dict]:
    """
    Retorna a lista de Action para o card:
    - Ver análise completa (Action.ShowCard — expansível inline)
    - Abrir Dashboard (Action.OpenUrl → Grafana)
    - Runbook (Action.OpenUrl → docs, se disponível)
    - Silence 1h (Action.OpenUrl → endpoint /silence do agente)
    """
    actions: list[dict] = []

    # Botão 1 — análise expansível (não abre nova janela, expande inline)
    if analysis_blocks:
        actions.append({
            "type": "Action.ShowCard",
            "title": "📋 Ver análise completa",
            "card": {
                "type": "AdaptiveCard",
                "body": analysis_blocks,
            },
        })

    # Botão 2 — Dashboard Grafana
    dashboard_url = f"{GRAFANA_URL}/d/{GRAFANA_DASHBOARD_UID}"
    actions.append({
        "type": "Action.OpenUrl",
        "title": "📊 Abrir Dashboard",
        "url": dashboard_url,
    })

    # Botão 3 — Runbook (só aparece se a annotation existir)
    runbook_url = alert_annotations.get("runbook_url", "")
    if runbook_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "📖 Runbook",
            "url": runbook_url,
        })

    # Botão 4 — Silence 1h via endpoint do agente
    silence_url = (
        f"{AGENT_PUBLIC_URL}/silence"
        f"?alert={quote(alert_name)}"
        f"&duration=1h"
    )
    actions.append({
        "type": "Action.OpenUrl",
        "title": "🔕 Silence 1h",
        "url": silence_url,
    })

    return actions


# ---------------------------------------------------------------------------
# Montagem e envio do card
# ---------------------------------------------------------------------------

def send_alert_to_teams(
    alert_name: str,
    alert_labels: dict,
    alert_annotations: dict,
    status: str,
    analysis: str,
) -> bool:
    """
    Envia um Adaptive Card para o Teams seguindo o padrão visual do time.
    Retorna True se enviado com sucesso, False caso contrário.
    """
    if not TEAMS_WEBHOOK_URL:
        print("[teams] TEAMS_WEBHOOK_URL não configurado — notificação ignorada.")
        return False

    severity  = alert_labels.get("severity", "info")
    namespace = alert_labels.get("namespace", "—")
    pod       = alert_labels.get("pod", alert_labels.get("instance", "—"))
    summary   = alert_annotations.get("summary", "Sem resumo disponível.")
    timestamp = datetime.now(_BRT).strftime("%d/%m/%Y %H:%M (Brasília)")

    emoji        = _SEVERITY_EMOJI.get(severity.lower(), "🔵")
    header_color = _SEVERITY_COLOR.get(severity.lower(), "accent")
    status_label = "RESOLVED" if status == "resolved" else "FIRING"
    if status == "resolved":
        emoji        = "✅"
        header_color = "good"

    clean_analysis  = _clean_markdown(_truncate(analysis))
    analysis_blocks = _build_analysis_blocks(clean_analysis)
    actions         = _build_actions(alert_name, alert_annotations, analysis_blocks)

    body: list[dict] = [
        # REGIÃO 1 — Cabeçalho
        {
            "type": "TextBlock",
            "text": f"{emoji} {status_label} - {alert_name}",
            "weight": "Bolder",
            "size": "Medium",
            "color": header_color,
            "wrap": True,
        },
        # REGIÃO 2 — Metadados
        {
            "type": "TextBlock",
            "text": (
                f"• **Severity:** {severity}\n"
                f"• **Namespace:** {namespace}\n"
                f"• **Pod:** {pod}\n"
                f"• **Iniciado:** {timestamp}"
            ),
            "wrap": True,
            "separator": True,
            "spacing": "Medium",
        },
        # REGIÃO 3 — Descrição curta
        {
            "type": "TextBlock",
            "text": summary,
            "wrap": True,
            "isSubtle": True,
            "separator": True,
            "spacing": "Medium",
        },
    ]

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": body,
                    "actions": actions,
                },
            }
        ],
    }

    try:
        resp = httpx.post(TEAMS_WEBHOOK_URL, json=card, timeout=10)
        resp.raise_for_status()
        print(f"[teams] Notificação enviada. HTTP {resp.status_code}")
        return True
    except httpx.HTTPError as e:
        print(f"[teams] Falha ao enviar notificação: {e}")
        return False
