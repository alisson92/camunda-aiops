# Changelog

Todas as mudanças notáveis deste projeto são documentadas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versões seguem [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- `agent/metrics.py` — ponto único de definição de métricas Prometheus: `aiops_webhooks_total`, `aiops_alerts_processed_total`, `aiops_alerts_filtered_total`, `aiops_analysis_duration_seconds`, `aiops_llm_tool_calls_total`, `aiops_teams_notifications_total`
- `GET /metrics` em `webhook_receiver.py` — endpoint Prometheus text/plain via `generate_latest()`
- `dashboards/camunda-aiops-agent.json` — dashboard Grafana com 3 seções: Webhooks & Alertas, Desempenho da Análise (p50/p90/p99), Notificações Teams
- `tests/unit/test_metrics.py` — 9 testes de definição e registro das métricas
- `docs/etapa-10-observabilidade-agente.md` — documentação da etapa: problema, solução, decisões técnicas, instruções de import do dashboard
- `pyproject.toml` — dependência `prometheus-client>=0.20.0,<1.0.0`

### Changed
- `agent/webhook_receiver.py` — instrumentado com `WEBHOOKS_RECEIVED`, `ALERTS_FILTERED`, `ALERTS_PROCESSED`, `ANALYSIS_DURATION.time()`, `TEAMS_NOTIFICATIONS`; adicionado endpoint `GET /metrics`
- `agent/reactive_agent.py` — instrumentado com `LLM_TOOL_CALLS` por nome de ferramenta
- `tests/unit/test_webhook_receiver.py` — adicionados 4 testes: `/metrics` (status, content-type, métricas presentes) e branch `success=false` de notificação

### Added
- `prompts/system-prompt-v2.md` — adiciona campo URGÊNCIA (Imediata/Alta/Moderada) ao formato firing; formato dedicado para `resolved` (RESOLUÇÃO/CONFIRMAÇÃO/PRÓXIMO_PASSO); contexto dos 6 componentes Camunda 8; dois exemplos de output (critical + resolved)
- `docs/etapa-9-system-prompt-v2.md` — documentação da etapa: problema, decisões, comparação v1 vs v2, rollback

### Changed
- `agent/config.py` — `_BRTFormatter` força logs em horário de Brasília (UTC-3); `setup_logging` usa handler com formatter explícito em vez de `basicConfig` com `format=`
- `tests/unit/test_config.py` — 2 testes para `_BRTFormatter`: offset UTC-3 e formato padrão `YYYY-MM-DD HH:MM:SS`
- `agent/prompts.py` — aponta para `system-prompt-v2.md` (era v1)
- `prompts/GUIDELINES.md` — atualiza comando de teste para `make demo-backpressure` e `make demo-resolved`; registra v2 no histórico de versões
- `scripts/demo.sh` — injeta timestamp atual (UTC) no payload antes de enviar — corrige horário exibido no card Teams (antes mostrava hora estática do fixture convertida para BRT): inicia Ollama e o agente automaticamente se necessário, injeta os 4 cenários, encerra tudo via `trap`; suporta `--scenario`, `--dry-run`, `--list`, `--delay`, `--webhook-url`
- `tests/fixtures/zeebe-backpressure-alert.json` — payload `ZeebeBackpressureGrowing` (critical) para ciclo de demo
- `tests/fixtures/zeebe-resolved.json` — payload `ZeebeMemoryPredictedHigh` (resolved) para demonstrar lifecycle completo
- `Makefile` targets `demo` e `demo-%` (demo-zeebe, demo-namespace, demo-backpressure, demo-resolved)
- `docs/etapa-8-demo-mode.md` — documentação da etapa: problema, solução, decisões técnicas e roteiro de uso
- `CLAUDE.md` — regra de documentação obrigatória ao concluir etapas; roadmap numerado; roteiro da demo ao time
- `README.md` — nota explicando a diferença entre `demo.sh` (valida o agente, sem Kind) e `run-cycle-test.sh` (valida a pipeline K8s, requer Kind)
- `tests/e2e/test_alert_cycle.py` — 3 testes E2E do ciclo completo: webhook → agente → Prometheus real → LLM mock HTTP → Teams mock HTTP
- `tests/e2e/conftest.py` — fixtures E2E: Prometheus (Testcontainers) + servidor HTTP mock unificado (pytest-httpserver)
- `tests/integration/test_tools_integration.py` — 7 testes de integração de `tools.py` contra Prometheus real (Testcontainers)
- `tests/integration/conftest.py` — fixture Prometheus com espera pelo primeiro self-scrape
- `tests/test_webhook_receiver.py` — 22 testes unitários para `/health`, `/webhook`, `/silence` (FastAPI TestClient)
- `tests/test_reactive_agent.py` — 12 testes do loop agentic com tool use (mock OpenAI client)
- `tests/test_tools.py` — 15 testes de queries ao Prometheus (mock httpx)
- `tests/test_teams_notifier_unit.py` — 19 testes de helpers puros e montagem do Adaptive Card
- `scripts/run-cycle-test.sh` — ciclo completo automatizado: port-forwards → agente → carga → alerta → cleanup
- `Makefile` targets `cycle-test`, `cycle-test-fast`, `test-integration`, `test-e2e`
- `.github/workflows/ci.yml` jobs `integration` (needs: python) e `e2e` (needs: integration)
- `.github/workflows/ci.yml` job `shell-lint` — ShellCheck com `severity=warning` via `ludeeus/action-shellcheck@2.0.0`
- `.gitignore` entradas `.coverage` e `htmlcov/`
- `pyproject.toml` — dependências `pytest-cov>=5.0.0`, `testcontainers>=4.7.0`, `pytest-httpserver>=1.0.0`; `fail_under = 100`; markers `integration` e `e2e`
- `agent/config.py` — ponto único de configuração; carrega `.env` e expõe constantes tipadas
- `agent/__init__.py` — torna `agent/` um pacote Python formal
- `tests/fixtures/` — fixtures de payload do Alertmanager (movidas de `agent/test-fixtures/`)
- `tests/test_teams_notifier.py` — smoke test de notificações Teams (movido de `agent/`)
- `pyproject.toml` — substitui `requirements.txt`; define metadados, deps e config do pytest
- `Makefile` — task runner com targets `run`, `test`, `smoke`, `lint`
- `.env.example` — template público de variáveis de ambiente
- `CHANGELOG.md` — este arquivo
- `docs/projeto-evolucao.md` — diário de decisões técnicas do projeto
- `prompts/GUIDELINES.md` — diretrizes de versionamento de prompts
- `prompts/system-prompt-v1.md` — system prompt base do agente AIOps

### Changed
- `Makefile` — `.DEFAULT_GOAL := help`; `make` sem argumentos exibe targets disponíveis
- `.github/workflows/ci.yml` — step `pytest` atualizado para `pytest --cov --cov-report=term-missing`
- `agent/tools.py` — adicionada `_resolve_ts()`: converte `now`, `now-30m`, `now-1h` para Unix timestamp antes de chamar `/api/v1/query_range` (bug: Prometheus rejeita timestamps relativos neste endpoint)
- `agent/webhook_receiver.py` — `datetime.utcnow()` substituído por `datetime.now(timezone.utc)` (deprecation fix)
- `scripts/run-cycle-test.sh` — `DEFAULT_KIND_CONTEXT="kind-camunda-platform-local"` hardcoded; falha explícita com diagnóstico se o contexto não existir
- `scripts/load-generator.sh` — removidas variáveis não utilizadas (`ZEEBE_REST_URL`, `HTTP_PID_1/2`, `SCALE_PID`)
- `scripts/check-metrics.sh` — variável `description` usada na saída de log (SC2034)
- `scripts/test-port-metrics.sh` — adicionado shebang `#!/usr/bin/env bash` (SC2148)
- `agent/tools.py` — `PROMETHEUS_URL` agora vem de `config.py` (era hardcoded)
- `agent/reactive_agent.py` — carregamento de `.env` centralizado em `config.py`; logging estruturado
- `agent/teams_notifier.py` — variáveis de ambiente via `config.py`; logging estruturado
- `agent/webhook_receiver.py` — `ALERTMANAGER_URL` via `config.py`; logging estruturado
- `agent/prompts.py` — loader limpo sem lógica de configuração
- Scripts renomeados: `01-check-metrics.sh` → `check-metrics.sh`, `02-load-generator.sh` → `load-generator.sh`, `03-import-dashboard.sh` → `import-dashboard.sh`

### Removed
- `requirements.txt` — substituído por `pyproject.toml`
- `agent/test-fixtures/` — movido para `tests/fixtures/`
- `agent/test/` — screenshots movidos para `tests/fixtures/`
- `agent/test-teams-notification.py` — renomeado para `tests/test_teams_notifier.py`

---

## [0.4.0] — 2026-05-22

### Added
- Notificação Microsoft Teams via Adaptive Card v1.2
- Botões de ação no card: "Ver análise", "Dashboard", "Runbook", "Silence 1h"
- Endpoint `GET /silence` no webhook receiver para criar silences via Alertmanager API
- Suporte a 4 severidades com cores e emojis distintos: critical 🚨, warning ⚠️, info ℹ️, resolved ✅

## [0.3.0] — 2026-05-22

### Changed
- Migração do LLM de Anthropic Cloud para Ollama local (`qwen2.5:7b`)
- Zero dependência externa — ciclo AIOps 100% air-gapped
- SDK migrado: `anthropic` → `openai` (compat Ollama)

## [0.2.0] — 2026-05-21

### Added
- Agente reativo com Claude API + webhook Alertmanager (Etapa 3)
- Grafana MCP Server conectado ao Claude Code (Etapa 2)
- Fix sustentável do Alertmanager via `helm upgrade` (IP: `172.18.0.1`)

## [0.1.0] — 2026-05-20

### Added
- PrometheusRules preditivas para Zeebe/Camunda (Etapa 1)
- Dashboard de forecasting com 11 painéis (PromQL: `predict_linear`, `deriv`, `avg_over_time`)
- Scripts de setup: `check-metrics`, `load-generator`, `import-dashboard`
- Publicação no GitHub (repositório privado)
