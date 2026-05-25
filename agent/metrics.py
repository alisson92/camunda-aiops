"""
Métricas Prometheus do agente AIOps.

Expostas em GET /metrics (formato text/plain Prometheus).
Importado por webhook_receiver, reactive_agent e teams_notifier.
"""

from prometheus_client import Counter, Histogram

WEBHOOKS_RECEIVED = Counter(
    "aiops_webhooks_total",
    "Total de payloads recebidos no endpoint /webhook",
    ["status"],  # success | invalid_json | empty
)

ALERTS_PROCESSED = Counter(
    "aiops_alerts_processed_total",
    "Alertas analisados pelo agente",
    ["alertname", "severity"],
)

ALERTS_FILTERED = Counter(
    "aiops_alerts_filtered_total",
    "Alertas ignorados por estarem fora do escopo Camunda",
)

ANALYSIS_DURATION = Histogram(
    "aiops_analysis_duration_seconds",
    "Duração do ciclo completo de análise do agente (run_agent)",
    buckets=[1, 5, 10, 20, 30, 60, 120],
)

LLM_TOOL_CALLS = Counter(
    "aiops_llm_tool_calls_total",
    "Chamadas de ferramentas executadas pelo agente LLM",
    ["tool_name"],
)

TEAMS_NOTIFICATIONS = Counter(
    "aiops_teams_notifications_total",
    "Notificações enviadas ao Microsoft Teams",
    ["success"],  # "true" | "false"
)
