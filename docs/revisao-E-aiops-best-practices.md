---
titulo: Revisão E — AIOps best practices
data: 2026-05-25
status: concluída
tipo: revisao
---

# Revisão E — AIOps best practices

## Por que esta revisão foi realizada

Com o ciclo AIOps completo (forecasting → alerta → análise LLM → notificação), o projeto
precisava de uma auditoria para verificar se os padrões de observabilidade e resiliência do
próprio agente estavam à altura do que o mercado considera referência para sistemas de automação
operacional.

---

## Diagnóstico: o que foi auditado

| Prática | Estado antes | Conclusão |
|---|---|---|
| Observabilidade do agente (`/metrics`) | ✅ Implementado (Etapa 10) | OK |
| Dashboard Grafana do agente | ✅ Implementado (Etapa 10) | OK |
| Runbook automático pós-análise | ✅ Implementado (Etapa 11) | OK |
| RAG / few-shot com histórico | ✅ Implementado (Etapa 12) | OK |
| PrometheusRules como IaC | ✅ Implementado (Etapa 1) | OK |
| Silenciar alerta via Teams | ✅ Implementado (Etapa 5) | OK |
| Correlation ID por análise | ❌ Ausente | **Implementado** |
| Métrica de rodadas do LLM | ❌ Ausente | **Implementado** |
| Runbook acessível após restart | ❌ Bug | **Corrigido** |
| `/health` com estado da KB | ❌ Ausente | **Implementado** |
| JSON structured logging | ⚠️ Avaliado | Descartado — ver decisão abaixo |
| Circuit breaker para Ollama | ⚠️ Avaliado | Descartado — ver decisão abaixo |
| Alert deduplication | ⚠️ Avaliado | Descartado — ver decisão abaixo |

---

## O que foi implementado e por quê

### 1. Correlation ID por análise

**Problema:** quando múltiplos alertas chegam simultaneamente, os logs do agente se
entrelaçam e é impossível determinar quais linhas pertencem a qual alerta.

**Solução:** cada alerta processado recebe um ID de correlação de 8 hex chars
(`uuid.uuid4().hex[:8]`). Todas as linhas de log do ciclo daquele alerta incluem `[{alert_id}]`.

```
[a1b2c3d4] Alerta recebido: ZeebeMemoryPredictedHigh | status: firing
[a1b2c3d4] KB: 2 doc(s) relevante(s)
[a1b2c3d4] Iniciando análise: alerta=ZeebeMemoryPredictedHigh status=firing modelo=qwen2.5:7b
[a1b2c3d4] Ferramenta: query_prometheus_instant({"expr": "jvm_memory_used_bytes..."})
[a1b2c3d4] Análise concluída em 2 rodada(s).
[a1b2c3d4] Runbook armazenado: id=zeebe-memory-aabbccdd
```

**Arquivos alterados:** `webhook_receiver.py` (geração do ID, propagação nos logs),
`reactive_agent.py` (parâmetro `alert_id`, logs com prefixo).

---

### 2. Métrica `aiops_llm_rounds_used` (Histogram)

**Problema:** o agente monitorava chamadas de ferramentas (`aiops_llm_tool_calls_total`) e
duração total da análise (`aiops_analysis_duration_seconds`), mas nunca instrumentava quantas
rodadas de tool use cada análise consumia. Esta métrica é fundamental para:
- Detectar quando o modelo entra em loops (muitas rodadas = possível problema de prompt)
- Tuning do `MAX_TOOL_ROUNDS` com base em dados reais
- Comparar comportamento entre modelos

**Solução:** `LLM_ROUNDS_USED = Histogram("aiops_llm_rounds_used", ..., buckets=[1,2,3,4,5,6])`
observado com `LLM_ROUNDS_USED.observe(round_n + 1)` no momento em que o agente recebe
`finish_reason == "stop"`.

**Arquivos alterados:** `metrics.py` (nova métrica), `reactive_agent.py` (observe no stop).

---

### 3. Fix: runbook reload no startup

**Problema (bug real):** `_runbooks` é um dict in-memory em `webhook_receiver.py`. Após
restart do agente, todos os botões "📖 Runbook" nos cards do Teams retornavam HTTP 404.
A `KnowledgeBase` já persistia os runbooks em disco, mas eles nunca eram recarregados para o
dict de serve.

**Solução:** após `_kb = KnowledgeBase()` no startup, o dict é populado a partir do KB:

```python
_runbooks.update({
    doc_id: (doc.alert_name, doc.content)
    for doc_id, doc in _kb.get_runbooks().items()
})
```

O novo método público `KnowledgeBase.get_runbooks()` retorna apenas documentos com
`source == "generated"` (runbooks produzidos pelo agente — não os exemplos curados).

**Arquivos alterados:** `knowledge_base.py` (método `get_runbooks()`),
`webhook_receiver.py` (reload no startup).

---

### 4. `/health` enriquecido com estado da KnowledgeBase

**Problema:** `/health` retornava apenas `{"status":"ok", "timestamp":"..."}`. Um health check
sem contexto do sistema não permite entender se o agente está realmente operacional.

**Solução:** adicionado campo `knowledge_base.documents` — número total de documentos
carregados (exemplos curados + runbooks gerados). Não envolve chamadas HTTP externas;
o valor é lido diretamente de `len(_kb)`.

```json
{
  "status": "ok",
  "timestamp": "2026-05-25T14:30:00Z",
  "knowledge_base": {"documents": 4}
}
```

**Arquivo alterado:** `webhook_receiver.py`.

---

## O que foi avaliado e descartado

**JSON structured logging:** adicionaria a dependência `python-json-logger` ou similar e
exigiria refatoração do formatter em `config.py`. Para um lab air-gapped sem agregador de logs
(Loki, ELK), o custo supera o benefício. Se o projeto migrar para produção com stack de logs,
essa seria a primeira mudança a fazer.

**Circuit breaker para Ollama:** tornaria o agente resiliente a falhas momentâneas do Ollama,
mas exigiria biblioteca (`tenacity` ou `circuitbreaker`) ou implementação manual de state machine.
O lab não tem SLA; uma falha do Ollama é visível nos logs imediatamente.

**Alert deduplication:** evitaria analisar o mesmo alerta múltiplas vezes em janelas curtas.
Requer estado compartilhado (TTL cache) e lógica de hash de payload. Adicionaria complexidade
sem benefício visível na demo ao time.

---

## Resultado

| Métrica | Antes | Depois |
|---|---|---|
| Testes unitários | 202 | 213 ✅ |
| Cobertura | 100% | 100% ✅ |
| Métricas do agente | 6 | 7 (+ `aiops_llm_rounds_used`) |
| Bug de runbook pós-restart | ❌ | ✅ corrigido |
| Correlation ID nos logs | ❌ | ✅ todos os ciclos |
| `/health` com contexto | ❌ | ✅ KB document count |
