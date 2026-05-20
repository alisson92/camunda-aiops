# Grafana ML Lab — Camunda 8.9 + Kind Local

Lab para explorar forecasting de métricas no Grafana usando técnicas
disponíveis no Prometheus OSS (sem plugin pago), aplicadas ao stack
Camunda 8.9 Self-Managed + kube-prometheus-stack.

> **Documentação completa:** [`docs/2026-05-20-ml-alertas-grafana-forecasting.md`](docs/2026-05-20-ml-alertas-grafana-forecasting.md)
> Cobre motivação, decisões técnicas, bugs encontrados e caminho para produção.

---

## Estrutura do projeto

```
grafana-ml-lab/
├── README.md                          # este arquivo
├── dashboards/
│   └── camunda-forecasting.json       # dashboard Grafana — 11 painéis
├── docs/
│   └── 2026-05-20-ml-alertas-grafana-forecasting.md  # documentação completa
└── scripts/
    ├── 01-check-metrics.sh            # inspeciona métricas disponíveis no Prometheus
    ├── 02-load-generator.sh           # gera carga sintética com sazonalidade
    └── 03-import-dashboard.sh         # importa o dashboard via API do Grafana
```

---

## Pré-requisitos

```bash
# Cluster Kind rodando
kubectl get nodes --context kind-camunda-platform-local

# ServiceMonitors do Camunda aplicados (necessário para métricas zeebe_/jvm_/http_)
kubectl get servicemonitor -n camunda
# Esperado: 6 ServiceMonitors (zeebe, zeebe-gateway, connectors, identity, optimize, web-modeler-restapi)
# Se não existirem: kubectl apply -f ~/personal/projects/camunda-kind/monitoring/camunda-servicemonitors.yaml

# Port-forwards — cada um em um terminal separado
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &
```

### Recuperar a senha do Grafana

```bash
kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d && echo
```

---

## Execução rápida

```bash
# 1. Verificar quais métricas estão sendo coletadas
./scripts/01-check-metrics.sh

# 2. Importar o dashboard no Grafana
GRAFANA_PASS=<senha> ./scripts/03-import-dashboard.sh

# 3. Gerar carga com sazonalidade para ver o forecasting em ação
./scripts/02-load-generator.sh --duration 30 --intensity medium
```

Dashboard disponível em:
`http://localhost:3000/d/camunda-local-forecasting/camunda-local-e28094-forecasting-com-promql`

---

## O dashboard

### Seção 1 — Infraestrutura K8s

| Painel | Técnica PromQL |
|---|---|
| CPU real vs média móvel | `avg_over_time` |
| Memória vs projeção +15min | `predict_linear` (janela 30min) |
| Memória vs suavização exponencial | `double_exponential_smoothing` |
| Pods Running por namespace | `kube_pod_status_phase` |
| Taxa de crescimento de memória | `deriv` |
| Gauge — ocupação de memória projetada % | `predict_linear` |
| Gauge — aceleração de CPU | `deriv` |

### Seção 2 — Zeebe e componentes Camunda

| Painel | Técnica PromQL |
|---|---|
| Backpressure: inflight vs limite + projeção | `predict_linear` |
| Latência p99 stream processor + tendência | `histogram_quantile` + `double_exponential_smoothing` |
| Memória RocksDB vs projeção +15min | `predict_linear` |
| JVM Heap por componente | `jvm_memory_used_bytes` |
| HTTP p99 por componente | `histogram_quantile` |

---

## Técnicas de forecasting

### `predict_linear(v[T], t)`

Extrapola a tendência linear observada em `T` por `t` segundos à frente.

```promql
# Onde a memória estará em 15min, baseado nos últimos 30min
predict_linear(
  sum(container_memory_working_set_bytes{namespace="camunda", container!=""})[30m:2m],
  900
)
```

> **Regra validada:** janela/horizonte ≥ 2:1. Janela 30min → horizonte máx. 15min.
> Horizonte maior superestima e gera falsos positivos.

**Bom para:** disco, filas do Zeebe, RocksDB, leaks de memória — recursos monotônicos.

### `double_exponential_smoothing(v, sf, tf)`

Suavização exponencial dupla — dá mais peso aos dados recentes sem amplificar picos transitórios.

```promql
double_exponential_smoothing(
  sum(container_memory_working_set_bytes{namespace="camunda", container!=""})[30m:2m],
  0.3,  -- sf: smoothing factor (0=mais suave, 1=reativo)
  0.1   -- tf: trend factor (conservador para memória Java)
)
```

> **Requer feature flag no Prometheus v3.x:**
> ```yaml
> prometheus:
>   prometheusSpec:
>     enableFeatures:
>       - promql-experimental-functions
> ```

**Bom para:** memória de aplicações Java com GC, qualquer métrica com oscilação natural.

> **Nota de compatibilidade:** `holt_winters()` foi removido no Prometheus v3.x.
> Substituto direto: `double_exponential_smoothing()` — mesmos parâmetros.

### `avg_over_time(v[T])`

Média móvel simples — remove ruído e evidencia tendência. Funciona em qualquer versão do Prometheus, sem feature flag.

```promql
avg_over_time(
  sum(rate(container_cpu_usage_seconds_total{namespace="camunda"}[2m]))[10m:1m]
)
```

### `deriv(v[T])`

Taxa de variação instantânea. Positivo = crescendo, negativo = reduzindo.

```promql
deriv(sum(container_memory_working_set_bytes{namespace="camunda"})[5m:])
```

**Bom para:** detectar aceleração antes do pico, não só o pico em si.

---

## ServiceMonitors

Os ServiceMonitors são necessários para que o Prometheus colete métricas
dos componentes Camunda (`zeebe_`, `jvm_`, `http_server_requests_*`).
Sem eles, o Prometheus ignora os componentes silenciosamente.

O arquivo com todos os ServiceMonitors validados está em:

```
~/personal/projects/camunda-kind/monitoring/camunda-servicemonitors.yaml
```

Endpoints confirmados:

| Componente | Porta | Nome da porta |
|---|---|---|
| Zeebe broker | 9600 | `server` |
| Zeebe gateway | 9600 | `server` |
| Connectors | 8080 | `http` |
| Identity | 8082 | `metrics` |
| Optimize | 8092 | `management` |
| Web Modeler REST API | 8091 | `http-management` |

---

## Próximo nível — Prophet/sklearn

Para sazonalidade semanal e feriados brasileiros, o próximo passo é um CronJob Python:

```
Prometheus API → Python (Prophet) → Pushgateway → Prometheus → Grafana
```

Condições para considerar:
- `predict_linear` calibrado ainda gera falsos positivos após 4+ semanas
- Histórico mínimo de 4 semanas disponível para treinar
- Sazonalidade do cliente relevante (fechamentos mensais, datas fixas)

---

## Referências

- [Prometheus — Query functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)
- [Prometheus v3.0 changelog](https://github.com/prometheus/prometheus/releases/tag/v3.0.0)
- [Camunda 8 — Métricas do Zeebe](https://docs.camunda.io/docs/self-managed/zeebe-deployment/operations/metrics/)
- [Grafana ML Plugin](https://grafana.com/docs/grafana-cloud/alerting-and-irm/machine-learning/) (requer Cloud/Enterprise)
