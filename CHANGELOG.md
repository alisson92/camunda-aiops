# Changelog

Todas as mudanças notáveis deste projeto são documentadas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versões seguem [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added
- `agent/config.py` — ponto único de configuração; carrega `.env` e expõe constantes tipadas
- `agent/__init__.py` — torna `agent/` um pacote Python formal
- `tests/` — diretório de testes na raiz (pytest convention)
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
