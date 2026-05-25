# Revisão F — Migração de alertas Grafana para PrometheusRule IaC

## Contexto

O ambiente de homologação já possuía 15 alertas configurados diretamente no Grafana
(UI-driven), distribuídos em 5 pastas. O objetivo desta migração é versionar essas
regras como PrometheusRule CRDs — IaC auditável, deployável via `kubectl apply`,
revisável em PRs e portável para qualquer cluster.

---

## Inventário de alertas migrados

### Fonte: Grafana folder "Kubernetes - Node" → `kubernetes-node-rules.yaml`

| Alert original (Grafana) | Alert PrometheusRule | Observações |
|---|---|---|
| Kubernetes - Node Condition Affected Pods | `KubeNodeConditionAffectedPods` | Lógica preservada com OR para 3 condições |
| Kubernetes - New Node | `KubeNewNode` | isPaused no Grafana — comentado |

### Fonte: Grafana folder "Elasticsearch" → `elasticsearch-rules.yaml`

| Alert original (Grafana) | Alert PrometheusRule | Observações |
|---|---|---|
| ElasticsearchClusterHealth (dynamic severity) | `ElasticsearchClusterHealthCritical` | color="red" → severity: critical |
| ElasticsearchClusterHealth (dynamic severity) | `ElasticsearchClusterHealthWarning` | color="yellow" → severity: warning |
| ElasticsearchUnassignedShards | `ElasticsearchUnassignedShards` | Migração direta |

### Fonte: Grafana folder "Camunda" → `camunda-forecasting-rules.yaml` (existente)

Alertas já estavam migrados nas Revisões anteriores (ZeebeMemoryPredictedHigh,
ZeebeBackpressureGrowing, CamundaNamespaceMemoryPressure).

### Fonte: Grafana folder "Kubernetes - Pod" → `kubernetes-pod-rules.yaml`

| Alert original (Grafana) | Alert PrometheusRule | Observações |
|---|---|---|
| KubePodNotReady | `KubePodNotReady` | Migração direta |
| KubeStatefulSetReplicasMismatch | `KubeStatefulSetReplicasMismatch` | Migração direta |
| KubeDeploymentReplicasMismatch | `KubeDeploymentReplicasMismatch` | Migração direta |
| KubePodHighMemory (dynamic severity) | `KubePodHighMemory` | > 80% → warning |
| KubePodHighMemory (dynamic severity) | `KubePodHighMemoryCritical` | > 90% → critical |
| KubePodCrashLooping | `KubePodCrashLooping` | Migração direta |
| KubePodHighCPU (dynamic severity) | `KubePodHighCPU` | > 80% → warning |
| KubePodHighCPU (dynamic severity) | `KubePodHighCPUCritical` | > 90% → critical |
| KubePodMultipleRestarts | `KubePodMultipleRestarts` | Migração direta |
| KubePodOOMKilled | `KubePodOOMKilled` | Migração direta, for: 0m |

### Fonte: Grafana folder "Kubernetes - Pod" (Kubernetes - Camunda NS) → `kubernetes-camunda-ns-rules.yaml`

| Alert original (Grafana) | Alert PrometheusRule | Observações |
|---|---|---|
| KubePersistentVolumeErrors | `KubePersistentVolumeErrors` | isPaused no Grafana |
| KubeStatefulSetGenerationMismatch | `KubeStatefulSetGenerationMismatch` | isPaused no Grafana |
| KubeStatefulSetUpdateNotRolledOut | `KubeStatefulSetUpdateNotRolledOut` | isPaused no Grafana |

---

## Decisões técnicas

### Severidade dinâmica → dois alertas separados

O Grafana suporta `$labels.color` ou `$values.A.Value` para determinar severity em
runtime. PrometheusRule não tem equivalente — severity é um label estático definido
em tempo de autoria.

**Decisão:** Split em dois alertas por threshold, padrão recomendado pelo
[awesome-prometheus-alerts](https://samber.github.io/awesome-prometheus-alerts/). Cada
alerta cobre um range discreto (warning: 80-90%, critical: >90%), sem sobreposição.

### Grafana-only features sem equivalente

| Feature Grafana | Comportamento em PrometheusRule |
|---|---|
| `keepFiringFor: 2m` | Alerta resolve assim que a condição deixa de ser verdadeira |
| `noDataState: OK` | PrometheusRule não dispara se não há dados (comportamento equivalente ao OK) |
| `execErrState: Error` | Erros de avaliação são reportados pelo Prometheus, não pelo alerta |
| `isPaused: true` | Incluído no YAML mas com comentário `ATENÇÃO: Esta regra estava PAUSADA` |

As três regras de `kubernetes-camunda-ns-rules.yaml` estavam pausadas no Grafana —
incluídas como IaC para não perder o trabalho anterior, mas marcadas como candidatas
a revisão antes de aplicar ao cluster.

### runbook_url sem URLs externas

Todos os `runbook_url` apontam para `http://172.18.0.1:5001/runbook/by-alert/{AlertName}`.
O endpoint `GET /runbook/by-alert/{alert_name}` serve o runbook mais recente gerado
pelo agente para aquele alertname — sem dependência de URLs externas (requisito de
segurança/compliance do ambiente produtivo).

### ALERT_FILTER_KEYWORDS expandido

`.env.example` atualizado para `Zeebe,Camunda,Kube,Elasticsearch`. O agente usa esta
lista para filtrar quais alertas processar — sem essa expansão, os novos alertas seriam
ignorados silenciosamente.

---

## Estrutura de arquivos após migração

```
alerting/
├── camunda-forecasting-rules.yaml   # ZeebeMemory, ZeebeBackpressure, CamundaMemory
├── camunda-latency-rules.yaml       # ZeebeGatewayLatencyHigh
├── camunda-storage-rules.yaml       # ZeebePVCUsagePredictedFull
├── elasticsearch-rules.yaml         # ElasticsearchClusterHealth (x2), UnassignedShards
├── kubernetes-node-rules.yaml       # KubeNodeConditionAffectedPods, KubeNewNode
├── kubernetes-pod-rules.yaml        # 10 alertas de pods
├── kubernetes-camunda-ns-rules.yaml # 3 alertas (isPaused) de PV/StatefulSet
├── alertmanager-config-camunda.yaml # CRD AlertmanagerConfig
└── alertmanager-webhook-patch.yaml  # values patch para helm upgrade
```

---

## Aplicar no cluster

```bash
# Validar sintaxe antes de aplicar
yamllint alerting/

# Aplicar todos os novos manifestos
kubectl apply -f alerting/elasticsearch-rules.yaml
kubectl apply -f alerting/kubernetes-node-rules.yaml
kubectl apply -f alerting/kubernetes-pod-rules.yaml
kubectl apply -f alerting/kubernetes-camunda-ns-rules.yaml

# Verificar que foram importados pelo Prometheus Operator
kubectl get prometheusrule -n monitoring

# Conferir regras no Prometheus UI
# http://localhost:9090/rules
```

**Atenção:** As 3 regras em `kubernetes-camunda-ns-rules.yaml` estavam pausadas no
Grafana. Revisar threshold e semântica antes de aplicar em produção.
