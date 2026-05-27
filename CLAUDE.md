# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é este projeto

Lab de AIOps aplicado ao stack **Camunda 8.9 Self-Managed** rodando em Kind local. Explora o ciclo completo: forecasting preditivo com PromQL → alertas → agente reativo com LLM local (Ollama) → notificação no Microsoft Teams. Sem plugins pagos, sem dependências externas — 100% local e air-gapped.

**Objetivo:** demo ao time mostrando o ciclo completo funcionando ao vivo.

Ambiente alvo: Kind local (`kind-camunda-platform-local`) com `kube-prometheus-stack` instalado.

---

## Regra de documentação — obrigatória ao concluir qualquer etapa

Ao finalizar qualquer etapa de desenvolvimento (nova feature, fix, refactor, test), **sempre** executar:

1. **`CHANGELOG.md`** — adicionar entrada em `[Unreleased]` com o que foi adicionado/alterado/removido
2. **`README.md`** — atualizar seções afetadas (estrutura de arquivos, tabelas de testes, comandos)
3. **`docs/`** — criar ou atualizar o documento da etapa (`docs/etapa-N-<nome>.md`) com:
   - O que foi implementado e por quê
   - Decisões técnicas e trade-offs
   - Como usar / exemplos
4. **`CLAUDE.md`** (este arquivo) — atualizar os comandos principais e o roadmap se necessário
5. **Memória interna** — atualizar `/home/alisson/.claude/projects/.../memory/project_historico_evolucao.md`

Nunca fechar uma etapa sem esses cinco pontos. Isso garante que a próxima sessão começa com contexto completo.

---

## Pré-requisitos para qualquer operação

```bash
# 1. Confirmar contexto Kind (nunca EKS)
kubectl config current-context  # deve retornar kind-*

# 2. ServiceMonitors do Camunda aplicados
kubectl get servicemonitor -n camunda
# 6 esperados: zeebe, zeebe-gateway, connectors, identity, optimize, web-modeler-restapi
# Se ausentes:
kubectl apply -f ~/personal/projects/camunda-kind/monitoring/camunda-servicemonitors.yaml

# 3. Port-forwards (cada um em terminal separado)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &

# 4. Recuperar senha do Grafana
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d && echo
```

---

## Comandos principais

```bash
# ── Deploy no Kind (fluxo completo) ────────────────────────────────────────────
make build                       # build da imagem Docker
make kind-load                   # carrega a imagem no cluster Kind (sem registry)
# Preencher deploy/secret.yaml com valores reais antes de aplicar:
kubectl apply -f deploy/secret.yaml -n camunda
make k8s-apply                   # aplica PVC, Deployment, Service e CronJob
make k8s-status                  # verifica Pod, Service, PVC e CronJob
make k8s-logs                    # acompanha logs em tempo real
make k8s-delete                  # remove Deployment/Service/CronJob (mantém PVC e Secret)

# WSL2+Kind: NodePort não é acessível via localhost — use o IP do nó:
#   NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
#   Webhook: http://$NODE_IP:30501/webhook  (configurar no Alertmanager)
#   Health:  http://$NODE_IP:30501/health

# ── Modo desenvolvimento local (sem Kind) ──────────────────────────────────────
# Iniciar o agente (webhook receiver na porta 5001)
make run

# Demo ao time: autossuficiente — gera fixtures + inicia Ollama + agente, executa TODOS os alertas
# Pré-requisito único: agent/.env com TEAMS_WEBHOOK_URL
make demo                        # ciclo completo (todos os *-alert.json)
make demo-zeebe                  # apenas ZeebeMemoryPredictedHigh
make demo-backpressure           # ZeebeBackpressureGrowing (critical — maior impacto)
make demo-resolved               # alerta encerrado (lifecycle completo)

# Testes
make test                        # 223 testes unitários + cobertura 100%
make test-integration            # Prometheus real via Testcontainers
make test-e2e                    # ciclo completo com mock HTTP

# Fixtures (geração automática a partir de alerting/*.yaml)
make generate-fixtures           # gera tests/fixtures/<kebab>-alert.json para cada alerta

# Smoke test (requer agent/.env com TEAMS_WEBHOOK_URL)
make smoke
make smoke-critical

# Qualidade
make lint

# Kubernetes / Observabilidade (requer Kind)
make port-forward
make check-metrics
make import-dashboard
make load                        # carga sintética (DURATION=30 INTENSITY=medium)
make cycle-test                  # ciclo completo com Kind ativo
```

Dashboard após import: `http://localhost:3000/d/camunda-local-forecasting/`

---

## Arquitetura

```
agent/            Pacote Python do agente AIOps (config, tools, notifier, webhook, metrics)
prompts/          System prompts versionados (v1, v2, ...) + GUIDELINES.md
deploy/           Manifests Kubernetes: pvc.yaml, deployment.yaml, service.yaml, cronjob.yaml, secret.yaml, kustomization.yaml
scripts/          Scripts operacionais: generate-fixtures, demo, check-metrics, load-generator, import-dashboard
dashboards/       camunda-forecasting.json (forecasting) + camunda-aiops-agent.json (observabilidade do agente)
alerting/         7 PrometheusRule CRDs: Camunda, Elasticsearch, Kubernetes nós/pods
tests/
  unit/           223 testes unitários (sem infraestrutura)
  integration/    7 testes — Prometheus real via Testcontainers
  e2e/            3 testes — ciclo completo: webhook → agente → Prometheus → LLM → Teams
  fixtures/       24 payloads JSON — 4 curados + 20 gerados por generate-fixtures.py
docs/             Documentação: etapas, fixes, decisões técnicas
Dockerfile        Build da imagem do agente (python:3.11-slim, usuário não-root, porta 5001)
```

**Fluxo do webhook (assíncrono):**
1. `POST /webhook` recebe payload do Alertmanager
2. Para cada alerta: aplica filtro por keywords → verifica deduplicação por fingerprint
3. Alerta novo → `background_tasks.add_task(_process_alert, ...)` + retorna 202 imediatamente
4. Em background: `run_agent` → `generate_runbook` → `send_alert_to_teams`

O dashboard tem duas seções:
- **Infra K8s** — CPU, memória, pods por namespace usando cAdvisor + kube-state-metrics
- **Zeebe/Camunda** — backpressure, latência p99, RocksDB, JVM heap

---

## Técnicas PromQL e regras validadas

| Função | Uso | Regra crítica |
|---|---|---|
| `predict_linear(v[T], t)` | Recursos monotônicos (disco, filas, RocksDB) | Janela/horizonte ≥ 2:1. Janela 30m → horizonte máx. 15m |
| `double_exponential_smoothing(v, sf, tf)` | Memória Java com GC, métricas oscilatórias | Requer feature flag no Prometheus v3.x (ver abaixo) |
| `avg_over_time` | Suavização simples sem flag | Funciona em qualquer versão |
| `deriv(v[T])` | Detectar aceleração antes do pico | Positivo = crescendo |

**Feature flag necessária para `double_exponential_smoothing`** (Prometheus v3.x):
```yaml
# values do kube-prometheus-stack
prometheus:
  prometheusSpec:
    enableFeatures:
      - promql-experimental-functions
```

`holt_winters()` foi removido no Prometheus v3.x. Substituto direto: `double_exponential_smoothing()`.

---

## Cuidados importantes

- `load-generator.sh` bloqueia execução se o contexto kubectl não for `kind-*` — proteção contra rodar em produção EKS acidentalmente.
- O script usa `trap cleanup EXIT INT TERM` para deletar o namespace `load-test` ao sair.
- `import-dashboard.sh` não aceita senha como argumento posicional — usar `GRAFANA_PASS=` env var.
- O arquivo `dashboards/camunda-forecasting.json` deve ter o campo `id` ausente ou nulo para que o Grafana trate como criação.
- `agent/.env` **nunca** deve ser commitado — contém `TEAMS_WEBHOOK_URL` e outros segredos. Usar `.env.example` como template.
- `demo.sh`: o Ollama `qwen2.5:7b` leva 10–30s para processar. `curl --max-time 120` está configurado para dar tempo ao modelo.
- `generate-fixtures.py`: idempotente por nome de arquivo — não sobrescreve fixtures existentes. Expressões Go template são resolvidas com valores padrão por componente (zeebe, elasticsearch, kube).
- `_dedup_cache`: variável module-level em `webhook_receiver.py` — persiste durante toda a vida do processo. Em testes, deve ser limpo via `patch.dict("webhook_receiver._dedup_cache", {}, clear=True)`.
- `DEDUP_TTL_SECONDS`: padrão 300s (5 min). Alertas `resolved` **nunca** são deduplicados — sempre passam.

---

## Roadmap de etapas

| # | Etapa | Status |
|---|---|---|
| 1 | PrometheusRules preditivas | ✅ Concluída |
| 2 | Integração MCP com Grafana | ✅ Concluída |
| 3 | Agente reativo + webhook Alertmanager | ✅ Concluída |
| 4 | Migração para Ollama local (air-gapped) | ✅ Concluída |
| 5 | Notificações Teams com Adaptive Card | ✅ Concluída |
| 6 | Ciclo completo automatizado (`run-cycle-test.sh`) | ✅ Concluída |
| 7 | Qualidade: 100% cobertura, testes integração + E2E, CI 5 jobs | ✅ Concluída |
| 8 | Demo mode (`make demo`) — sem Kind, sem alertas reais | ✅ Concluída |
| 9 | Refinamento do system prompt v2 | ✅ Concluída |
| 10 | Dashboard de observabilidade do próprio agente | ✅ Concluída |
| 11 | Runbook generation automático | ✅ Concluída |
| 12 | Few-shot + RAG com histórico de incidentes | ✅ Concluída |
| 13 | Fixtures dinâmicos, deduplicação por fingerprint e webhook assíncrono | ✅ Concluída |
| 14 | Filtro por label `agentia: true` + notificação direta para demais alertas | ✅ Concluída |
| 15 | Dockerfile + deploy Kubernetes com PVC (Kind local → EKS produção) | ✅ Concluída |
| 16 | Separação deploy/demo: `scripts/deploy.sh`, `make deploy-fast`, cluster-aware `run-cycle-test.sh` | ✅ Concluída |
| 17 | Serialização do `_runbooks` dict em disco (JSON) para sobreviver restart sem PVC | ⏳ Próxima |
| 18 | Pipeline Prophet para sazonalidade | ⏳ Longo prazo |

---

## Roteiro da demo ao time (referência rápida)

1. **Contexto (2 min):** problema — alertas reativos chegam tarde em produção
2. **Forecasting (3 min):** dashboard Grafana com `predict_linear` — "prevemos 15 min antes"
3. **Ciclo ao vivo (5 min):** `make demo` → LLM analisa → card no Teams com análise + botões
4. **Qualidade (2 min):** pipeline CI — "não é lab, é produção-ready"
5. **Próximos passos (2 min):** runbook automático, observabilidade do agente
