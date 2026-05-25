# Etapa 10 — Observabilidade do Agente AIOps

## Problema

O agente analisava alertas, acionava ferramentas Prometheus e enviava cards ao Teams — mas sem nenhuma visibilidade sobre seu próprio comportamento:
- Quantos webhooks chegaram? Quantos foram filtrados?
- Quanto tempo demora uma análise (LLM local pode levar 10–30 s)?
- Quantas tool calls o LLM emitiu por rodada?
- As notificações Teams estão chegando ou falhando silenciosamente?

## Solução

Adicionado endpoint `GET /metrics` (formato Prometheus text/plain) e instrumentação interna com `prometheus-client`.

## O que foi implementado

### `agent/metrics.py`
Ponto único de definição de todas as métricas:

| Métrica | Tipo | Labels | Descrição |
|---|---|---|---|
| `aiops_webhooks_total` | Counter | `status` (success/invalid_json/empty) | Payloads recebidos |
| `aiops_alerts_processed_total` | Counter | `alertname`, `severity` | Alertas analisados pelo agente |
| `aiops_alerts_filtered_total` | Counter | — | Alertas ignorados (fora do escopo Camunda) |
| `aiops_analysis_duration_seconds` | Histogram | — | Duração do ciclo run_agent (buckets: 1–120 s) |
| `aiops_llm_tool_calls_total` | Counter | `tool_name` | Chamadas de ferramentas emitidas pelo LLM |
| `aiops_teams_notifications_total` | Counter | `success` (true/false) | Notificações enviadas ao Teams |

### Instrumentação

- `webhook_receiver.py` — conta webhooks, alertas filtrados/processados, duração da análise (`with ANALYSIS_DURATION.time():`), resultado da notificação
- `reactive_agent.py` — conta cada tool call com o nome da ferramenta
- Endpoint `GET /metrics` retorna `generate_latest()` com `Content-Type: text/plain; version=0.0.4`

### Dashboard Grafana

`dashboards/camunda-aiops-agent.json` — 3 seções:
1. **Webhooks & Alertas** — stats de totais + taxa de webhooks por status
2. **Desempenho da Análise** — p50/p90/p99 da duração + tool calls por ferramenta
3. **Notificações Teams** — stats de sucesso/falha + taxa em série temporal

Para importar:
```bash
# Com Kind rodando e port-forward do Grafana ativo:
GRAFANA_PASS=$(kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d)

curl -s -X POST "http://admin:${GRAFANA_PASS}@localhost:3000/api/dashboards/import" \
  -H "Content-Type: application/json" \
  -d "{\"dashboard\": $(cat dashboards/camunda-aiops-agent.json), \"overwrite\": true, \"folderId\": 0}"
```

## Decisões técnicas

**`prometheus-client` vs OpenTelemetry**: escolhido `prometheus-client` por ser mais simples (sem collector/exporter/OTLP pipeline) e por já termos Prometheus no stack. OTel seria melhor para traces distribuídos — candidato à Etapa 12.

**`with ANALYSIS_DURATION.time():`**: uso do context manager em vez de `time.perf_counter()` manual — mais idiomático e à prova de exceções (o observe acontece mesmo se `run_agent` lançar).

**Métricas em `metrics.py` separado**: evita importação circular entre `webhook_receiver` ↔ `reactive_agent` ↔ `teams_notifier`. Todos importam de `metrics.py`, que não importa nenhum módulo do agente.

## Cobertura de testes

- `tests/unit/test_metrics.py` — 9 testes: tipos, labels, buckets, registro no REGISTRY
- `tests/unit/test_webhook_receiver.py` — 3 testes novos: endpoint `/metrics` (status 200, content-type, presença das métricas)
- Cobertura total: **100%** (108 testes)
