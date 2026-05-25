"""
Ferramentas Prometheus chamadas pelo agente via tool use.
Cada função bate diretamente na HTTP API do Prometheus local (porta 9090).
"""

import logging
import time as _time

import httpx

from config import ALERT_FILTER_KEYWORDS, PROMETHEUS_URL

logger = logging.getLogger(__name__)


def _resolve_ts(ts: str) -> str:
    """Converte timestamps relativos (now, now-30m, now-1h) para Unix timestamp.

    A Prometheus HTTP API aceita timestamps relativos em /api/v1/query, mas
    exige Unix timestamp ou RFC3339 em /api/v1/query_range. Esta função
    normaliza a entrada para que ambos os endpoints recebam um formato válido.
    """
    if not ts.startswith("now"):
        return ts
    if ts == "now":
        return str(int(_time.time()))
    offset = ts[len("now-"):]
    units = {"s": 1, "m": 60, "h": 3600}
    unit = offset[-1]
    seconds = int(offset[:-1]) * units[unit] if unit in units else int(offset)
    return str(int(_time.time() - seconds))


def query_prometheus_instant(expr: str) -> dict:
    """Executa uma PromQL instant query e retorna os resultados."""
    try:
        resp = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": expr},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "success":
            return {"error": f"Prometheus retornou status={data['status']}"}
        results = data["data"]["result"]
        if not results:
            return {
                "empty": True,
                "expr": expr,
                "hint": "Nenhuma série encontrada. Verifique labels e se o target está ativo.",
            }
        return {
            "resultType": data["data"]["resultType"],
            "results": [
                {"labels": r["metric"], "value": r["value"][1]}
                for r in results
            ],
        }
    except httpx.HTTPError as e:
        logger.error("Falha na query instant '%s': %s", expr, e)
        return {"error": str(e)}


def query_prometheus_range(expr: str, start: str, end: str, step: str = "60") -> dict:
    """Executa uma PromQL range query para ver tendência temporal."""
    try:
        resp = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={"query": expr, "start": _resolve_ts(start), "end": _resolve_ts(end), "step": step},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data["status"] != "success":
            return {"error": f"Prometheus retornou status={data['status']}"}
        results = data["data"]["result"]
        if not results:
            return {"empty": True, "expr": expr}
        # Retorna apenas os últimos 5 pontos por série para não sobrecarregar o contexto
        return {
            "resultType": data["data"]["resultType"],
            "results": [
                {
                    "labels": r["metric"],
                    "last_5_values": r["values"][-5:],
                }
                for r in results
            ],
        }
    except httpx.HTTPError as e:
        logger.error("Falha na query range '%s': %s", expr, e)
        return {"error": str(e)}


def get_alert_rules() -> dict:
    """Lista as PrometheusRules ativas e seus thresholds."""
    try:
        resp = httpx.get(f"{PROMETHEUS_URL}/api/v1/rules", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        camunda_rules = []
        for group in data["data"]["groups"]:
            for rule in group["rules"]:
                if rule.get("type") == "alerting" and any(
                    kw in rule["name"] for kw in ALERT_FILTER_KEYWORDS
                ):
                    camunda_rules.append({
                        "name": rule["name"],
                        "state": rule.get("state"),
                        "health": rule.get("health"),
                        "query": rule.get("query"),
                        "labels": rule.get("labels", {}),
                        "annotations": rule.get("annotations", {}),
                    })
        return {"rules": camunda_rules, "total": len(camunda_rules)}
    except httpx.HTTPError as e:
        logger.error("Falha ao buscar alert rules: %s", e)
        return {"error": str(e)}


# Mapa nome → função, usado pelo agente para despachar chamadas de ferramenta
TOOL_DISPATCH = {
    "query_prometheus_instant": query_prometheus_instant,
    "query_prometheus_range":   query_prometheus_range,
    "get_alert_rules":          get_alert_rules,
}

# Schemas no formato OpenAI / Ollama (compatível com openai SDK)
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "query_prometheus_instant",
            "description": (
                "Executa uma PromQL instant query no Prometheus local e retorna os valores atuais. "
                "Use para checar o estado presente de uma métrica."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {
                        "type": "string",
                        "description": "Expressão PromQL a executar, ex: jvm_memory_used_bytes{pod='camunda-zeebe-0'}",
                    }
                },
                "required": ["expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_prometheus_range",
            "description": (
                "Executa uma PromQL range query para observar a tendência de uma métrica ao longo do tempo. "
                "Use para confirmar se um recurso está crescendo ou oscilando."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expr":  {"type": "string", "description": "Expressão PromQL"},
                    "start": {"type": "string", "description": "Início em Unix timestamp ou relativo, ex: 'now-30m'"},
                    "end":   {"type": "string", "description": "Fim em Unix timestamp ou relativo, ex: 'now'"},
                    "step":  {"type": "string", "description": "Intervalo em segundos entre pontos, ex: '60'"},
                },
                "required": ["expr", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alert_rules",
            "description": (
                "Lista as PrometheusRules preditivas do Camunda com seus thresholds e estado atual. "
                "Use para entender o que cada alerta está monitorando."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
