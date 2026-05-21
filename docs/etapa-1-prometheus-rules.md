---
titulo: Etapa 1 — Alertas Preditivos com PrometheusRule
data: 2026-05-21
status: concluída
depende-de: baseline do dashboard (camunda-forecasting.json)
---

# Etapa 1 — Alertas Preditivos com PrometheusRule

## Objetivo

Transformar as queries de forecasting que existem no dashboard visual em **alertas reais no Prometheus**, usando o recurso `PrometheusRule` do kube-prometheus-stack.

Até aqui, o `predict_linear` e o `double_exponential_smoothing` são apenas painéis — eles mostram o que pode acontecer, mas não disparam nenhuma notificação. O objetivo desta etapa é fechar esse ciclo: de "visualização preditiva" para "alerta preditivo ativo".

Esta etapa é o desbloqueador das próximas: sem alertas reais, o Grafana MCP Server (Etapa 2) só faz análise passiva, e o agente reativo com Claude API (Etapa 3) não tem gatilho para funcionar.

---

## Pré-requisitos

Antes de começar, validar:

```bash
# 1. Contexto Kind (nunca EKS)
kubectl config current-context
# esperado: kind-camunda-platform-local

# 2. kube-prometheus-stack instalado e operacional
kubectl get pods -n monitoring | grep -E "prometheus|alertmanager"
# esperado: pods Running

# 3. ServiceMonitors do Camunda presentes
kubectl get servicemonitor -n camunda
# esperado: 6 ServiceMonitors (zeebe, zeebe-gateway, connectors, identity, optimize, web-modeler-restapi)

# 4. Port-forwards ativos
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093 &

# 5. Confirmar que as métricas base existem no Prometheus
curl -s 'http://localhost:9090/api/v1/query?query=jvm_memory_used_bytes{namespace="camunda"}' \
  | jq '.data.result | length'
# esperado: > 0
```

---

## O que foi feito

### Decisão de design

O kube-prometheus-stack expõe o CRD `PrometheusRule`, que permite declarar grupos de alertas em YAML e aplicá-los via `kubectl`. O Prometheus operado pelo stack detecta o recurso automaticamente via label selector — não é necessário editar `configmap` nem reiniciar o Prometheus.

**Label obrigatória:** todo `PrometheusRule` precisa ter a label `release: kube-prometheus-stack` para ser descoberto pelo operador.

### Alertas implementados

Três alertas foram criados, cada um cobrindo uma técnica PromQL diferente do dashboard:

| Alerta | Técnica | Recurso monitorado | Horizonte |
|---|---|---|---|
| `ZeebeMemoryPredictedHigh` | `predict_linear` | JVM heap do Zeebe | 15 minutos |
| `ZeebeBackpressureGrowing` | `deriv` | backpressure rate | aceleração positiva |
| `CamundaNamespaceMemoryPressure` | `predict_linear` | memória total do namespace | 30 minutos |

**Regra crítica respeitada:** janela do `predict_linear` é sempre o dobro do horizonte de projeção.
- Horizonte 15min → janela mínima `[30m]`
- Horizonte 30min → janela mínima `[1h]`

### Arquivo criado

`alerting/camunda-forecasting-rules.yaml`

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: camunda-forecasting-alerts
  namespace: monitoring
  labels:
    # Label obrigatória para o operador do kube-prometheus-stack descobrir esta regra
    release: kube-prometheus-stack
    app: camunda-forecasting
spec:
  groups:
    - name: camunda.forecasting.memory
      # Intervalo de avaliação: a cada 1 minuto
      interval: 1m
      rules:

        # Alerta 1: JVM heap do Zeebe projetado acima de 85% em 15 minutos
        # Janela [30m] = 2x o horizonte de 15min (regra: janela >= 2x horizonte)
        - alert: ZeebeMemoryPredictedHigh
          expr: |
            (
              predict_linear(
                jvm_memory_used_bytes{
                  namespace="camunda",
                  pod=~"camunda-zeebe-[0-9]+",
                  area="heap"
                }[30m],
                900
              )
              /
              jvm_memory_max_bytes{
                namespace="camunda",
                pod=~"camunda-zeebe-[0-9]+",
                area="heap"
              }
            ) > 0.85
          # for: garante que a condição persista por 2min antes de disparar (evita flaps)
          for: 2m
          labels:
            severity: warning
            team: platform
            etapa: "1"
          annotations:
            summary: "Zeebe {{ $labels.pod }} — heap projetada acima de 85% em 15min"
            description: |
              A projeção linear indica que o pod {{ $labels.pod }} atingirá
              {{ $value | humanizePercentage }} de uso de heap nos próximos 15 minutos.
              Valor atual: {{ with query "jvm_memory_used_bytes{pod='{{ $labels.pod }}',area='heap'}" }}{{ . | first | value | humanize1024 }}B{{ end }}
            runbook_url: "https://github.com/alisson92/grafana-ml-lab/docs/etapa-1-prometheus-rules.md"

        # Alerta 2: aceleração positiva de backpressure — crescendo mais rápido que o normal
        # deriv() retorna a taxa de variação por segundo; positivo = crescendo
        - alert: ZeebeBackpressureGrowing
          expr: |
            deriv(
              zeebe_backpressure_inflight_requests_count{namespace="camunda"}[10m]
            ) > 0.5
          for: 3m
          labels:
            severity: warning
            team: platform
            etapa: "1"
          annotations:
            summary: "Zeebe backpressure em aceleração positiva"
            description: |
              A derivada do backpressure está em {{ $value | humanize }} req/s².
              O sistema está aceitando requests mais rápido do que processa — tendência de saturação.

    - name: camunda.forecasting.capacity
      interval: 1m
      rules:

        # Alerta 3: memória total do namespace camunda projetada para saturar em 30min
        # Janela [1h] = 2x o horizonte de 30min
        - alert: CamundaNamespaceMemoryPressure
          expr: |
            (
              predict_linear(
                sum by (namespace) (
                  container_memory_working_set_bytes{
                    namespace="camunda",
                    container!=""
                  }
                )[1h],
                1800
              )
              /
              sum by (namespace) (
                kube_node_status_allocatable{resource="memory"}
              )
            ) > 0.80
          for: 5m
          labels:
            severity: critical
            team: platform
            etapa: "1"
          annotations:
            summary: "Namespace camunda — memória projetada acima de 80% em 30min"
            description: |
              A projeção indica uso de {{ $value | humanizePercentage }} da memória alocável
              do nó nos próximos 30 minutos. Considere verificar consumo por pod.
```

### Como aplicar

```bash
# Criar diretório (se não existir)
mkdir -p alerting

# Aplicar o recurso no cluster Kind
kubectl apply -f alerting/camunda-forecasting-rules.yaml

# Confirmar que o Prometheus detectou a regra (pode levar até 1 minuto)
kubectl get prometheusrule -n monitoring camunda-forecasting-alerts

# Verificar se não há erros de sintaxe PromQL
curl -s 'http://localhost:9090/api/v1/rules' \
  | jq '.data.groups[] | select(.name | startswith("camunda.forecasting")) | .rules[].health'
# esperado: "ok" para cada regra
```

---

## Como validar

A etapa é considerada **concluída** quando todos os critérios abaixo forem atendidos:

### Critério 1 — Regras carregadas sem erro

```bash
curl -s 'http://localhost:9090/api/v1/rules' \
  | jq '[.data.groups[] | select(.name | startswith("camunda.forecasting")) | .rules[]] | length'
# esperado: 3
```

### Critério 2 — Alertas visíveis na UI do Prometheus

Acessar `http://localhost:9090/alerts` e confirmar que os três alertas aparecem com estado `inactive` (saudável) ou `firing` (se a carga sintética estiver ativa).

### Critério 3 — Alerta disparando com carga sintética

```bash
# Gerar carga alta para forçar o alerta de memória
./scripts/02-load-generator.sh --duration 10 --intensity high

# Em outro terminal, monitorar estado dos alertas
watch -n 5 'curl -s http://localhost:9093/api/v2/alerts | jq ".[].labels.alertname"'
# esperado após alguns minutos: "ZeebeMemoryPredictedHigh" ou "ZeebeBackpressureGrowing"
```

### Critério 4 — Alertas visíveis no Alertmanager

Acessar `http://localhost:9093` e confirmar que alertas com label `etapa: "1"` aparecem na interface.

---

## Problemas encontrados

### 1. Query inválida: range selector após agregação

**Sintoma:** `parse error: ranges only allowed for vector selectors`

**Causa raiz:** O PromQL não permite aplicar um range selector (`[30m]`, `[1h]`) a um instant vector resultante de uma agregação (`max by`, `sum by`). O `predict_linear` exige um range vector como primeiro argumento, e range vectors só podem ser criados a partir de seletores de métricas brutos.

**Exemplo inválido:**
```promql
predict_linear(max by (pod)(jvm_memory_used_bytes{...})[30m], 900)
```

**Correção — para alertas de série única:** aplicar o range no seletor bruto, sem agregação prévia:
```promql
predict_linear(jvm_memory_used_bytes{..., id="G1 Old Gen"}[30m], 900)
```

**Correção — para soma de namespace (Alerta 3):** aplicar `predict_linear` em cada série individualmente e agregar o resultado:
```promql
sum by (namespace)(predict_linear(container_memory_working_set_bytes{...}[1h], 1800))
```

### 2. Heap do Zeebe: G1 Eden e G1 Survivor têm max = -1

**Sintoma:** a query de ratio de heap (usado/max) retornava valores negativos ou inúteis para algumas séries.

**Causa raiz:** no G1GC, Eden Space e Survivor Space têm tamanho dinâmico — o JVM não expõe um limite fixo, então `jvm_memory_max_bytes` retorna `-1` para essas áreas.

**Decisão:** filtrar apenas `id="G1 Old Gen"`, que corresponde ao `Xmx` configurado (750MB no Zeebe deste lab) e é a única área com limite fixo e significativo para detecção de pressão de memória.

### 3. Estado `unknown` após aplicação do PrometheusRule

**Sintoma:** logo após `kubectl apply`, a API do Prometheus retornava `health: "unknown", state: "unknown"` para todas as regras.

**Causa:** comportamento esperado — o Prometheus carrega as regras mas só as avalia no próximo ciclo (`interval: 1m`). Após ~60 segundos, todas passaram para `health: "ok", state: "inactive"`.

---

## Próximo passo

Com os alertas preditivos funcionando e validados pelos critérios acima, avançar para:

**[Etapa 2 — Grafana MCP Server](etapa-2-grafana-mcp-server.md)**

O MCP Server conecta o Claude ao Grafana em tempo real. Com os alertas da Etapa 1 ativos, o agente consegue não apenas visualizar dashboards, mas responder perguntas como "qual alerta preditivo está mais próximo de disparar?" com dados reais.
