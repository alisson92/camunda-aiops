"""
Gera runbooks operacionais Markdown a partir da análise do agente reativo.

Fluxo:
  run_agent() → análise estruturada
                    ↓
  generate_runbook() → segunda chamada LLM (sem tool use)
                    ↓
               Runbook Markdown

O runbook é servido via GET /runbook/{alert_id} no webhook_receiver.
"""

import hashlib
import html as _html
import logging
import re
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

_BRT = timezone(timedelta(hours=-3))

_RUNBOOK_SYSTEM_PROMPT = """\
Você é um engenheiro SRE especializado em Kubernetes e Camunda 8 Self-Managed.
Receberá a análise de um alerta já realizada por outro agente.
Sua tarefa é transformar essa análise em um runbook operacional em Markdown.

Regras:
- Responda APENAS com o Markdown do runbook — sem texto antes ou depois
- Use exatamente os headings da estrutura fornecida (##, ###)
- Português brasileiro, tom técnico e objetivo
- Comandos kubectl/helm em blocos de código com ```
- Máximo de 600 palavras
"""

_RUNBOOK_USER_TEMPLATE = """\
## Análise do agente AIOps

{analysis}

## Metadados do alerta

- **alertname:** {alert_name}
- **severity:** {severity}
- **namespace:** {namespace}

## Estrutura obrigatória do runbook

Preencha a estrutura abaixo mantendo os headings exatos:

# Runbook: {alert_name}

**Severidade:** {severity} | **Componente:** {component} | **Gerado em:** {generated_at}

## Descrição
<descreva brevemente o que é este alerta e em que condições é acionado>

## Causa Raiz Identificada
<extraia a causa raiz da análise fornecida>

## Procedimento de Remediação

### Diagnóstico inicial
1. <primeiro comando de diagnóstico>
2. <segundo comando>

### Ações corretivas
1. <ação principal>
2. <ação secundária se necessário>

## Verificação de Resolução
- <métrica ou saída de comando que confirma normalização>

## Prevenção
- <ajuste de configuração ou capacidade para evitar recorrência>
"""


def _make_alert_id(alert_name: str, starts_at: str) -> str:
    """Gera um ID URL-safe único para um alerta — usado como chave do store e path da URL."""
    slug = re.sub(r"[^a-z0-9]+", "-", alert_name.lower()).strip("-")
    suffix = hashlib.md5(starts_at.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{suffix}"


def _infer_component(alert_name: str, labels: dict) -> str:
    """Infere o componente Camunda a partir do nome do alerta ou labels."""
    name_lower = alert_name.lower()
    if "zeebe" in name_lower:
        if "gateway" in name_lower or "backpressure" in name_lower:
            return "zeebe-gateway"
        return "zeebe-broker"
    if "camunda" in name_lower:
        return labels.get("namespace", "camunda")
    return labels.get("service", "unknown")


def _fallback_runbook(
    alert_name: str,
    severity: str,
    component: str,
    generated_at: str,
    analysis: str,
) -> str:
    """Runbook mínimo gerado localmente quando a chamada ao LLM falha."""
    return f"""# Runbook: {alert_name}

**Severidade:** {severity} | **Componente:** {component} | **Gerado em:** {generated_at}

## Causa Raiz Identificada

{analysis}

## Verificação de Resolução

- `kubectl get pods -n camunda`
- Verifique métricas no Grafana: `http://localhost:3000`
"""


def generate_runbook(
    alert_name: str,
    alert_labels: dict,
    analysis: str,
    starts_at: str = "",
) -> tuple[str, str]:
    """
    Chama o LLM (sem tool use) para transformar a análise em runbook Markdown.

    Retorna tupla (alert_id, runbook_markdown).
    alert_id é o identificador URL-safe usado para servir o runbook via GET /runbook/{alert_id}.
    """
    alert_id = _make_alert_id(alert_name, starts_at or "unknown")
    severity = alert_labels.get("severity", "unknown")
    namespace = alert_labels.get("namespace", "camunda")
    component = _infer_component(alert_name, alert_labels)
    generated_at = datetime.now(_BRT).strftime("%d/%m/%Y %H:%M")

    user_message = _RUNBOOK_USER_TEMPLATE.format(
        analysis=analysis,
        alert_name=alert_name,
        severity=severity,
        namespace=namespace,
        component=component,
        generated_at=generated_at,
    )

    client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

    try:
        response = client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": _RUNBOOK_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        runbook_md = (response.choices[0].message.content or "").strip()
        if not runbook_md:
            logger.warning("LLM retornou runbook vazio para %s — usando fallback", alert_name)
            return alert_id, _fallback_runbook(alert_name, severity, component, generated_at, analysis)
        logger.info("Runbook gerado: alert_id=%s (%d chars)", alert_id, len(runbook_md))
        return alert_id, runbook_md
    except Exception as e:
        logger.error("Falha ao gerar runbook para %s: %s", alert_name, e)
        fallback = _fallback_runbook(alert_name, severity, component, generated_at, analysis)
        return alert_id, fallback


# ---------------------------------------------------------------------------
# Renderização Markdown → HTML (sem dependência externa)
# ---------------------------------------------------------------------------

def _markdown_to_html(md: str) -> str:
    """Converte subconjunto de Markdown para HTML — cobre apenas os elementos do template."""
    code_blocks: list[str] = []

    def store_code(m: re.Match) -> str:
        code_blocks.append(
            f"<pre><code>{_html.escape(m.group(1).rstrip())}</code></pre>"
        )
        return f"\x00CODE{len(code_blocks) - 1}\x00"

    md = re.sub(r"```[^\n]*\n(.*?)```", store_code, md, flags=re.DOTALL)

    lines = md.split("\n")
    out: list[str] = []
    in_ul = False
    in_ol = False

    def close_ul() -> None:
        nonlocal in_ul
        if in_ul:
            out.append("</ul>")
            in_ul = False

    def close_ol() -> None:
        nonlocal in_ol
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def close_lists() -> None:
        close_ul()
        close_ol()

    def inline(text: str) -> str:
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        return text

    for line in lines:
        if "\x00CODE" in line:
            close_lists()
            idx = int(re.search(r"\x00CODE(\d+)\x00", line).group(1))
            out.append(code_blocks[idx])
        elif re.match(r"^# (.+)", line):
            close_lists()
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif re.match(r"^## (.+)", line):
            close_lists()
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif re.match(r"^### (.+)", line):
            close_lists()
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif m := re.match(r"^- (.+)", line):
            close_ol()
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"  <li>{inline(m.group(1))}</li>")
        elif m := re.match(r"^\d+\. (.+)", line):
            close_ul()
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"  <li>{inline(m.group(1))}</li>")
        elif not line.strip():
            close_lists()
        else:
            close_lists()
            out.append(f"<p>{inline(line)}</p>")

    close_lists()
    return "\n".join(x for x in out if x)


_HTML_PAGE = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Runbook: {title}</title>
  <style>
    body  {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
             max-width: 860px; margin: 40px auto; padding: 0 24px;
             color: #1e1e1e; line-height: 1.6; background: #fafafa; }}
    h1   {{ border-bottom: 2px solid #0078d4; padding-bottom: 8px; color: #0078d4; }}
    h2   {{ border-bottom: 1px solid #ddd; padding-bottom: 4px; margin-top: 32px; }}
    h3   {{ margin-top: 24px; color: #333; }}
    code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 4px;
            font-family: "Cascadia Code", "Consolas", monospace; font-size: 0.88em; }}
    pre  {{ background: #1e1e1e; color: #d4d4d4; padding: 16px;
            border-radius: 8px; overflow-x: auto; }}
    pre code {{ background: none; color: inherit; padding: 0; font-size: 0.9em; }}
    ul, ol {{ padding-left: 24px; }}
    li   {{ margin: 4px 0; }}
    p    {{ margin: 8px 0; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def render_runbook_html(alert_name: str, runbook_md: str) -> str:
    """Envolve o runbook Markdown em HTML completo pronto para servir no browser."""
    body = _markdown_to_html(runbook_md)
    return _HTML_PAGE.format(title=alert_name, body=body)
