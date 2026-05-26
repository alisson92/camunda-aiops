# Melhorias Pós-Demo — Pontos Levantados pelo Time

**Contexto:** Registro consolidado dos pontos de melhoria identificados pelo time após a apresentação da demo. Cada item inclui análise do problema atual, opções de solução e trade-offs. Nenhum item está implementado — este documento serve como base para priorização e planejamento das próximas etapas.

> Para a análise comparativa com soluções prontas da comunidade (HolmesGPT, K8sGPT, Robusta, Grafana LLM App), consulte [`comparativo-solucoes-aiops-comunidade.md`](./comparativo-solucoes-aiops-comunidade.md).

---

## Índice

1. [Persistência de dados do agente](#1-persistência-de-dados-do-agente)
2. [Entender a projeção de alerta real (acurácia do forecasting)](#2-entender-a-projeção-de-alerta-real)
3. [Filtrar alertas por label em vez de keyword](#3-filtrar-alertas-por-label-em-vez-de-keyword)
4. [Ampliar métricas internas do agente](#4-ampliar-métricas-internas-do-agente)

---

## 1. Persistência de dados do agente

### Problema atual

O agente reinicia "zerado" — todo o conhecimento acumulado é perdido quando o processo é reiniciado.

| Dado | Onde vive hoje | Perdido no restart? | Impacto |
|---|---|---|---|
| Runbooks gerados (`_runbooks` dict) | Memória Python | Sim | Links "📖 Runbook" nos cards Teams quebram |
| Base de conhecimento RAG (`KnowledgeBase`) | `data/knowledge/runbooks/` no filesystem do container | Sim (container efêmero) | Agente recomeça sem histórico de incidentes — RAG degradado |
| Cache de deduplicação (`_dedup_cache`) | Memória Python | Sim | Baixo — no pior caso reprocessa um alerta duplicado após restart |

O `_dedup_cache` é o menos crítico (TTL 300s, alertas `resolved` nunca deduplicados). A `KnowledgeBase` e o store de runbooks têm impacto direto na qualidade das análises.

### O que precisaria ser persistido

**Base de conhecimento RAG (`data/knowledge/`)** — é o dado mais valioso. Quanto mais tempo esse histórico existe, melhor o RAG: o agente reconhece padrões recorrentes e injeta contexto relevante nas análises. Contém exemplos curados pelo time (`examples/`) e runbooks gerados automaticamente (`runbooks/`).

**Store de runbooks (`_runbooks` dict)** — mapeamento `alert_id → (markdown, html)` usado pelo endpoint `GET /runbook/{alert_id}`. Persistir como arquivo JSON em disco resolve com zero dependência externa.

### Opções de persistência

**Opção A — PVC (PersistentVolumeClaim)**

Montar um PVC no path `data/` do container. A `KnowledgeBase` já escreve arquivos lá — persistiria automaticamente sem mudar uma linha de código.

```yaml
volumeMounts:
  - name: agent-data
    mountPath: /app/data
volumes:
  - name: agent-data
    persistentVolumeClaim:
      claimName: camunda-aiops-data
```

| Prós | Contras |
|---|---|
| Zero mudança no código | Requer Kubernetes (não funciona no `make run` local) |
| `KnowledgeBase` persiste automaticamente | Backup precisa de estratégia separada (Velero, snapshots) |
| Rollback simples: desmontar o PVC | `ReadWriteOnce` impede múltiplas réplicas no mesmo PVC |

**Opção B — SQLite**

Trocar o store em memória e os arquivos markdown por SQLite em `data/agent.db`. Permite TTL via `DELETE WHERE created_at < now() - interval`.

| Prós | Contras |
|---|---|
| TTL implementável por query SQL | Requer refactor do `KnowledgeBase` e `_runbooks` store |
| Arquivo único — backup trivial (`cp agent.db`) | Não escala para múltiplas réplicas sem migrar para PostgreSQL |
| Funciona local e no cluster | Overhead de desenvolvimento maior |

**Opção C — Object storage (S3 / MinIO)**

Escrever runbooks e base de conhecimento em bucket S3 ou MinIO local.

| Prós | Contras |
|---|---|
| Escala horizontalmente (múltiplas réplicas) | Latência maior (rede vs. disco local) |
| Políticas de ciclo de vida nativas (S3 Lifecycle) | Dependência externa — problema para ambiente air-gapped |
| Backup e versionamento nativos | Requer refactor do `KnowledgeBase` para client S3 |

### Política de retenção

Acumular runbooks indefinidamente gera ruído no RAG — runbooks de incidentes antigos podem contaminar o contexto injetado nas análises tanto quanto ajudar.

**Estratégia 1 — CronJob Kubernetes** (recomendada para começar)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: aiops-data-cleanup
spec:
  schedule: "0 2 * * 0"  # domingo às 02h
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: cleanup
              image: busybox
              command:
                - sh
                - -c
                - find /data/knowledge/runbooks -mtime +30 -name "*.md" -delete
          restartPolicy: OnFailure
```

Zero mudança no agente, operação declarativa em YAML, TTL ajustável. Contra: não distingue runbooks por severidade.

**Estratégia 2 — TTL no código (`KnowledgeBase`)**

Purga entradas mais antigas que `KNOWLEDGE_TTL_DAYS` ao carregar documentos. Permite lógica fina: `critical` → 90 dias, `warning` → 30 dias. Contra: acoplado ao código Python, TTL fica invisível para quem opera o cluster.

**Estratégia 3 — S3 Lifecycle Policy** (só se Opção C)

Subpastas por severidade com regras de expiração distintas: `runbooks/critical/` → 90 dias, `runbooks/warning/` → 30 dias. Política declarativa no próprio storage, sem código.

### Estimativa de volume

- Runbook médio: ~2–5 KB
- 10 alertas/dia × 30 dias × 5 KB = **~1,5 MB/mês**
- Com TTL de 90 dias: teto de ~4,5 MB para runbooks gerados

**O volume de dados é pequeno.** Um PVC de 1 Gi cobre anos de operação. A discussão sobre retenção é sobre higiene operacional e qualidade do RAG — não sobre custo de storage.

### Recomendação por horizonte

| Horizonte | Ação |
|---|---|
| Curto prazo | Montar volume local (`docker run -v ./data:/app/data`) — persiste sem Kubernetes |
| Médio prazo | PVC + CronJob no cluster — menor fricção, zero mudança de código |
| Longo prazo | SQLite (single-node) ou PostgreSQL/MinIO (multi-replica) + avaliar embeddings reais (pgvector, ChromaDB) |

---

## 2. Entender a projeção de alerta real

### Problema atual

O ciclo hoje é: `predict_linear` dispara alerta preditivo → agente analisa → notifica Teams. Mas o time não tem visibilidade sobre **quanto tempo depois o problema real ocorreu** — nem se ele chegou a ocorrer. Sem isso, não há como defender o valor do forecasting com dados: *"prevemos com X minutos de antecedência em Y% dos casos"*.

### O que seria necessário

Correlacionar o timestamp do alerta preditivo com o timestamp do alerta real correspondente (quando/se ele disparar). Isso exige:

1. **Identificar o par preditivo/real** — por exemplo, `ZeebeMemoryPredictedHigh` (preditivo) com `ZeebeMemoryHigh` (real, se existir). Requer convenção de nomenclatura ou anotação explícita nas PrometheusRules.
2. **Registrar timestamps** — quando o alerta preditivo disparou, quando o alerta real disparou (se disparou), e quando o problema foi resolvido.
3. **Calcular lead time** — diferença entre os dois timestamps. Essa é a métrica central: *"avisamos X minutos antes"*.
4. **Calcular taxa de acerto** — quantas vezes o preditivo disparou e o real veio a seguir vs. quantas vezes foi um falso positivo.

### Opções

**Opção A — Rastrear no próprio agente**

O webhook já recebe todos os alertas. O agente poderia identificar pares preditivo/real por convenção de nome (ex.: sufixo `Predicted` indica o preditivo do alerta sem sufixo) e registrar os timestamps em disco/banco.

| Prós | Contras |
|---|---|
| Sem dependência externa | Requer lógica de correlação no código Python |
| Dados disponíveis para o RAG | Convenção de nomenclatura precisa ser respeitada em todas as regras |

**Opção B — Recording rules no Prometheus**

Criar recording rules que capturam `ALERTS` ativos e registram o estado preditivo vs. real como séries temporais. O Grafana então exibe a correlação.

| Prós | Contras |
|---|---|
| Dados persistidos no próprio Prometheus (retenção configurável) | Requer que os alertas reais existam — hoje só os preditivos estão implementados |
| Dashboards nativos no Grafana | Correlação manual entre series pode ser complexa em PromQL |
| Zero mudança no código do agente | |

**Opção C — Anotações no Grafana**

O agente cria uma anotação no Grafana quando o alerta preditivo dispara e outra quando o real dispara. O dashboard exibe a linha do tempo visual com os dois eventos.

| Prós | Contras |
|---|---|
| Visualização imediata nos dashboards existentes | Anotações não são métricas — difíceis de agregar estatisticamente |
| API de anotações já disponível via MCP Grafana | Requer implementação no agente |

### Pré-requisito não trivial

Para medir acurácia, é necessário ter alertas *reais* correspondentes a cada alerta preditivo. Hoje as PrometheusRules do projeto são quase todas preditivas. Criar as versões "reais" (ex.: `ZeebeMemoryHigh` que dispara quando o heap *já está* alto, não quando está sendo previsto) é o primeiro passo — e por si só já é útil operacionalmente.

---

## 3. Filtrar alertas por label em vez de keyword ✅ Implementado

### Problema atual

O agente usa `ALERT_FILTER_KEYWORDS` para decidir quais alertas processar — uma lista de palavras testadas contra o nome do alerta (`Zeebe,Camunda,Kube,Elasticsearch`). É uma heurística frágil:

- Um alerta com nome inesperado (ex.: `WorkflowEngineBackpressure`) passa batido mesmo sendo relevante
- Um alerta não relacionado que contenha "Kube" entra no processamento
- Adicionar uma nova PrometheusRule requer lembrar de atualizar a variável de ambiente

### Comportamento implementado

A label controla o nível de processamento — todos os alertas chegam ao Teams:

```
agentia=true  → LLM analisa → card enriquecido (análise + runbook + RAG)
agentia=false → direto Teams → card com labels/annotations da própria regra
(ambos passam pela deduplicação por fingerprint)
```

### Proposta original

Usar uma label nas PrometheusRules para opt-in explícito:

```yaml
# PrometheusRule — o criador da regra decide conscientemente
groups:
  - name: zeebe.rules
    rules:
      - alert: ZeebeMemoryPredictedHigh
        expr: predict_linear(...)
        labels:
          severity: warning
          agentia: "true"   # ← opt-in para processamento pelo agente
```

O agente verificaria a presença de `agentia: "true"` no payload do Alertmanager em vez de (ou além de) checar keywords.

### Trade-offs

| Prós | Contras |
|---|---|
| Intenção explícita — quem cria a regra decide se o agente deve processar | Requer que toda PrometheusRule nova seja anotada conscientemente |
| Elimina falsos positivos e falsos negativos do filtro por keyword | PrometheusRules existentes precisam ser atualizadas retroativamente |
| Consistente com padrões do ecossistema (ServiceMonitor usa labels da mesma forma) | Se alguém esquecer a label, o alerta não é processado — silêncio pode ser confundido com "tudo certo" |
| O filtro por keyword vira fallback ou é removido | |

### Variação: label com nível de processamento

Em vez de booleano, a label poderia indicar o nível de processamento:

```yaml
labels:
  agentia: "full"      # análise completa + runbook + RAG
  # agentia: "triage"  # apenas triagem rápida, sem runbook
  # agentia: "skip"    # explicitamente excluído
```

Mais expressivo, mas aumenta a complexidade da lógica no agente.

---

## 4. Ampliar métricas internas do agente

### Contexto

A etapa 10 já implementou `GET /metrics` com 7 métricas Prometheus:

| Métrica atual | O que mede |
|---|---|
| `aiops_webhooks_total` | Webhooks recebidos por status HTTP |
| `aiops_alerts_processed_total` | Alertas processados por alertname e severidade |
| `aiops_alerts_filtered_total` | Alertas descartados pelo filtro de keywords |
| `aiops_alerts_deduplicated_total` | Alertas bloqueados por deduplicação |
| `aiops_analysis_duration_seconds` | Histograma de duração da análise (p50/p90/p99) |
| `aiops_llm_tool_calls_total` | Tool calls do LLM por nome de ferramenta |
| `aiops_teams_notifications_total` | Notificações enviadas ao Teams por status |

### O que o time pediu

Métricas que hoje não existem:

| Métrica desejada | Por que é útil |
|---|---|
| Queries Prometheus executadas por análise | Entender o "custo de investigação" de cada alerta |
| Timeouts do LLM | Identificar quando o modelo local está sobrecarregado ou lento demais |
| Timeouts de queries Prometheus | Identificar instabilidade no Prometheus durante análises |
| Projeções consultadas (`predict_linear` queries) | Separar queries de forecasting das queries de estado atual |
| Erros por tipo (LLM, Prometheus, Teams) | Hoje `aiops_webhooks_total` agrega tudo — granularidade maior facilita debugging |

### Opções de implementação

**Opção A — Adicionar Counters/Gauges ao `metrics.py`**

Incrementar contadores existentes em `reactive_agent.py` e `tools.py` nos pontos de timeout e erro.

```python
# Exemplo conceitual
LLM_TIMEOUTS = Counter("aiops_llm_timeouts_total", "Timeouts do LLM", ["model"])
PROMETHEUS_QUERIES = Counter("aiops_prometheus_queries_total", "Queries ao Prometheus", ["query_type"])
```

Mudança cirúrgica, sem dependência nova. Contra: requer identificar todos os pontos de timeout no código (LLM tem `--max-time` no curl, Prometheus tem timeout no client HTTP).

**Opção B — Middleware de instrumentação**

Envolver as chamadas LLM e Prometheus em decoradores que automaticamente registram duração, status e timeouts.

Mais elegante e menos propenso a esquecer pontos de instrumentação. Contra: adiciona uma camada de abstração que pode dificultar debugging.

**Opção C — OpenTelemetry**

Substituir `prometheus-client` direto por OpenTelemetry com exporter Prometheus. Permite traces distribuídos além de métricas — visibilidade end-to-end de cada análise (webhook → LLM → Prometheus → Teams).

| Prós | Contras |
|---|---|
| Traces mostram exatamente onde o tempo é gasto | Mudança significativa de infraestrutura de observabilidade |
| Padrão da indústria, compatível com Grafana Tempo | Overhead de configuração e dependências novas |
| Correlação automática entre métricas e traces | Overkill para o estágio atual do projeto |

### Recomendação

**Opção A** para as métricas pedidas pelo time — é incremental, não quebra nada, e entrega valor imediato. OpenTelemetry (Opção C) vale considerar se o projeto evoluir para múltiplos serviços ou se o time precisar debugar análises complexas com muitos tool calls.

---

## Resumo de priorização sugerida

| # | Item | Complexidade | Impacto | Pré-requisito |
|---|---|---|---|---|
| 1 | Label `agentia: true` nas PrometheusRules | ~~Baixa~~ | ~~Alto~~ | ✅ **Implementado** |
| 2 | Métricas de timeout e queries Prometheus | Baixa | Médio — melhora observabilidade | Nenhum |
| 3 | Persistência via volume local (docker) | Baixa | Alto — resolve perda de RAG no restart | Nenhum |
| 4 | Persistência via PVC + CronJob (Kubernetes) | Média | Alto — solução definitiva para o cluster | Deploy em K8s |
| 5 | Alertas reais correspondentes aos preditivos | Média | Alto — habilita medição de acurácia | Definir convenção de nomenclatura |
| 6 | Correlação preditivo/real + dashboard de acurácia | Alta | Alto — prova de valor do forecasting | Item 5 concluído |
