# Changelog

Todas as mudanças notáveis deste projeto são documentadas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versões seguem [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- `tests/test_webhook_receiver.py` — 22 testes unitários para `/health`, `/webhook`, `/silence` (FastAPI TestClient)
- `tests/test_reactive_agent.py` — 12 testes do loop agentic com tool use (mock OpenAI client)
- `tests/test_tools.py` — 15 testes de queries ao Prometheus (mock httpx)
- `tests/test_teams_notifier_unit.py` — 19 testes de helpers puros e montagem do Adaptive Card
- `scripts/run-cycle-test.sh` — ciclo completo automatizado: port-forwards → agente → carga → alerta → cleanup
- `Makefile` targets `cycle-test` e `cycle-test-fast` para acionar o ciclo via `make`
- `.github/workflows/ci.yml` job `shell-lint` — ShellCheck com `severity=warning` via `ludeeus/action-shellcheck@2.0.0`
- `.gitignore` entradas `.coverage` e `htmlcov/`
- `pyproject.toml` — dependência `pytest-cov>=5.0.0`; seções `[tool.coverage.run]` e `[tool.coverage.report]` com `fail_under = 100`
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
