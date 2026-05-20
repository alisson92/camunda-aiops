---
tags: [sre, grafana, prometheus, ml, forecasting, camunda, alertas, projeto]
created: 2026-05-20
status: concluído
tipo: projeto
relacionado:
  - "[[grafana-ml-lab-comandos]]"
  - "[[ideia-ml-alertas-grafana]]"
---

# ML para Alertas Inteligentes no Grafana
## Do Problema ao Laboratório: Forecasting com Prometheus e Camunda 8.9

| Campo | Valor |
|---|---|
| Autor | Alisson Lima |
| Data | 20 de maio de 2026 |
| Perfil | SRE / DevOps Junior |
| Ambiente | Kind local + Camunda 8.9 + kube-prometheus-stack |

---

## 1. Motivação — Por que pensar em ML para alertas?

O ponto de partida não foi uma tecnologia — foi um problema operacional concreto e recorrente: **alertas que disparam às 3h da manhã para situações completamente normais**.

Um cluster Kubernetes com Camunda 8.9 em produção tem padrões previsíveis: CPU mais alta às 9h de segunda-feira, picos de processamento em datas de fechamento, consumo de memória que oscila por conta do Garbage Collector Java. Um alerta baseado em threshold fixo não sabe disso. Ele dispara toda vez que o valor ultrapassa o número configurado, independente do contexto histórico.

> **O problema central:** alertas com threshold fixo não distinguem pico normal de anomalia real. Isso gera fadiga de alerta no time — com o tempo, alertas começam a ser ignorados, e o alerta que realmente importa se perde no ruído.

A pergunta que originou este projeto foi:

> *"Como posso saber que algo vai dar errado antes que dê?"*

A resposta está em substituir alertas reativos por alertas preditivos — que aprendem o comportamento histórico do sistema e alertam quando a tendência atual indica que um problema está se formando, não quando ele já aconteceu.

---

## 2. Contexto do Ambiente

### 2.1 Stack em produção (EKS)

O ambiente de referência é um deployment do Camunda 8.9 Self-Managed no Amazon EKS, operado por uma equipe pequena em regime de plantão 12x36.

| Componente | Função | Criticidade |
|---|---|---|
| Zeebe | Motor BPMN — executa os processos | Alta |
| Operate | UI de monitoramento de instâncias | Média |
| Tasklist | UI de tarefas humanas | Média |
| Identity | Autenticação e autorização (Keycloak) | Alta |
| Optimize | Análise e relatórios de processos | Baixa |
| Web Modeler | Modelagem de processos BPMN | Baixa |
| Connectors | Integração com sistemas externos | Média |
| Elasticsearch | Armazenamento de dados de processo | Alta |

### 2.2 Laboratório local (Kind)

Para validar as ideias com segurança, foi montado um cluster Kind local espelhando a arquitetura do EKS. O cluster `camunda-platform-local` possui 1 control-plane e 2 workers.

| Componente | Namespace | Versão |
|---|---|---|
| Camunda Platform | camunda | 8.9.0 (chart 14.0.0) |
| kube-prometheus-stack | monitoring | Prometheus v3.11.3 + Grafana OSS |
| Elasticsearch, PostgreSQL, Keycloak | camunda-infra | Externos ao chart Camunda |

---

## 3. ML no Contexto DevOps — Conceitos Aplicados

Machine Learning em operações não significa modelos complexos ou infraestrutura de dados. No contexto de SRE, ML é **estatística aplicada a séries temporais** para antecipar problemas, reduzir ruído e tornar alertas mais inteligentes.

### 3.1 Comparativo: threshold fixo vs alerta preditivo

| Característica | Threshold fixo (atual) | Alerta preditivo (objetivo) |
|---|---|---|
| Lógica | `SE valor > X por N min` | `SE tendência indica X em N min` |
| Contexto histórico | Nenhum | Aprende padrões de dias/semanas anteriores |
| Sazonalidade | Ignora | Considera horário, dia da semana |
| Falsos positivos | Frequentes em picos normais | Reduzidos pelo contexto |
| Momento do alerta | Quando o problema já existe | Antes do problema acontecer |

### 3.2 Funções PromQL disponíveis (sem custo adicional)

| Função | O que faz | Melhor para |
|---|---|---|
| `predict_linear(v[T], t)` | Extrapola tendência linear por `t` segundos | Disco, filas, leaks de memória |
| `double_exponential_smoothing(v, sf, tf)` | Suavização com mais peso em dados recentes | Memória Java com GC |
| `avg_over_time(v[T])` | Média móvel — remove ruído | CPU, qualquer métrica ruidosa |
| `deriv(v[T])` | Taxa de variação instantânea | Detectar aceleração antes do pico |

> **Parâmetros validados para `predict_linear`:** janela 30min, horizonte 15min. Relação janela/horizonte deve ser ≥ 2:1 — projetar metade do que foi observado.

### 3.3 Próximo nível — Prophet/sklearn

Para capturar sazonalidade semanal e feriados brasileiros, um CronJob Python pode buscar histórico do Prometheus, treinar um modelo Prophet e empurrar previsões de volta via Pushgateway:

```
Prometheus API → Python (Prophet) → previsão → Pushgateway → Prometheus → Grafana
```

---

## 4. O Laboratório — O que Foi Construído

Lab em `~/personal/projects/grafana-ml-lab/` com três scripts e um dashboard Grafana, todos validados end-to-end no ambiente Kind local.

### 4.1 Scripts

| Script | Finalidade |
|---|---|
| `01-check-metrics.sh` | Inspeciona quais métricas o Prometheus coleta, separadas por prefixo |
| `02-load-generator.sh` | Gera carga sintética oscilatória com `--intensity low\|medium\|high` |
| `03-import-dashboard.sh` | Importa dashboard via API do Grafana com validação de autenticação |

### 4.2 Dashboard de forecasting — Seção 1: Infraestrutura K8s

| Painel | Técnica | O que mostra |
|---|---|---|
| CPU real vs média móvel | `avg_over_time 10min` | Smoothing remove ruído — evidencia tendência real |
| Memória vs projeção 15min | `predict_linear janela 30m` | Onde a memória estará em 15min |
| Memória vs suavização exponencial | `double_exponential_smoothing` | Tendência sem distorção de GC |
| Pods Running por namespace | `kube_pod_status_phase` | Padrão de escala up/down |
| Taxa de crescimento (deriv) | `deriv 5min` | Aceleração — positivo=crescendo |
| Gauge memória projetada % | `predict_linear` | Alerta preditivo visual (verde/amarelo/vermelho) |
| Gauge aceleração CPU | `deriv` | Tendência instantânea de CPU |

### 4.3 Dashboard de forecasting — Seção 2: Zeebe e componentes Camunda

| Painel | Técnica | O que mostra |
|---|---|---|
| Backpressure: inflight vs limite | `predict_linear` + raw metrics | Principal sinal de gargalo do Zeebe |
| Latência p99 stream processor | `histogram_quantile` + DES | Tempo de processamento BPMN + tendência |
| Memória RocksDB vs projeção | `predict_linear` | Crescimento monotônico do storage do Zeebe |
| JVM Heap por componente | `jvm_memory_used_bytes` | Pressão de memória separada por pod |
| HTTP p99 por componente | `histogram_quantile` | Latência da camada de API por componente |

---

## 5. ServiceMonitors — Habilitando a Coleta de Métricas

> **Descoberta importante:** sem ServiceMonitors, o Prometheus ignora completamente os componentes Camunda — sem erro visível, sem log de aviso. A execução inicial do `01-check-metrics.sh` retornou 0 métricas em todos os prefixos Camunda.

### 5.1 Processo de investigação

1. Confirmar ausência: `kubectl get servicemonitor -n camunda`
2. Identificar Services: `kubectl get svc -n camunda`
3. Confirmar nomes exatos das portas (não o número — o **nome**): `kubectl get svc -n camunda <nome> -o jsonpath='{range .spec.ports[*]}{.name}{"\t"}{.port}{"\n"}{end}'`
4. Testar endpoint manualmente antes de criar o ServiceMonitor: `kubectl exec ... -- wget -qO- http://localhost:<porta>/actuator/prometheus`
5. Criar o ServiceMonitor com os valores confirmados e o label obrigatório `release: kube-prometheus-stack`

### 5.2 Endpoints confirmados

| Componente | Service | Porta | Nome da porta | Path |
|---|---|---|---|---|
| Zeebe broker | `camunda-zeebe` | 9600 | `server` | `/actuator/prometheus` |
| Zeebe gateway | `camunda-zeebe-gateway` | 9600 | `server` | `/actuator/prometheus` |
| Connectors | `camunda-connectors` | 8080 | `http` | `/actuator/prometheus` |
| Identity | `camunda-identity` | 8082 | `metrics` | `/actuator/prometheus` |
| Optimize | `camunda-optimize` | 8092 | `management` | `/actuator/prometheus` |
| Web Modeler | `camunda-web-modeler-restapi` | 8091 | `http-management` | `/actuator/prometheus` |

### 5.3 Resultado — antes e depois

| Prefixo | Antes | Depois | Exemplos relevantes |
|---|---|---|---|
| `zeebe_` | 0 | **290** | backpressure, stream_processor, rocksdb, exporter |
| `jvm_` | 0 | **28** | heap, GC, threads por componente |
| `http_server_requests` | 0 | **10** | latência, contagem por endpoint |
| `operate_` | 0 | 2 | model_bpmn_count, model_dmn_count |
| `container_*` | OK | OK | CPU e memória (cadvisor — sempre disponível) |
| `node_*` | OK | OK | CPU, memória, disco dos nodes (node-exporter) |

---

## 6. Bugs Encontrados e Lições Aprendidas

### 6.1 Script 03-import-dashboard.sh — três bugs

| Bug | Causa | Correção |
|---|---|---|
| Senha hardcoded errada (`prom-operator`) | Pressuposto incorreto sobre o default do kube-prometheus-stack | Remover default — pedir via variável de ambiente, flag `--password` ou `read -rsp` |
| `/api/health` não valida autenticação | Endpoint retorna HTTP 200 sem credenciais | Usar `/api/org` — retorna 401 com credenciais inválidas |
| `curl -sf` engolia erro HTTP 401 | `set -e` não captura erros dentro de subshell com pipe | Separar status e body: `curl -w "%{http_code}" -o tempfile`, inspecionar código explicitamente |

### 6.2 Prometheus v3.x — compatibilidade de funções

| Problema | Causa | Solução |
|---|---|---|
| `holt_winters()` retorna `bad_data` | Função removida no Prometheus v3.x | Substituir por `double_exponential_smoothing()` — mesmos parâmetros |
| `double_exponential_smoothing()` retorna `bad_data` | Função experimental — desabilitada por padrão no v3.x | Adicionar `enableFeatures: [promql-experimental-functions]` no `prometheus-values.yaml` |
| `predict_linear` superestimava (3.38 GiB → 6.87 GiB projetado) | Janela 10min e horizonte 30min — relação 1:3 | Janela 30min, horizonte 15min — relação 2:1 |

### 6.3 ServiceMonitors — armadilhas silenciosas

- O label `release: kube-prometheus-stack` é **obrigatório** em todos os ServiceMonitors. Sem ele, o Prometheus Operator ignora silenciosamente — sem erro, sem log
- O campo `port` no ServiceMonitor deve ser o **nome** da porta, não o número. Nome errado = sem coleta, sem erro visível
- Services headless (`ClusterIP: None`) funcionam normalmente com ServiceMonitor
- O `app.kubernetes.io/component` do `web-modeler-restapi` é `restapi` (não `web-modeler-restapi`) — labels do Service devem ser inspecionados antes de criar o selector

---

## 7. Configurações Aplicadas no Ambiente

### 7.1 prometheus-values.yaml — feature flag experimental

```yaml
prometheus:
  prometheusSpec:
    enableFeatures:
      - promql-experimental-functions
```

Aplicado via:

```bash
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring -f monitoring/prometheus-values.yaml
```

Confirmação:

```bash
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 \
  -c prometheus -- cat /proc/1/cmdline | tr '\0' '\n' | grep enable-feature
# Saída esperada: --enable-feature=promql-experimental-functions
```

### 7.2 Versões confirmadas

| Componente | Versão | Observação |
|---|---|---|
| Prometheus | v3.11.3 | `quay.io/prometheus/prometheus` — `holt_winters` removido |
| Grafana | OSS via kube-prometheus-stack | Senha: `grafana-secret` |
| Camunda Platform | 8.9.0 | Chart `camunda-platform-14.0.0` — Operate/Tasklist unificados no Zeebe |
| Kind node | `kindest/node:v1.34.0` | 1 control-plane + 2 workers |

---

## 8. Caminho para Produção — EKS

### 8.1 Métricas prioritárias para forecasting em produção

| Métrica | Técnica recomendada | Sinal de alerta |
|---|---|---|
| `zeebe_backpressure_inflight_requests_count` | `predict_linear` janela 30min | Projeção ultrapassa `requests_limit` |
| `zeebe_rocksdb_memory_cur_size_all_mem_tables` | `predict_linear` janela 1h | Projeção ultrapassa 80% do heap do pod |
| `jvm_memory_used_bytes{area="heap"}` | `double_exponential_smoothing` | Tendência crescente sustentada por 10min |
| `zeebe_stream_processor_latency_seconds` | `histogram_quantile p99` | p99 > 1s por mais de 5min |
| `container_memory_working_set_bytes` | `predict_linear` janela 30min | Projeção ultrapassa 85% do node allocatable |

### 8.2 Plano de implantação em 5 etapas

1. **Validar baseline** — observar o dashboard por 1-2 semanas com o Camunda em uso real. Entender o padrão normal de cada métrica por horário e dia da semana
2. **Calibrar thresholds** — ajustar os valores dos gauges (atualmente 75%/88%) para refletir o comportamento real do ambiente do cliente
3. **Criar PrometheusRules** — converter as queries validadas em regras de alerta com `for: Nm` adequado. Usar `for: 10m` como padrão
4. **Testar no staging** — validar que não geram ruído durante pelo menos 1 semana de operação normal
5. **Aplicar no EKS com documentação** — incluir as regras no repositório como código, documentar no runbook o que cada alerta significa e qual a ação esperada

### 8.3 Esboço de PrometheusRule para produção

```yaml
groups:
- name: camunda.forecasting
  rules:
  - alert: MemoriaProjetadaCritica
    expr: |
      predict_linear(
        sum(container_memory_working_set_bytes{namespace="camunda", container!=""})[30m:2m],
        900
      )
      / sum(kube_node_status_allocatable{resource="memory"})
      * 100 > 85
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "Memória projetada acima de 85% em 15min"
      description: |
        Tendência indica {{ $value | printf "%.1f" }}% de ocupação em ~15min.
        Investigar antes do threshold ser atingido.
```

---

## 9. Resumo Executivo

### Artefatos produzidos

| Artefato | Localização | Status |
|---|---|---|
| `01-check-metrics.sh` | `~/personal/projects/grafana-ml-lab/scripts/` | Funcionando |
| `02-load-generator.sh` | `~/personal/projects/grafana-ml-lab/scripts/` | Funcionando |
| `03-import-dashboard.sh` | `~/personal/projects/grafana-ml-lab/scripts/` | Funcionando — com tratamento de erro robusto |
| `camunda-forecasting.json` | `~/personal/projects/grafana-ml-lab/dashboards/` | Importado no Grafana — 11 painéis ativos |
| `camunda-servicemonitors.yaml` | `~/personal/projects/camunda-kind/monitoring/` | Aplicado — 6 ServiceMonitors ativos |
| `prometheus-values.yaml` | `~/personal/projects/camunda-kind/monitoring/` | Atualizado com `enableFeatures` |
| `grafana-ml-lab-comandos.md` | Obsidian: `40-references/` | Referência técnica completa |
| `ideia-ml-alertas-grafana.md` | Obsidian: `10-areas/sre-fundamentos/` | Registro da ideia e caminho para produção |

### O que foi alcançado

Partindo de um Prometheus que não coletava nenhuma métrica dos componentes Camunda, chegamos a um ambiente com **290 métricas do Zeebe**, **28 do JVM** e **10 de HTTP** em coleta, com um dashboard de forecasting funcional usando três técnicas distintas de projeção. Todos os erros encontrados foram diagnosticados, corrigidos e documentados.

A base está construída para evoluir de alertas reativos (threshold fixo) para alertas preditivos (baseados em tendência histórica) — primeiro via PromQL nativo no Kind, depois em staging, e por fim no EKS em produção.
