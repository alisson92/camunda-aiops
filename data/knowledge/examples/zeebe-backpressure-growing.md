---
alert_name: ZeebeBackpressureGrowing
type: example
severity: critical
---
# Exemplo de análise — ZeebeBackpressureGrowing

Exemplo de análise ideal para o alerta de backpressure crescente no Zeebe Gateway.
Use como referência de formato, profundidade e comandos sugeridos.

## Análise de referência

CAUSA_RAIZ: Gateway Zeebe saturado — backpressure crescendo a +0.8 req/s por 5 min consecutivos; fila de inflight requests esgotando capacidade de processamento do broker

URGÊNCIA: Imediata (< 15 min)

MÉTRICAS_COLETADAS:
- zeebe_backpressure_inflight_requests_count: 318 requests
- rate zeebe_backpressure_inflight [5m]: +0.8 req/s
- kube_pod_status_phase{namespace="camunda"}: 3/3 Running (sem falha de pod)
- container_memory_working_set_bytes (zeebe-broker): 1.2 GB

IMPACTO_ESTIMADO: Gateway rejeitando novas requisições gRPC — instâncias BPMN novas falham ao iniciar; processos em andamento não são afetados (broker continua executando jobs já aceitos)

REMEDIAÇÃO:
1. `kubectl top pods -n camunda` — identificar pod com maior consumo de CPU/memória
2. Pausar conectores de alto volume no Operate (UI > Connectors > pause)
3. `kubectl scale deployment camunda-zeebe-gateway --replicas=2 -n camunda` — escalar gateway se disponível no cluster

PRIMEIRO_PASSO: `kubectl top pods -n camunda`

## Contexto do ambiente

- zeebe-gateway aplica backpressure quando o broker não consegue processar na taxa de entrada
- Aumentar réplicas do gateway **não resolve** se o gargalo for no broker
- Verificar RocksDB e JVM heap do broker antes de escalar
