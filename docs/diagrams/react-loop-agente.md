# ReAct Loop — Raciocínio Interno do Agente

Como o agente decide o que consultar, executa as ferramentas e chega à análise final.  
**ReAct = Reasoning + Acting** — o modelo raciocina sobre o que precisa e age para buscar.

```mermaid
flowchart TD
    START(["Alerta recebido\nalertname · labels · annotations"])

    subgraph CONTEXT["Montagem do contexto"]
        SP["System prompt\n(formato, urgência, idioma)"]
        RAG["KnowledgeBase\nhistórico do mesmo alertname\nexemplos curados do time"]
        MSG["Mensagem do alerta\nalertname · labels · annotations · status"]
    end

    LLM1["🧠 LLM — Rodada 1\n'Qual dado real preciso\npara analisar isso?'"]

    DECISION{{"Resposta\ndo LLM"}}

    subgraph TOOLS["Execução da ferramenta"]
        T1["query_prometheus_instant\nvalor atual da métrica"]
        T2["query_prometheus_range\nsérie temporal (últimos N min)"]
        T3["get_alert_rules\nPrometheusRules ativas"]
    end

    PROM[("Prometheus\nHTTP API")]

    LLM2["🧠 LLM — Rodada 2\n'Com os dados reais,\nqual é a causa e\no que fazer?'"]

    ANALYSIS["Análise final\nCAUSA_RAIZ · URGÊNCIA\nMÉTRICAS_COLETADAS · RECOMENDAÇÃO"]

    RUNBOOK["🧠 LLM — Rodada 3\nGeração do runbook\n(passos de investigação\ne remediação)"]

    END(["Análise + Runbook\nprontos para o Teams"])

    LOOP{{"Mais dados\nnecessários?\n(máx. 5 rodadas)"}}

    START --> CONTEXT
    SP --> LLM1
    RAG --> LLM1
    MSG --> LLM1

    LLM1 --> DECISION

    DECISION -->|"tool_call\n(precisa de dados)"| TOOLS
    T1 & T2 & T3 <-->|"HTTP GET"| PROM
    TOOLS -->|"resultado da consulta"| LOOP

    LOOP -->|"Sim — nova tool_call"| LLM1
    LOOP -->|"Não — dados suficientes"| LLM2

    DECISION -->|"stop\n(resposta direta)"| LLM2

    LLM2 --> ANALYSIS
    ANALYSIS --> RUNBOOK
    RUNBOOK --> END

    %% Estilos
    style CONTEXT fill:#e8f4f8,stroke:#2196F3,color:#000
    style TOOLS fill:#fff3e0,stroke:#FF9800,color:#000
    style LLM1 fill:#f3e8f8,stroke:#9C27B0,color:#000
    style LLM2 fill:#f3e8f8,stroke:#9C27B0,color:#000
    style RUNBOOK fill:#f3e8f8,stroke:#9C27B0,color:#000
    style PROM fill:#e8f5e9,stroke:#4CAF50,color:#000
    style DECISION fill:#fff9c4,stroke:#F9A825,color:#000
    style LOOP fill:#fff9c4,stroke:#F9A825,color:#000
```

---

## Por que esse padrão importa

**Sem ReAct (resposta genérica):**
```
Alerta: "Heap JVM alto"
LLM responde: "Possível problema de memória. Considere reiniciar o pod."
→ Inútil. Não tem dados reais. Poderia ser qualquer alerta.
```

**Com ReAct (dados reais):**
```
Alerta: "Heap JVM alto"
LLM pensa: "Preciso do valor atual do heap e da tendência."
LLM consulta: jvm_memory_used_bytes{pod="camunda-zeebe-0"} → 530 MB
LLM analisa: "530 de 614 MB (86%), crescendo +2 MB/min há 15 min.
              Padrão típico de jobs BPMN presos em retry loop."
LLM recomenda: passos específicos para aquele pod, naquele momento.
→ Acionável. Baseado em evidência.
```

## Limite de rodadas

O loop tem um máximo de **5 rodadas** (`MAX_TOOL_ROUNDS` em `reactive_agent.py`).  
Se o LLM continuar pedindo dados após o limite, o agente encerra com a análise parcial disponível.  
O histograma `aiops_llm_rounds_used` no dashboard mostra quantas rodadas cada análise usou.
