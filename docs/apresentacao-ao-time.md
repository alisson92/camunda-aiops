# camunda-aiops — Apresentação ao time

## O problema

Alertas reativos chegam **depois** do problema. Quando o heap do Zeebe atinge 92%
e o alerta dispara, o impacto já está acontecendo. O time recebe uma notificação,
abre o Grafana, tenta entender o que está acontecendo, e só então age.

Esse ciclo tem dois problemas:
1. **Tempo de resposta:** do alerta ao diagnóstico levam minutos que poderiam ser evitados
2. **Ruído cognitivo:** a pessoa que recebe o alerta precisa ter contexto do sistema para interpretá-lo

---

## A proposta

Antecipar o problema **antes** de acontecer e entregar a análise pronta no Teams.

```
Prometheus (prevê o problema 15 min antes)
    ↓ alerta preditivo
Alertmanager
    ↓ webhook
Agente Python (consulta métricas reais → analisa com LLM local)
    ↓
Microsoft Teams (card com diagnóstico + runbook + botões de ação)
```

Ninguém precisa abrir o Grafana. A análise chega no canal onde o time já está.

---

## Como funciona — três camadas

### 1. Forecasting com PromQL

Em vez de alertar quando o problema já ocorreu, as regras projetam onde a métrica
vai estar no futuro:

```promql
predict_linear(
  container_memory_working_set_bytes{pod=~"camunda-zeebe-.*"}[30m],
  900   -- daqui a 15 minutos
) > 0.85 * limite
```

**Regra do 2:1:** a janela de observação sempre tem o dobro do horizonte projetado.
Janela de 30 min → projeção máxima de 15 min. Fora dessa proporção, a projeção
fica instável.

Três técnicas usadas:
- `predict_linear` — crescimento monotônico (disco, filas, RocksDB)
- `deriv` — detecta aceleração antes do pico (backpressure)
- `histogram_quantile` — latência p99 do gateway gRPC do Zeebe

### 2. Agente reativo com LLM local

O agente recebe o alerta e age em loop:
1. Consulta métricas reais do Prometheus (queries pré-definidas em `tools.py`)
2. Passa os dados para o LLM junto com o system prompt
3. Se o LLM pedir mais dados, executa a tool e volta ao passo 2
4. Quando o LLM tem informação suficiente, gera a análise final
5. Chama o LLM uma segunda vez para gerar o runbook em Markdown

O LLM usado é o **Ollama local** (`qwen2.5:7b`). Nenhum dado sai da rede —
ciclo 100% air-gapped. Trocar o modelo é mudar duas variáveis de ambiente.

### 3. Notificação no Teams com ações

O card entregue no Teams contém:
- **Severidade e urgência** (Imediata / Alta / Moderada)
- **Causa raiz** identificada pelo agente
- **Ações recomendadas** com comandos prontos
- **Análise completa** expansível (accordion)
- Botões: **📖 Runbook** · **📊 Dashboard** · **🔕 Silence 1h**

O runbook é gerado automaticamente pelo LLM após cada análise e fica acessível
via URL estática por nome de alerta — funciona após restart do agente.

---

## O que já está coberto

### Alertas como IaC (7 arquivos PrometheusRule)

| Arquivo | O que monitora |
|---|---|
| `camunda-forecasting-rules.yaml` | Heap Zeebe, backpressure, memória do namespace |
| `camunda-latency-rules.yaml` | Latência p99 do gateway gRPC |
| `camunda-storage-rules.yaml` | Disco do PVC do Zeebe (RocksDB) |
| `elasticsearch-rules.yaml` | Saúde do cluster + shards não alocados |
| `kubernetes-node-rules.yaml` | Condições adversas de nó |
| `kubernetes-pod-rules.yaml` | NotReady, HighMemory/CPU, CrashLoop, OOM |
| `kubernetes-camunda-ns-rules.yaml` | PVC errors, StatefulSet rollout travado |

Todos aplicáveis com `kubectl apply -f alerting/`.

### Dashboards Grafana (2)

| Dashboard | URL | O que mostra |
|---|---|---|
| Camunda Forecasting | `http://localhost:3000/d/camunda-local-forecasting/` | Projeções de heap, backpressure, disco, latência p99 |
| Agent Observability | `http://localhost:3000/d/camunda-aiops-agent/` | Webhooks recebidos, duração das análises, notificações Teams |

### Qualidade

- **219 testes unitários**, 100% de cobertura (`fail_under = 100`)
- **7 testes de integração** — `tools.py` contra Prometheus real (Testcontainers)
- **3 testes E2E** — ciclo completo: webhook → agente → Prometheus real → LLM mock → Teams mock
- **CI com 5 jobs** em sequência — cada camada só roda se a anterior passou

---

## Decisões técnicas relevantes

**Por que Ollama e não Claude/GPT?**
Dados de observabilidade são sensíveis. Com LLM local, nenhum dado sai da rede.
A interface é compatível com OpenAI — trocar o modelo é só mudar `OLLAMA_BASE_URL`
e `OLLAMA_MODEL` no `.env`.

**Por que `runbook_url` aponta para o próprio agente?**
Em produção não existem URLs externas acessíveis. O endpoint
`GET /runbook/by-alert/{alertname}` serve o runbook mais recente gerado para
aquele alerta, sem depender de GitHub, Confluence ou qualquer serviço externo.

**Por que 100% de cobertura é obrigatória?**
Não é vaidade de métrica. É a garantia de que cada branch de código foi exercido
por um teste. Qualquer linha nova sem teste bloqueia o merge via CI.

**O que é o `alert_id` nos logs?**
Cada ciclo de análise recebe um ID de 8 caracteres (`uuid4().hex[:8]`). Todas as
linhas de log daquele ciclo carregam esse ID — um `grep alert_id` mostra exatamente
o que aconteceu, do recebimento do webhook até o card no Teams.

---

## Para explorar no repositório

```
CONTRIBUTING.md              → padrões, fluxo de contribuição, convenções
alerting/                    → PrometheusRules prontas para kubectl apply
prompts/system-prompt-v2.md  → o prompt que guia o agente
agent/tools.py               → queries Prometheus disponíveis para o LLM
agent/knowledge_base.py      → few-shot + RAG com histórico de incidentes
docs/                        → documentação por etapa e decisões técnicas
```

---

## Próximos passos planejados

| # | O que | Por que |
|---|---|---|
| 13 | Sazonalidade com Prophet | `predict_linear` não entende picos de segunda/sexta — gera falsos positivos após semanas de histórico |
| 14 | Dashboards dinâmicos | Agente cria painéis Grafana automaticamente para alertas sem dashboard |
| 15 | PromQL por linguagem natural | "Qual a taxa de erro dos conectores nas últimas 2h?" → agente gera e executa a query |
| 16 | Ações corretivas com aprovação | Agente propõe `kubectl rollout restart` ou ajuste de HPA — executa só após aprovação no card Teams |
