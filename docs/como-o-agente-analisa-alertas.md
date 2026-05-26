# Como o Agente Analisa um Alerta

**Público:** time de engenharia — apresentação e debate técnico  
**Objetivo:** entender o que acontece "por baixo dos panos" quando um alerta chega

---

## A pergunta central

> *"O agente simplesmente manda o alerta para o LLM e pede uma análise genérica?"*

Não. O agente usa um padrão chamado **ReAct** (Reasoning + Acting) — ele não responde direto. Ele primeiro *raciocina sobre quais dados precisa*, *busca esses dados em tempo real*, e *só então conclui a análise*.

---

## Passo a passo do que acontece

### 1. Alerta chega no webhook

O Alertmanager envia um payload JSON com:

- `alertname` — nome da regra disparada (ex: `ZeebeMemoryPredictedHigh`)
- `labels` — namespace, pod, severidade
- `annotations` — summary e description definidos na PrometheusRule

Isso é tudo que vem "de fora". O agente ainda não sabe o estado real da métrica.

---

### 2. Agente monta o contexto

Antes de chamar o LLM, o agente reúne três camadas de informação:

```
┌─────────────────────────────────────────────────────────┐
│ System prompt                                           │
│   Instruções: formato da análise, campos obrigatórios, │
│   idioma, como classificar urgência                     │
├─────────────────────────────────────────────────────────┤
│ Contexto RAG (KnowledgeBase)                           │
│   Histórico do time: runbooks de análises anteriores   │
│   do mesmo tipo de alerta + exemplos curados           │
│   (se existirem)                                       │
├─────────────────────────────────────────────────────────┤
│ Mensagem do alerta                                      │
│   alertname, labels, annotations, status               │
│   (firing / resolved)                                  │
└─────────────────────────────────────────────────────────┘
```

O contexto histórico (RAG) é o que permite que análises melhorem com o tempo — cada runbook gerado vira referência para os próximos alertas do mesmo tipo.

---

### 3. Primeira chamada ao LLM — "O que eu preciso saber?"

Com o contexto montado, o LLM recebe a pergunta e decide que precisa de dados reais antes de concluir qualquer coisa. Ele responde com uma **tool call** — uma instrução para o agente executar:

```json
{
  "tool": "query_prometheus_instant",
  "arguments": {
    "expr": "jvm_memory_used_bytes{namespace='camunda', pod='camunda-zeebe-0'}"
  }
}
```

O LLM escolhe **sozinho** qual métrica consultar, com base no nome do alerta e no que sabe sobre Zeebe e Kubernetes. As ferramentas disponíveis são:

| Ferramenta | O que faz |
|---|---|
| `query_prometheus_instant` | Valor atual de uma métrica (ponto no tempo) |
| `query_prometheus_range` | Série temporal — evolução da métrica nos últimos N minutos |
| `get_alert_rules` | Lista as PrometheusRules ativas para o componente |

---

### 4. Agente executa a ferramenta — dados reais do Prometheus

O agente faz uma chamada HTTP real para o Prometheus e devolve o resultado para o LLM:

```
resultado: 530 MB  ←  jvm_memory_used_bytes{pod="camunda-zeebe-0"}
```

Não é um valor estimado. É o dado real, coletado no momento em que o alerta foi recebido.

---

### 5. Segunda chamada ao LLM — "O que isso significa?"

Agora o LLM tem tudo: o alerta + o contexto histórico + os dados reais do Prometheus. Com isso ele gera a análise final:

```
CAUSA_RAIZ:
  Heap G1 Old Gen crescendo continuamente — possível vazamento de memória
  em processamento de instâncias BPMN longas ou acúmulo de jobs pendentes.

URGÊNCIA: Alta (< 1h)

MÉTRICAS_COLETADAS:
  - jvm_memory_used_bytes: 530 MB (limite Xmx: 614 MB — 86% ocupado)
  - tendência: +2 MB/min nos últimos 15 minutos

RECOMENDAÇÃO:
  1. Verificar jobs BPMN em estado "STUCK" ou com retry loop
  2. Forçar GC: kubectl exec camunda-zeebe-0 -- jcmd 1 GC.run
  3. Se não resolver: restart fora do horário de pico com PodDisruptionBudget
```

---

### 6. Runbook gerado automaticamente

Uma terceira chamada ao LLM gera um runbook Markdown com:

- Contexto do alerta
- Passos de investigação (o que checar primeiro)
- Passos de remediação (o que fazer)
- Como prevenir recorrência

Disponível em tempo real em:
```
GET /runbook/by-alert/ZeebeMemoryPredictedHigh
```

O link já vem no card do Teams — qualquer pessoa do time consegue acessar sem precisar de acesso ao cluster.

---

### 7. Card chega no Microsoft Teams

O card reúne tudo em um único lugar:

```
🚨 ZeebeMemoryPredictedHigh — FIRING [WARNING]
────────────────────────────────────────────────
Namespace: camunda | Pod: camunda-zeebe-0

▼ Análise do Agente
  CAUSA_RAIZ: Heap G1 Old Gen crescendo — possível vazamento...
  URGÊNCIA: Alta (< 1h)
  MÉTRICAS: 530 MB / 614 MB (86%)
  RECOMENDAÇÃO: Verificar jobs STUCK...

[📊 Dashboard]  [📖 Runbook]  [🔕 Silence 1h]
```

---

## Fluxo completo — visão de sistema

```
Prometheus detecta threshold preditivo (predict_linear)
    ↓
Alertmanager dispara webhook
    ↓
webhook_receiver (retorna 202 imediatamente — Alertmanager não bloqueia)
    ↓ background
KnowledgeBase → busca histórico relevante do mesmo tipo de alerta
    ↓
LLM (rodada 1) → "Preciso dos dados reais. Vou consultar o Prometheus."
    ↓ tool_call
Prometheus → retorna valor atual da métrica
    ↓
LLM (rodada 2) → "Com 530 MB / 614 MB e tendência crescente, a causa é X"
    ↓ análise final
LLM (rodada 3) → gera runbook Markdown com passos de remediação
    ↓
Microsoft Teams ← card com análise + link do runbook + botões de ação
```

---

## O que diferencia de um alerta tradicional

| Alerta tradicional | Com o agente AIOps |
|---|---|
| "Heap > 85%" — você ainda precisa investigar | Dado real já no card: "530 MB de 614 MB, +2 MB/min" |
| Causa identificada manualmente, depois do fato | Causa provável já identificada com contexto histórico |
| Runbook manual, desatualizado ou inexistente | Runbook gerado automaticamente, específico para aquele momento |
| Engenheiro decide o próximo passo | Recomendação concreta já no card, pronta para executar |
| Alerta reativo — problema já aconteceu | Alerta preditivo — `predict_linear` avisa 15 min antes |

---

## O que o agente NÃO faz

É importante ser honesto sobre os limites:

- **Não executa remediação automática** — recomenda, mas a ação é sempre humana
- **Não tem acesso ao cluster** — lê métricas do Prometheus, não executa `kubectl`
- **Pode errar** — se o LLM não tiver contexto suficiente ou a métrica consultada for insuficiente, a análise pode ser genérica; o histórico RAG melhora isso com o tempo
- **Depende da qualidade das PrometheusRules** — uma regra mal calibrada gera alertas imprecisos que o LLM não consegue compensar

---

## Por que o modelo roda local (sem custo de cloud)

O LLM (`qwen2.5:7b`) roda localmente via Ollama:

- **Sem custo por token** — nenhuma chamada para OpenAI, Anthropic ou similar
- **Air-gapped** — dados de produção não saem da infraestrutura
- **Sem dependência externa** — funciona mesmo sem acesso à internet
- **Tradeoff:** mais lento que cloud (~30–60s por análise vs ~2–5s) — gargalo em investigação, documentado em [`analise-llm-local-desempenho.md`](analise-llm-local-desempenho.md)
