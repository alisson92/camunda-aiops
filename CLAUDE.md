# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## O que é este projeto

Lab de forecasting de métricas no Grafana usando **PromQL puro** (sem plugin pago), aplicado ao stack **Camunda 8.9 Self-Managed** rodando em Kind local. O objetivo é explorar `predict_linear`, `double_exponential_smoothing`, `avg_over_time` e `deriv` para antecipar problemas de capacidade antes de chegarem à produção EKS.

Ambiente alvo: Kind local (`kind-camunda-platform-local`) com `kube-prometheus-stack` instalado.

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

## Comandos principais

```bash
# Inspecionar quais métricas estão sendo coletadas
./scripts/check-metrics.sh

# Importar o dashboard (senha via env var, nunca hardcoded)
GRAFANA_PASS=<senha> ./scripts/import-dashboard.sh

# Gerar carga sintética com sazonalidade (verifica contexto Kind automaticamente)
./scripts/load-generator.sh --duration 30 --intensity medium
# Intensidades: low | medium | high
# --dry-run para ver o que seria feito sem executar

# Iniciar o agente (webhook receiver)
make run

# Smoke test de notificações Teams
make smoke
```

Dashboard após import: `http://localhost:3000/d/camunda-local-forecasting/`

## Arquitetura

```
agent/            Pacote Python do agente AIOps (config, tools, notifier, webhook)
prompts/          System prompts versionados (v1, v2, ...) + GUIDELINES.md
scripts/          Scripts operacionais: check-metrics, load-generator, import-dashboard
dashboards/       camunda-forecasting.json — 11 painéis divididos em 2 seções
tests/            Testes e smoke tests; fixtures em tests/fixtures/
docs/             Documentação: etapas, fixes, evolução do projeto
```

O dashboard tem duas seções:
- **Infra K8s** — CPU, memória, pods por namespace usando cAdvisor + kube-state-metrics
- **Zeebe/Camunda** — backpressure, latência p99, RocksDB, JVM heap

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

`holt_winters()` foi removido no Prometheus v3.x. Substituto direto: `double_exponential_smoothing()` com os mesmos parâmetros.

## Cuidados importantes

- `load-generator.sh` bloqueia execução se o contexto kubectl não for `kind-*` — proteção contra rodar em produção EKS acidentalmente.
- O script usa `trap cleanup EXIT INT TERM` para deletar o namespace `load-test` ao sair (Ctrl+C ou fim da duração).
- `import-dashboard.sh` não aceita senha como argumento posicional — usar `GRAFANA_PASS=` env var ou flag `--password`.
- O arquivo `dashboards/camunda-forecasting.json` deve ter o campo `id` ausente ou nulo para que o Grafana trate como criação (não update de um dashboard existente com outro ID).

## Próximo nível planejado

Se `predict_linear` ainda gerar falsos positivos após 4+ semanas de histórico: pipeline Python com Prophet para sazonalidade semanal e feriados brasileiros:

```
Prometheus API → Python (Prophet) → Pushgateway → Prometheus → Grafana
```
