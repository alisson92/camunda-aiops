"""
Envia notificações de alertas AIOps para um canal do Microsoft Teams
via Incoming Webhook, usando Adaptive Card v1.2.

Estrutura do card:
  - Título: {emoji} {STATUS} - {alertname}
  - Metadata: Severity / Started / Resolved (se resolved)
  - Summary e Description das annotations
  - Botão "Ver análise" (Action.ShowCard com análise do agente)
  - Botão "Abrir Dashboard" (Action.OpenUrl)
  - Botão "Runbook" (Action.OpenUrl, se annotation presente)
  - Botão "Silence 1h" (Action.OpenUrl, apenas em FIRING)

Regra de cores e emojis por severidade:
  critical → vermelho (attention) 🚨  |  status label: FIRING
  warning  → amarelo (warning)   ⚠️   |  status label: WARNING
  info     → azul    (accent)    ℹ️   |  status label: INFO
  resolved → verde   (good)      ✅   |  status label: RESOLVED
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from config import AGENT_PUBLIC_URL, GRAFANA_DASHBOARD_UID, GRAFANA_URL, TEAMS_WEBHOOK_URL

logger = logging.getLogger(__name__)

# UTC-3 fixo (Brasília — sem horário de verão desde 2019)
_BRT = timezone(timedelta(hours=-3))

_SEVERITY_COLOR = {
    "critical": "attention",  # vermelho
    "warning":  "warning",    # amarelo
    "info":     "accent",     # azul
}

_SEVERITY_EMOJI = {
    "critical": "🚨",
    "warning":  "⚠️",
    "info":     "ℹ️",
}

_SEVERITY_STATUS_LABEL = {
    "critical": "FIRING",
    "warning":  "WARNING",
    "info":     "INFO",
}

# Prefixos que identificam linhas de comando/script na análise
_CMD_PREFIXES = (
    "kubectl", "helm", "grep", "curl", "bash", "sh ",
    "docker", "python", "pip", "cat ", "echo ", "export ",
)


# ---------------------------------------------------------------------------
# Helpers de tempo
# ---------------------------------------------------------------------------

def _format_alert_time(iso_str: str) -> str:
    """Converte timestamp ISO 8601 do Alertmanager para dd/mm/yyyy HH:MM (BRT)."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(_BRT).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return iso_str


def _format_duration(starts_at: str, ends_at: str) -> str:
    """Calcula e formata a duração entre dois timestamps ISO 8601."""
    try:
        start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        end   = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        total_minutes = max(0, int((end - start).total_seconds() // 60))
        if total_minutes < 60:
            return f"{total_minutes} min"
        hours, minutes = divmod(total_minutes, 60)
        return f"{hours}h {minutes}min" if minutes else f"{hours}h"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Processamento do texto de análise (bloco AIOps)
# ---------------------------------------------------------------------------

def _clean_analysis(text: str) -> str:
    """
    Normaliza texto de análise LLM para Adaptive Card:
    - Headings (#/##/###) → **negrito**
    - Fenced code blocks → conteúdo sem marcadores
    - Inline code → texto simples (evita retângulos no Teams)
    - Linhas --- e ——— → removidas (separator:True já faz a divisão visual)
    - Múltiplas linhas em branco → colapsadas
    """
    text = re.sub(r"^#{1,3}\s+(.+)$", r"**\1**", text, flags=re.MULTILINE)
    text = re.sub(r"```[^\n]*\n(.*?)```", lambda m: m.group(1).strip(), text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"^[\-—]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[—\-]+.*[—\-]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _build_analysis_blocks(text: str) -> list[dict]:
    """
    Converte o texto de análise em TextBlocks para o ShowCard:
    - **Header:** → negrito com separador visual acima
    - Linhas de comando (kubectl, helm, etc.) → azul monospace
    - Demais linhas → texto normal
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

        if re.match(r"^\*\*[^*]+:\*\*$", stripped):
            flush_pending()
            block: dict = {
                "type": "TextBlock",
                "text": stripped,
                "weight": "Bolder",
                "wrap": True,
                "spacing": "Large",
            }
            if not first_header:
                block["separator"] = True
            first_header = False
            blocks.append(block)

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
                "size": "Small",
                "wrap": True,
                "spacing": "Small",
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
# Montagem e envio do card
# ---------------------------------------------------------------------------

def send_alert_to_teams(
    alert_name: str,
    alert_labels: dict,
    alert_annotations: dict,
    status: str,
    analysis: str,
    starts_at: str = "",
    ends_at: str = "",
    runbook_url: str = "",
) -> bool:
    """
    Envia Adaptive Card para o Teams com análise AIOps.
    Retorna True se enviado com sucesso.
    """
    if not TEAMS_WEBHOOK_URL:
        logger.warning("TEAMS_WEBHOOK_URL não configurado — notificação ignorada.")
        return False

    is_resolved = status == "resolved"

    severity    = alert_labels.get("severity", "info")
    summary     = alert_annotations.get("summary", "")
    description = alert_annotations.get("description", "").strip()
    runbook_url = runbook_url or alert_annotations.get("runbook_url", "")

    started_str  = _format_alert_time(starts_at) if starts_at else datetime.now(_BRT).strftime("%d/%m/%Y %H:%M")
    resolved_str = _format_alert_time(ends_at) if ends_at else ""

    emoji        = "✅" if is_resolved else _SEVERITY_EMOJI.get(severity.lower(), "🔔")
    status_label = "RESOLVED" if is_resolved else _SEVERITY_STATUS_LABEL.get(severity.lower(), "FIRING")
    header_color = "good" if is_resolved else _SEVERITY_COLOR.get(severity.lower(), "accent")

    # ------------------------------------------------------------------
    # REGIÃO 1 — Título
    # ------------------------------------------------------------------
    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": f"{emoji} {status_label} - {alert_name}",
            "weight": "Bolder",
            "size": "Large",
            "color": header_color,
            "wrap": True,
        },
    ]

    # ------------------------------------------------------------------
    # REGIÃO 2 — Metadata
    # ------------------------------------------------------------------
    meta_lines = [
        f"**Severity:** {severity.title()}",
        f"**Started:** {started_str}",
    ]
    if is_resolved and resolved_str:
        meta_lines.append(f"**Resolved:** {resolved_str}")
        duration_str = _format_duration(starts_at, ends_at)
        if duration_str:
            meta_lines.append(f"**Duração:** {duration_str}")

    body.append({
        "type": "TextBlock",
        "text": "\n".join(meta_lines),
        "wrap": True,
        "separator": True,
        "spacing": "Medium",
    })

    # ------------------------------------------------------------------
    # REGIÃO 3 — Summary
    # ------------------------------------------------------------------
    if summary:
        body.append({
            "type": "TextBlock",
            "text": summary,
            "wrap": True,
            "isSubtle": True,
            "separator": True,
            "spacing": "Medium",
        })

    # ------------------------------------------------------------------
    # REGIÃO 4 — Description
    # ------------------------------------------------------------------
    if description and description != summary:
        body.append({
            "type": "TextBlock",
            "text": description,
            "wrap": True,
            "spacing": "Small",
        })

    # ------------------------------------------------------------------
    # Botões de ação
    # ------------------------------------------------------------------
    actions: list[dict] = []

    if analysis and analysis.strip():
        clean = _clean_analysis(_truncate(analysis))
        analysis_blocks = _build_analysis_blocks(clean)
        if analysis_blocks:
            actions.append({
                "type": "Action.ShowCard",
                "title": "📋 Ver análise do agente",
                "card": {
                    "type": "AdaptiveCard",
                    "body": analysis_blocks,
                },
            })

    actions.append({
        "type": "Action.OpenUrl",
        "title": "📊 Dashboard",
        "url": f"{GRAFANA_URL}/d/{GRAFANA_DASHBOARD_UID}",
    })

    if runbook_url and not is_resolved:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "📖 Runbook",
            "url": runbook_url,
        })

    if not is_resolved:
        silence_url = f"{AGENT_PUBLIC_URL}/silence?alert={quote(alert_name)}&duration=1h"
        actions.append({
            "type": "Action.OpenUrl",
            "title": "🔕 Silence 1h",
            "url": silence_url,
        })

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
        logger.info("Notificação enviada. HTTP %s", resp.status_code)
        return True
    except httpx.HTTPError as e:
        logger.error("Falha ao enviar notificação: %s", e)
        return False
