# Fluxo Completo do Alerta

Do forecasting preditivo no Prometheus até o card de análise no Microsoft Teams.

```mermaid
sequenceDiagram
    autonumber

    participant APP as Camunda 8<br/>(Zeebe / pods)
    participant PROM as Prometheus
    participant AM as Alertmanager
    participant WH as webhook_receiver
    participant KB as KnowledgeBase
    participant LLM as LLM (Ollama)
    participant RB as runbook_generator
    participant TEAMS as Microsoft Teams

    Note over PROM: Avalia PrometheusRules a cada 30s

    APP->>PROM: métricas /actuator/prometheus
    PROM->>PROM: predict_linear(jvm_memory[30m], 900) > 0.85
    Note over PROM: threshold preditivo atingido<br/>15 minutos antes do problema real

    PROM->>AM: alerta FIRING
    AM->>WH: POST /webhook (payload JSON)
    WH-->>AM: 202 Accepted (< 1ms)
    Note over WH: filtro por keywords ✓<br/>deduplicação por fingerprint ✓<br/>BackgroundTask enfileirada

    Note over WH,TEAMS: processamento em background — Alertmanager já foi liberado

    WH->>KB: busca histórico do alertname
    KB-->>WH: runbooks anteriores + exemplos curados

    WH->>LLM: [system prompt] + [contexto RAG] + [alerta]
    Note over LLM: "Preciso dos dados reais<br/>antes de concluir"
    LLM-->>WH: tool_call: query_prometheus_instant(expr=...)

    WH->>PROM: GET /api/v1/query?query=jvm_memory_used_bytes{...}
    PROM-->>WH: 530 MB (valor real, instante atual)

    WH->>LLM: [conversa anterior] + [resultado: 530 MB]
    Note over LLM: "530 MB de 614 MB, +2 MB/min.<br/>Causa: heap G1 Old Gen crescendo"
    LLM-->>WH: análise final (CAUSA_RAIZ · URGÊNCIA · MÉTRICAS · RECOMENDAÇÃO)

    WH->>RB: generate_runbook(alertname, análise)
    RB->>LLM: prompt de geração de runbook
    LLM-->>RB: markdown com passos de investigação e remediação
    RB-->>WH: runbook_id + URL (GET /runbook/by-alert/ZeebeMemoryPredictedHigh)

    WH->>TEAMS: POST webhook (Adaptive Card)
    TEAMS-->>WH: 200 OK

    Note over TEAMS: Card entregue com:<br/>análise · link runbook · botões de ação
```

---

## Pontos-chave do fluxo

**Forecasting vs reativo:**  
O alerta é disparado por `predict_linear` — o Prometheus projeta que a métrica vai ultrapassar o threshold em 15 minutos, não que já ultrapassou. O time recebe o aviso *antes* do problema.

**202 imediato:**  
O Alertmanager recebe a confirmação em menos de 1ms. O processamento (LLM + Prometheus + Teams) acontece depois, em background. O Alertmanager nunca fica esperando o LLM terminar.

**Dados reais, não estimativas:**  
O valor "530 MB" no card não é inventado pelo LLM — é o dado coletado do Prometheus no momento do alerta (passo 10). O LLM usa esse dado para fundamentar a análise.

**RAG melhora com o tempo:**  
Cada runbook gerado (passo 14) é armazenado na `KnowledgeBase`. Na próxima ocorrência do mesmo alerta, o agente já tem o histórico de análises anteriores como referência.
