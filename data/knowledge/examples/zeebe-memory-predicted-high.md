---
alert_name: ZeebeMemoryPredictedHigh
type: example
severity: warning
---
# Exemplo de análise — ZeebeMemoryPredictedHigh

Exemplo de análise ideal para o alerta preditivo de heap JVM do Zeebe broker.
Use como referência de formato, profundidade e comandos sugeridos.

## Análise de referência

CAUSA_RAIZ: Heap G1 Old Gen do zeebe-broker crescendo de forma monotônica — projeção linear indica ultrapassagem do threshold de 600 MB em ~18 min; possível acúmulo de instâncias BPMN não finalizadas ou GC pressure

URGÊNCIA: Alta (< 1 h)

MÉTRICAS_COLETADAS:
- jvm_memory_used_bytes{area="heap", pod="camunda-zeebe-0"}: 412 MB
- predict_linear(jvm_memory_used_bytes[10m], 1800): 648 MB (projetado)
- jvm_gc_pause_seconds_count (últimos 5 min): 3 pauses
- kube_pod_container_status_restarts_total{container="zeebe"}: 0

IMPACTO_ESTIMADO: Sem impacto confirmado ainda — alerta preditivo; se heap atingir Xmx (750 MB) o broker pode ser OOMKilled interrompendo jobs em execução

REMEDIAÇÃO:
1. `kubectl logs -n camunda camunda-zeebe-0 --tail=100 | grep -i "gc\|memory\|heap"` — verificar sinais de GC pressure
2. `kubectl top pod camunda-zeebe-0 -n camunda` — confirmar uso atual de memória
3. Se crescimento confirmar, restart controlado: `kubectl rollout restart statefulset/camunda-zeebe -n camunda`

PRIMEIRO_PASSO: `kubectl logs -n camunda camunda-zeebe-0 --tail=100 | grep -i "gc\|memory\|heap"`

## Contexto do ambiente

- Xmx padrão do Zeebe broker no Kind local: 750 MB
- GC G1 faz coletas incrementais; heap crescendo sem coletas indica objetos de longa vida
- Verificar no Operate se há instâncias BPMN presas em estado "Incident" acumulando memória
