# camunda-aiops

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
camunda-aiops/
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
│   ├── camunda-forecasting-rules.yaml      # PrometheusRules preditivas (IaC)
│   ├── alertmanager-config-camunda.yaml    # CRD AlertmanagerConfig
│   └── alertmanager-webhook-patch.yaml     # values patch para helm upgrade
├── dashboards/
│   └── camunda-forecasting.json  # dashboard Grafana — 11 painéis
├── scripts/
│   ├── run-cycle-test.sh         # ciclo completo automatizado com auto-recuperação
│   ├── check-metrics.sh          # inspeciona métricas no Prometheus
│   ├── load-generator.sh         # gera carga sintética com sazonalidade
│   ├── import-dashboard.sh       # importa o dashboard via API do Grafana
│   └── test-port-metrics.sh      # testa endpoints /actuator/prometheus
├── tests/
│   ├── fixtures/                 # payloads de alerta para testes
│   ├── unit/                     # 88 testes unitários (sem infraestrutura)
│   │   ├── test_config.py        # 6 testes — carregamento do .env
│   │   ├── test_webhook_receiver.py  # 22 testes — endpoints FastAPI
│   │   ├── test_reactive_agent.py    # 12 testes — loop agentic com tool use
│   │   ├── test_tools.py             # 22 testes — queries Prometheus + _resolve_ts
│   │   ├── test_teams_notifier_unit.py  # 19 testes — Adaptive Card e helpers
│   │   └── test_alert_fixtures.py    # 7 testes — estrutura dos fixtures JSON
│   ├── test_teams_notifier.py    # smoke test de notificações Teams (requer .env)
│   ├── integration/              # testes contra Prometheus real (Testcontainers)
│   └── e2e/                      # ciclo completo: webhook → agente → LLM → Teams
├── docs/                         # documentação por etapa e decisões técnicas
├── .env.example                  # template de variáveis de ambiente
├── pyproject.toml                # metadados e dependências do projeto
└── Makefile                      # task runner (.DEFAULT_GOAL = help)
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

## Demo ao time

O script `demo.sh` é totalmente autossuficiente: inicia o Ollama e o agente automaticamente, executa os cenários e encerra tudo ao final. Não requer o cluster Kind, nem abrir múltiplos terminais.

**Pré-requisito único:** `agent/.env` com `TEAMS_WEBHOOK_URL` configurada.

```bash
# Ciclo completo: 4 cenários em sequência — um único comando
make demo

# Um cenário específico
make demo-backpressure   # critical — maior impacto visual
make demo-zeebe          # warning — heap JVM crescendo
make demo-resolved       # resolved — lifecycle completo

# Ensaiar sem enviar nada
./scripts/demo.sh --dry-run

# Ver cenários disponíveis
./scripts/demo.sh --list
```

Cada cenário envia o payload ao webhook, aguarda o LLM processar e exibe os primeiros caracteres da análise no terminal. O card completo chega no Microsoft Teams.

> **`demo.sh` vs `run-cycle-test.sh`:** os dois scripts têm propósitos complementares, não redundantes.
> `demo.sh` valida **o agente** — dado um alerta qualquer, o LLM analisa e o Teams recebe o card. Não precisa de Kind.
> `run-cycle-test.sh` valida **a pipeline de infraestrutura** — PrometheusRule dispara, Alertmanager roteia, webhook recebe. Requer Kind ativo.
> Use `demo.sh` para apresentações e ensaios; use `run-cycle-test.sh` para validar que o cluster está configurado corretamente.

---

## Ciclo completo automatizado

O script `run-cycle-test.sh` automatiza o ciclo completo de validação do lab em um único comando:

```bash
# Ciclo completo (port-forwards → agente → carga → monitoramento → cleanup)
make cycle-test

# Com parâmetros customizados
make cycle-test INTENSITY=high DURATION=30

# Validação rápida de conectividade (sem carga sintética)
make cycle-test-fast

# Com contexto Kind explícito (override do padrão)
make cycle-test CONTEXT=kind-meu-cluster
```

O script usa `DEFAULT_KIND_CONTEXT="kind-camunda-platform-local"` como padrão determinístico.
Se o contexto não existir no kubeconfig, o script aborta com diagnóstico claro — lista os
contextos `kind-*` disponíveis e exibe o comando para criar o cluster esperado.

---

## Testes e cobertura

```bash
# Testes unitários com cobertura (sem infraestrutura necessária)
make test

# Testes de integração — Prometheus real via Testcontainers (requer Docker)
make test-integration

# Testes E2E — ciclo completo: Prometheus real + LLM/Teams mock HTTP (requer Docker)
make test-e2e

# Smoke test (requer agent/.env configurado)
make smoke
```

| Suíte | Testes | Infraestrutura | Cobertura |
|---|---|---|---|
| Unitários | 88 | Nenhuma | 100% (`fail_under = 100`) |
| Integração | 7 | Docker — Prometheus real (Testcontainers) | — |
| E2E | 3 | Docker — Prometheus real + LLM/Teams mock HTTP | — |

**Estratégia de isolamento:**
- **Unitários:** todas as dependências externas mockadas em nível Python — rodam em qualquer ambiente sem infraestrutura
- **Integração:** `tools.py` testado contra Prometheus HTTP API real — valida compatibilidade com respostas reais
- **E2E:** ciclo completo `webhook → agente → Prometheus → LLM → Teams` com zero mocks em nível de função Python; apenas Ollama e Teams interceptados na camada HTTP via `pytest-httpserver`

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
make run              # inicia o agente na porta 5001
make test             # roda pytest (88 testes unitários + cobertura 100%)
make smoke            # envia todos os cenários de teste para o Teams
make smoke-critical   # envia só o critical
make lint             # valida estilo com ruff
make cycle-test       # ciclo completo automatizado
make cycle-test-fast  # ciclo sem carga sintética (validação rápida)
make help             # lista todos os targets disponíveis
```

---

## Princípios de arquitetura

O projeto segue uma **pipeline reativa orientada a eventos**, não polling. Cada componente
tem uma única responsabilidade e se comunica via interfaces bem definidas:

| Componente | Responsabilidade | Interface |
|---|---|---|
| `PrometheusRule` CRD | Define thresholds preditivos como IaC | Kubernetes API |
| Alertmanager | Roteamento e deduplicação de alertas | `webhook_configs` |
| `webhook_receiver` | Recebe eventos e aciona o agente | `POST /webhook` (HTTP) |
| `reactive_agent` | Loop agentic: análise + tool use | OpenAI-compatible API |
| `tools` | Queries ao Prometheus | Prometheus HTTP API |
| `teams_notifier` | Formatação e entrega da notificação | Microsoft Teams Webhook |

**Vendor neutrality:** O SDK `openai` é usado com `base_url` apontando para o Ollama local.
Trocar de LLM (Ollama → GPT-4 → Claude API) exige mudar apenas duas variáveis de ambiente.

---

## Documentação

| Documento | Conteúdo |
|---|---|
| `docs/projeto-evolucao.md` | Decisões técnicas, ADRs simplificados e trade-offs |
| `docs/etapa-1-prometheus-rules.md` | PrometheusRules preditivas |
| `docs/etapa-2-grafana-mcp-server.md` | Grafana MCP Server + Claude Code |
| `docs/etapa-3-agente-reativo-claude-api.md` | Agente com Claude API (histórico) |
| `docs/etapa-4-ollama-local-llm.md` | Migração para Ollama local |
| `docs/fix-*.md` | Investigações e fixes documentados |
| `prompts/GUIDELINES.md` | Como versionar e testar prompts |

---

## CI/CD

5 jobs a cada push/PR — sequência garante que cada camada passa antes da próxima iniciar:

| Job | O que valida | Depende de |
|---|---|---|
| `python` | 88 testes unitários, cobertura 100%, `ruff` | — |
| `yaml-lint` | `yamllint` em manifestos Kubernetes | — |
| `shell-lint` | ShellCheck `severity=warning` em scripts | — |
| `integration` | 7 testes — `tools.py` contra Prometheus real (Testcontainers) | `python` |
| `e2e` | 3 testes — ciclo completo com Prometheus real + mock HTTP | `integration` |

---

## Referências

- [Prometheus — Query functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)
- [Camunda 8 — Métricas do Zeebe](https://docs.camunda.io/docs/self-managed/zeebe-deployment/operations/metrics/)
- [Ollama — OpenAI compatibility](https://ollama.com/blog/openai-compatibility)
- [Microsoft Adaptive Cards](https://adaptivecards.io/)
- [The Twelve-Factor App](https://12factor.net/)
- [ShellCheck](https://www.shellcheck.net/)
- [Documenting Architecture Decisions — Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
