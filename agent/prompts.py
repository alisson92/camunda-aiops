"""Loader de prompts — lê os arquivos .md de prompts/ e os expõe para o agente."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge_base import Document

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


SYSTEM_PROMPT = _load("system-prompt-v2.md")


def build_user_message(
    alert_name: str,
    alert_labels: dict,
    alert_annotations: dict,
    status: str,
    context_docs: list[Document] | None = None,
) -> str:
    parts: list[str] = []

    if context_docs:
        parts.append("## Contexto relevante — histórico do time\n")
        for doc in context_docs:
            label = "Runbook anterior" if doc.source == "generated" else "Exemplo de análise"
            parts.append(f"### {label}: {doc.alert_name or doc.title}\n\n{doc.excerpt(500)}\n")
        parts.append("---\n")

    labels_str = "\n".join(f"  {k}: {v}" for k, v in alert_labels.items())
    annotations_str = "\n".join(f"  {k}: {v}" for k, v in alert_annotations.items())
    parts.append(f"""Alerta recebido do Alertmanager:

**Nome:** {alert_name}
**Status:** {status}
**Labels:**
{labels_str}
**Annotations:**
{annotations_str}

Consulte as métricas, identifique a causa raiz e gere o relatório seguindo EXATAMENTE o formato definido no system prompt.
""")
    return "\n".join(parts)
