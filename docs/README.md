# Documentação — camunda-aiops

Índice de navegação da pasta `docs/`. Para contexto geral do projeto, consulte o
[README principal](../README.md).

---

## Etapas de desenvolvimento

Cada etapa documenta o que foi implementado, as decisões técnicas e como usar.

| Arquivo | Conteúdo |
|---|---|
| [etapa-1-prometheus-rules.md](etapa-1-prometheus-rules.md) | PrometheusRules preditivas com `predict_linear`, `deriv` e `double_exponential_smoothing` |
| [etapa-2-grafana-mcp-server.md](etapa-2-grafana-mcp-server.md) | Integração Claude Code com Grafana via MCP Server |
| [etapa-3-agente-reativo-claude-api.md](etapa-3-agente-reativo-claude-api.md) | Agente reativo com Claude API — histórico (migrado para Ollama na Etapa 4) |
| [etapa-4-ollama-local-llm.md](etapa-4-ollama-local-llm.md) | Migração do LLM para Ollama local — ciclo 100% air-gapped |
| [etapa-6-ciclo-completo.md](etapa-6-ciclo-completo.md) | Ciclo completo automatizado com `run-cycle-test.sh` |
| [etapa-7-qualidade-ci.md](etapa-7-qualidade-ci.md) | 100% de cobertura, testes integração/E2E, pipeline CI com 5 jobs |
| [etapa-8-demo-mode.md](etapa-8-demo-mode.md) | Demo autossuficiente (`make demo`) sem Kind |
| [etapa-9-system-prompt-v2.md](etapa-9-system-prompt-v2.md) | System prompt v2 — URGÊNCIA, formato resolved, contexto Camunda 8 |
| [etapa-10-observabilidade-agente.md](etapa-10-observabilidade-agente.md) | Métricas Prometheus do próprio agente (`GET /metrics`) e dashboard Grafana |
| [etapa-11-runbook-generation.md](etapa-11-runbook-generation.md) | Geração automática de runbooks via LLM após cada análise |
| [etapa-12-rag-conhecimento.md](etapa-12-rag-conhecimento.md) | Few-shot + RAG com base de conhecimento local (`KnowledgeBase`) |

---

## Revisões de qualidade

Revisões periódicas aplicadas ao projeto antes de apresentação ao time.

| Arquivo | Conteúdo |
|---|---|
| [revisao-A-limpeza-repositorio.md](revisao-A-limpeza-repositorio.md) | Limpeza de artefatos, reorganização de arquivos, docs faltantes |
| [revisao-B-hardcoded-configurabilidade.md](revisao-B-hardcoded-configurabilidade.md) | Auditoria e correção de valores hardcoded — `ALERT_FILTER_KEYWORDS` |
| [revisao-C-organizacao-estrutura.md](revisao-C-organizacao-estrutura.md) | Estrutura do repositório, CI, pyproject.toml, índices de navegação |
| [revisao-D-contributing.md](revisao-D-contributing.md) | Criação do CONTRIBUTING.md — padrões, fluxo de contribuição, convenções |
| [revisao-E-aiops-best-practices.md](revisao-E-aiops-best-practices.md) | Auditoria AIOps: correlation ID, `aiops_llm_rounds_used`, runbook reload, `/health` enriquecido |
| [revisao-F-alerting.md](revisao-F-alerting.md) | Alerting strategy: 2 novos alertas (Gateway latency, PVC storage), label `component`, `runbook_url` por alerta |
| [revisao-F-grafana-migration.md](revisao-F-grafana-migration.md) | Migração de 15 alertas Grafana para PrometheusRule IaC — 5 arquivos, decisões de split de severidade |

---

## Fixes e investigações

Registros de bugs investigados e corrigidos em ambiente real.

| Arquivo | Conteúdo |
|---|---|
| [fix-alertmanager-helm-resiliencia.md](fix-alertmanager-helm-resiliencia.md) | Fix do Alertmanager via `helm upgrade` (IP do webhook) |
| [fix-zeebe-backpressure-investigacao.md](fix-zeebe-backpressure-investigacao.md) | Investigação do alerta `ZeebeBackpressureGrowing` em ambiente real |

---

## ADR Log — decisões arquiteturais

| Arquivo | Conteúdo |
|---|---|
| [projeto-evolucao.md](projeto-evolucao.md) | Registro de ADRs: por que cada decisão técnica foi tomada (complementa o CHANGELOG) |
