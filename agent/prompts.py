"""Loader de prompts — lê os arquivos .md de prompts/ e os expõe para o agente."""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load("system-prompt-v1.md")


def build_user_message(alert_name: str, alert_labels: dict, alert_annotations: dict, status: str) -> str:
    labels_str = "\n".join(f"  {k}: {v}" for k, v in alert_labels.items())
    annotations_str = "\n".join(f"  {k}: {v}" for k, v in alert_annotations.items())
    return f"""Alerta recebido do Alertmanager:

**Nome:** {alert_name}
**Status:** {status}
**Labels:**
{labels_str}
**Annotations:**
{annotations_str}

Consulte as métricas, identifique a causa raiz e gere o relatório seguindo EXATAMENTE o formato definido no system prompt.
"""
