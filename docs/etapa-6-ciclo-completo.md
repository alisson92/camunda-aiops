---
titulo: Etapa 6 — Ciclo completo automatizado (run-cycle-test.sh)
data: 2026-05-24
status: concluída
depende-de: etapa-5-teams-adaptive-card.md
---

# Etapa 6 — Ciclo completo automatizado

## Objetivo

Validar o ciclo AIOps end-to-end em ambiente Kind real: da geração de carga sintética até o
recebimento do card no Teams com análise do LLM — sem intervenção manual em cada passo.

**Problema que esta etapa resolve:**

Até aqui, cada componente estava testado isoladamente. Faltava um script que orquestrasse
o ciclo completo: carga → alerta → webhook → agente → Teams, validando que todos os componentes
conversam entre si no ambiente Kubernetes real.

---

## O que foi implementado

### `scripts/run-cycle-test.sh`

Script de orquestração completo com as seguintes responsabilidades:

1. **Verificação de pré-requisitos** — valida que o contexto kubectl é `kind-*` (aborta com diagnóstico claro se não for)
2. **Port-forwards automáticos** — Prometheus (9090), Grafana (3000), Alertmanager (9093), webhook do agente (5001)
3. **Inicialização do agente** — sobe o `webhook_receiver.py` em background
4. **Carga sintética** — executa `load-generator.sh` para pressionar métricas do Zeebe
5. **Validação do alerta** — aguarda o Prometheus disparar a `PrometheusRule` (polling com timeout)
6. **Cleanup** — encerra todos os processos em background via `trap cleanup EXIT INT TERM`

```bash
make cycle-test                         # ciclo completo (carga media, 20min)
make cycle-test-fast                    # sem carga (valida conectividade)
make cycle-test INTENSITY=high DURATION=30
```

---

## Decisões técnicas

### `DEFAULT_KIND_CONTEXT` hardcoded com override via `--context`

**Decisão:** `DEFAULT_KIND_CONTEXT="kind-camunda-platform-local"` definido no topo do script,
sobrescrevível via flag `--context`.

**Por quê não auto-selecionar o contexto ativo?** O contexto ativo pode não ser o correto.
Múltiplos clusters `kind-*` são comuns em ambientes de desenvolvimento. Seleção automática
por prefixo não é determinística — cria risco silencioso de operar no cluster errado.
Falha explícita com diagnóstico ("contexto X não encontrado, clusters kind-* disponíveis: Y, Z")
é preferível a silenciosamente continuar em ambiente incorreto.

**Princípio:** fail fast, fail loud.

### Separação entre `cycle-test` e `cycle-test-fast`

`cycle-test-fast` pula o `load-generator.sh` e valida apenas a conectividade entre componentes
(agent responde no 5001, Prometheus acessível, port-forwards funcionando). Útil quando já há
histórico de métricas no cluster e não se quer aguardar 20+ minutos de carga.

---

## Quando usar

| Situação | Comando |
|---|---|
| Validar ciclo completo antes de demo ao time | `make cycle-test` |
| Verificar conectividade rapidamente | `make cycle-test-fast` |
| Demonstração ao time (sem Kind) | `make demo` ← preferir esta |

> **Nota:** Para apresentações ao time, prefira `make demo` (Etapa 8) — não requer Kind.
> `make cycle-test` é para validação técnica em ambiente Kubernetes real.
