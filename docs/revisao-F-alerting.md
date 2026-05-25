---
titulo: Revisão F — Alerting strategy e cobertura de PrometheusRules
data: 2026-05-25
status: concluída
tipo: revisao
---

# Revisão F — Alerting strategy e cobertura de PrometheusRules

## Por que esta revisão foi realizada

O projeto tinha 3 alertas preditivos (heap JVM, backpressure, memória do namespace), mas
dois caminhos críticos de falha do Camunda 8 estavam sem cobertura:
- **Latência do Zeebe Gateway** — único ponto de entrada gRPC/REST sem alerta
- **Disco/PVC do Zeebe** — disco cheio no RocksDB para o processamento BPMN imediatamente

Além disso, todos os alertas compartilhavam o mesmo `runbook_url` genérico, e nenhum tinha
a label `component`, dificultando routing futuro por componente.

---

## O que foi feito

### 1. `camunda-forecasting-rules.yaml` — melhorias nas rules existentes

**Label `component` adicionada** em todos os alertas existentes:

| Alerta | component |
|---|---|
| `ZeebeMemoryPredictedHigh` | `zeebe` |
| `ZeebeBackpressureGrowing` | `zeebe` |
| `CamundaNamespaceMemoryPressure` | `camunda` |

**Por quê:** a label `component` permite routing diferenciado no Alertmanager e filtragem no
Grafana. Hoje é usada para contexto; futuramente pode direcionar alertas de `zeebe-gateway`
para um receiver diferente dos de `zeebe`.

**`runbook_url` corrigido por alerta:**

| Alerta (antes) | runbook_url (antes) | runbook_url (depois) |
|---|---|---|
| `ZeebeMemoryPredictedHigh` | `docs/etapa-1-prometheus-rules.md` | `data/knowledge/examples/zeebe-memory-predicted-high.md` |
| `ZeebeBackpressureGrowing` | `docs/etapa-1-prometheus-rules.md` | `data/knowledge/examples/zeebe-backpressure-growing.md` |
| `CamundaNamespaceMemoryPressure` | `docs/etapa-1-prometheus-rules.md` | `docs/etapa-1-prometheus-rules.md` (sem exemplo KB) |

Os dois primeiros agora apontam para os exemplos curados da KnowledgeBase — os mesmos
documentos que o agente usa como few-shot context. Isso fecha o ciclo: o link do Alertmanager
leva ao mesmo material que o LLM usa para analisar o alerta.

---

### 2. `camunda-latency-rules.yaml` — novo arquivo (Alerta 4)

**`ZeebeGatewayLatencyHigh`** — latência p99 do Gateway acima de 2s por 5 minutos.

**Técnica:** `histogram_quantile(0.99, sum by (le, pod) (rate(...[5m])))`

```yaml
- alert: ZeebeGatewayLatencyHigh
  expr: |
    histogram_quantile(0.99,
      sum by (le, pod) (
        rate(
          grpc_server_processing_duration_seconds_bucket{
            namespace="camunda",
            pod=~"camunda-zeebe-gateway-.*"
          }[5m]
        )
      )
    ) > 2
  for: 5m
  labels:
    severity: warning
    component: zeebe-gateway
```

**Por que Gateway e não Broker?** O Gateway é o único ponto de entrada externo para
workers, Operate e Tasklist. Latência alta aqui impacta imediatamente todos os clientes.
O Broker tem backpressure (já monitorado) como sinal de saturação interna.

**Por que `histogram_quantile` e não média?** A média mascara picos. p99 captura o pior
caso de 1% dos requests — que em workflows BPMN tipicamente são os jobs com maior SLA
(compensações, pagamentos, integrações externas).

**Por que `for: 5m`?** Latência momentânea pode ser GC pause ou spike de CPU. Cinco minutos
garantem que o problema é sustentado, não transitório.

---

### 3. `camunda-storage-rules.yaml` — novo arquivo (Alerta 5)

**`ZeebePVCUsagePredictedFull`** — PVC do Zeebe projetado para atingir 85% em 1 hora.

**Técnica:** `predict_linear(kubelet_volume_stats_used_bytes[2h], 3600)` / `capacity_bytes`

```yaml
- alert: ZeebePVCUsagePredictedFull
  expr: |
    (
      predict_linear(
        kubelet_volume_stats_used_bytes{
          namespace="camunda",
          persistentvolumeclaim=~"data-camunda-zeebe-.*"
        }[2h],
        3600
      )
      /
      kubelet_volume_stats_capacity_bytes{
        namespace="camunda",
        persistentvolumeclaim=~"data-camunda-zeebe-.*"
      }
    ) > 0.85
  for: 10m
  labels:
    severity: critical
    component: zeebe
```

**Por que `kubelet_volume_stats_used_bytes` e não `container_fs_usage_bytes`?**
`container_fs_usage_bytes` inclui layers overlay e a imagem do container, distorcendo o valor
real de dados do RocksDB. `kubelet_volume_stats_used_bytes` reflete exclusivamente o uso
do PVC montado — o que interessa.

**Por que `critical` (não `warning`)?** Disco cheio no Zeebe não degrada gradualmente —
o RocksDB para de aceitar escritas imediatamente. Não há janela de "degradação tolerável"
entre "disco quase cheio" e "parada total". Critical é o nível correto.

**Por que `for: 10m`?** O `predict_linear` em uma série monotônica (disco) pode oscilar
levemente em janelas curtas. Dez minutos garantem que a tendência é consistente e não
um artefato de compaction do RocksDB (que reduz temporariamente o tamanho dos arquivos).

**Janela `[2h]` = 2× horizonte 1h:** regra obrigatória do `predict_linear` — janela de
histórico deve ser ao menos o dobro do horizonte projetado.

---

## Cobertura de falhas antes e depois

| Componente | Falha | Antes | Depois |
|---|---|---|---|
| zeebe-broker | Heap JVM projetada alta | ✅ `ZeebeMemoryPredictedHigh` | ✅ |
| zeebe-broker | Backpressure crescendo | ✅ `ZeebeBackpressureGrowing` | ✅ |
| zeebe-broker | Disco RocksDB projetado cheio | ❌ | ✅ `ZeebePVCUsagePredictedFull` |
| zeebe-gateway | Latência p99 alta | ❌ | ✅ `ZeebeGatewayLatencyHigh` |
| namespace | Memória total projetada alta | ✅ `CamundaNamespaceMemoryPressure` | ✅ |

---

## O que foi decidido não implementar

**Alertas para Operate, Tasklist, Identity:** Esses componentes usam bancos de dados externos
(Elasticsearch/OpenSearch para o Operate) e autenticação (Keycloak). Monitorá-los adequadamente
requer acesso a métricas dessas dependências, que estão fora do escopo do lab. Qualquer
degradação nesses componentes se manifesta primeiro como latência do Gateway ou pressão de
memória do namespace (já monitorados).

**Alerta de `ZeebeBackpressureCritical` (escalada de severidade):** Considerado, mas
dois alertas para o mesmo sintoma com severidades diferentes complicam o sistema de
silenciamento (criar um silence exige matchers corretos para cada nome de alerta). O threshold
e o `for:` do alerta existente foram calibrados para capturar situações sérias.

---

## Como aplicar no cluster

```bash
# Novos arquivos (latência e storage)
kubectl apply -f alerting/camunda-latency-rules.yaml
kubectl apply -f alerting/camunda-storage-rules.yaml

# Atualização do arquivo existente (runbook_url + label component)
kubectl apply -f alerting/camunda-forecasting-rules.yaml

# Verificar que as 5 rules foram carregadas
curl -s 'http://localhost:9090/api/v1/rules' \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
rules = [r['name'] for g in d['data']['groups']
         for r in g['rules'] if r.get('type')=='alerting' and 'Zeebe' in r['name'] or 'Camunda' in r['name']]
print(f'{len(rules)} alertas Camunda:', *rules, sep='\n  ')
"
# Esperado: 5 alertas
```

---

## Resultado

| Métrica | Antes | Depois |
|---|---|---|
| PrometheusRules | 3 alertas, 1 arquivo | 5 alertas, 3 arquivos |
| Cobertura Gateway latência | ❌ | ✅ |
| Cobertura disco RocksDB | ❌ | ✅ |
| Label `component` | ❌ | ✅ todos os alertas |
| `runbook_url` por alerta | ❌ (mesmo URL em todos) | ✅ (por alerta, KB onde disponível) |
| yamllint | ✅ | ✅ |
| Testes Python | 213 | 213 ✅ |
| Cobertura Python | 100% | 100% ✅ |
