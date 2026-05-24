# grafana-ml-lab

Lab de AIOps para Kubernetes + Camunda 8.9 Self-Managed.

Explora o ciclo completo: forecasting preditivo com PromQL → alertas → agente reativo com LLM local → notificação no Microsoft Teams. Sem plugins pagos, sem dependências externas — 100% local e air-gapped.

---

## Visão geral

```
Prometheus (predict_linear / deriv)
    ↓ alerta preditivo
Alertmanager
    ↓ webhook
FastAPI (webhook_receiver)
    ↓ aciona
Agente Python (Ollama + qwen2.5:7b)
    ↓ consulta métricas via PromQL
    ↓ analisa causa raiz
Microsoft Teams (Adaptive Card)
```

---

## Estrutura do projeto

```
grafana-ml-lab/
├── agent/                        # pacote Python do agente AIOps
│   ├── config.py                 # ponto único de configuração (env vars)
│   ├── reactive_agent.py         # loop agentic com tool use (Ollama)
│   ├── tools.py                  # ferramentas: queries Prometheus HTTP API
│   ├── teams_notifier.py         # notificações via Adaptive Card v1.2
│   ├── webhook_receiver.py       # FastAPI — recebe payloads do Alertmanager
│   └── prompts.py                # loader de prompts do diretório prompts/
├── prompts/
│   ├── system-prompt-v1.md       # system prompt do agente (versionado)
│   └── GUIDELINES.md             # regras de versionamento de prompts
├── alerting/
│   ├── camunda-forecasting-rules.yaml      # PrometheusRules preditivas
│   ├── alertmanager-config-camunda.yaml    # CRD AlertmanagerConfig
│   └── alertmanager-webhook-patch.yaml     # values patch para helm upgrade
├── dashboards/
│   └── camunda-forecasting.json  # dashboard Grafana — 11 painéis
├── scripts/
│   ├── check-metrics.sh          # inspeciona métricas no Prometheus
│   ├── load-generator.sh         # gera carga sintética com sazonalidade
│   ├── import-dashboard.sh       # importa o dashboard via API do Grafana
│   └── test-port-metrics.sh      # testa endpoints /actuator/prometheus
├── tests/
│   ├── fixtures/                 # payloads de alerta para testes
│   └── test_teams_notifier.py    # smoke test de notificações Teams
├── docs/                         # documentação por etapa e decisões técnicas
├── .env.example                  # template de variáveis de ambiente
├── pyproject.toml                # metadados e dependências do projeto
└── Makefile                      # task runner
```

---

## Pré-requisitos

- Cluster Kind rodando: `kind-camunda-platform-local`
- `kube-prometheus-stack` instalado no namespace `monitoring`
- Ollama instalado localmente com o modelo `qwen2.5:7b` (`ollama pull qwen2.5:7b`)
- Python 3.11+

```bash
# 1. Confirmar contexto Kind (nunca EKS)
kubectl config current-context   # deve retornar kind-*

# 2. ServiceMonitors do Camunda aplicados
kubectl get servicemonitor -n camunda
# Esperado: 6 (zeebe, zeebe-gateway, connectors, identity, optimize, web-modeler-restapi)

# 3. Port-forwards (cada um em terminal separado)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &

# 4. Recuperar senha do Grafana
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d && echo
```

---

## Configuração

```bash
cp .env.example agent/.env
# edite agent/.env com os valores do seu ambiente
```

Variáveis obrigatórias: `TEAMS_WEBHOOK_URL`. As demais têm valores padrão para ambiente local.

---

## Execução

```bash
# Instalar dependências
pip install -e ".[dev]"

# Iniciar o agente (webhook receiver na porta 5001)
make run

# Importar o dashboard no Grafana
GRAFANA_PASS=<senha> ./scripts/import-dashboard.sh

# Aplicar alertas preditivos no cluster
kubectl apply -f alerting/camunda-forecasting-rules.yaml

# Gerar carga sintética para acionar os alertas
./scripts/load-generator.sh --duration 30 --intensity medium

# Smoke test — envia os 4 cenários de alerta para o Teams
make smoke
```

Dashboard: `http://localhost:3000/d/camunda-local-forecasting/`

---

## Alertas preditivos

Três alertas configurados em `alerting/camunda-forecasting-rules.yaml`:

| Alerta | Técnica | Threshold |
|---|---|---|
| `ZeebeMemoryPredictedHigh` | `predict_linear` (30m) | heap G1 Old Gen > 85% do Xmx em 15min |
| `ZeebeBackpressureGrowing` | `deriv` (10m) | derivada > 0.5 req/s por 3min |
| `CamundaNamespaceMemoryPressure` | `predict_linear` (1h) | namespace camunda > 6 GB em 30min |

---

## Notificações Teams

Cards com 4 severidades, cores e emojis distintos:

| Severidade | Status label | Cor | Emoji |
|---|---|---|---|
| `critical` | `FIRING` | Vermelho | 🚨 |
| `warning` | `WARNING` | Amarelo | ⚠️ |
| `info` | `INFO` | Azul | ℹ️ |
| `resolved` | `RESOLVED` | Verde | ✅ |

Cada card inclui: análise do agente (expansível), link para o dashboard, runbook e botão de silence.

---

## Técnicas PromQL de forecasting

| Função | Uso | Regra crítica |
|---|---|---|
| `predict_linear(v[T], t)` | Recursos monotônicos (disco, filas, RocksDB) | Janela/horizonte ≥ 2:1 — janela 30m → horizonte máx. 15m |
| `double_exponential_smoothing(v, sf, tf)` | Memória Java com GC, métricas oscilatórias | Requer feature flag `promql-experimental-functions` (Prometheus v3.x) |
| `avg_over_time(v[T])` | Suavização simples | Funciona em qualquer versão, sem feature flag |
| `deriv(v[T])` | Detectar aceleração antes do pico | Positivo = crescendo |

> `holt_winters()` foi removido no Prometheus v3.x. Substituto: `double_exponential_smoothing()`.

---

## Comandos úteis

```bash
make run          # inicia o agente na porta 5001
make test         # roda pytest
make smoke        # envia todos os cenários de teste para o Teams
make smoke-critical   # envia só o critical
make lint         # valida estilo com ruff
make help         # lista todos os targets
```

---

## Documentação

| Documento | Conteúdo |
|---|---|
| `docs/etapa-1-prometheus-rules.md` | PrometheusRules preditivas |
| `docs/etapa-2-grafana-mcp-server.md` | Grafana MCP Server + Claude Code |
| `docs/etapa-3-agente-reativo-claude-api.md` | Agente com Claude API (histórico) |
| `docs/etapa-4-ollama-local-llm.md` | Migração para Ollama local |
| `docs/projeto-evolucao.md` | Decisões técnicas e refatorações |
| `docs/fix-*.md` | Investigações e fixes documentados |
| `prompts/GUIDELINES.md` | Como versionar e testar prompts |

---

## Referências

- [Prometheus — Query functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)
- [Camunda 8 — Métricas do Zeebe](https://docs.camunda.io/docs/self-managed/zeebe-deployment/operations/metrics/)
- [Ollama — OpenAI compatibility](https://ollama.com/blog/openai-compatibility)
- [Microsoft Adaptive Cards](https://adaptivecards.io/)
- [The Twelve-Factor App](https://12factor.net/)
