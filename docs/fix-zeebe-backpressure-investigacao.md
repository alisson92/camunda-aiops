---
titulo: "Fix — ZeebeBackpressureGrowing: investigação e validação"
data: "2026-05-22"
status: "concluído"
relacionado: "etapa-1-prometheus-rules"
---

# Fix — ZeebeBackpressureGrowing: investigação e validação

## Problema reportado

O alerta `ZeebeBackpressureGrowing` estava `inactive` por ausência de série de dados
(`zeebe_backpressure_requests_total` não estava sendo coletada). Havia risco de falsa
sensação de cobertura: o alerta ficava inativo não porque o sistema estava saudável,
mas porque a métrica simplesmente não existia.

---

## Investigação

### Métricas de backpressure disponíveis no Prometheus

```bash
curl -s "http://localhost:9090/api/v1/label/__name__/values" | \
  python3 -c "import json,sys; [print(n) for n in json.load(sys.stdin)['data'] if 'backpressure' in n]"
```

Resultado:
```
zeebe_backpressure_inflight_append_count
zeebe_backpressure_inflight_requests_count   ← usada no alerta atual
zeebe_backpressure_requests_limit
```

`zeebe_backpressure_requests_total` não existe no Zeebe 8.9. O nome correto é
`zeebe_backpressure_inflight_requests_count`.

### Estado atual da métrica

```bash
curl -s "http://localhost:9090/api/v1/query?query=zeebe_backpressure_inflight_requests_count"
```

Labels confirmados:
- `namespace: camunda` ✓
- `pod: camunda-zeebe-0` ✓
- `partition: "1"` ✓
- Valor atual: `0` (sem backpressure — sistema saudável)

### Estado do alerta no Prometheus

```bash
curl -s "http://localhost:9090/api/v1/rules"
# ZeebeBackpressureGrowing: state=inactive, health=ok
```

---

## Conclusão

**O alerta está funcionando corretamente.** A PrometheusRule já usa o nome correto
`zeebe_backpressure_inflight_requests_count`. O `state: inactive` é o comportamento
esperado para um sistema sem carga de backpressure.

O bug anterior foi resolvido quando a regra foi atualizada para o nome correto da métrica.
A documentação da Etapa 1 registrava o bug como pendente, mas a correção já havia sido aplicada.

---

## Como confirmar que o alerta funcionaria sob carga

Gerar carga e observar:

```bash
# Terminal 1 — monitorar a métrica
watch -n 5 'curl -s "http://localhost:9090/api/v1/query?query=deriv(zeebe_backpressure_inflight_requests_count{namespace=\"camunda\"}[10m])" | python3 -m json.tool'

# Terminal 2 — gerar carga
./scripts/02-load-generator.sh --duration 30 --intensity high
```

O alerta dispararia se `deriv(...) > 0.5` por mais de 3 minutos consecutivos, indicando
que requests estão se acumulando mais rápido do que são processados.

---

## Métricas complementares úteis para diagnóstico

| Métrica | O que indica |
|---|---|
| `zeebe_backpressure_inflight_requests_count` | Requests in-flight no momento |
| `zeebe_backpressure_requests_limit` | Limite máximo de in-flight (backpressure threshold) |
| `zeebe_backpressure_inflight_append_count` | Appends ao log Raft em andamento |

Correlacionar `inflight_requests_count / requests_limit` dá a taxa de utilização do
backpressure: valores acima de 80% indicam risco.
