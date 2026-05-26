# Arquitetura de Componentes — camunda-aiops

Visão geral de todos os componentes do sistema e como eles se conectam.

```mermaid
graph TB
    subgraph K8S["☸ Kubernetes (Kind local)"]
        CAMUNDA["Camunda 8.9\nZeebe · Gateway · Connectors\nIdentity · Operate · Web Modeler"]
        PROM["Prometheus\n+ kube-prometheus-stack"]
        AM["Alertmanager"]
        RULES["PrometheusRules\n7 arquivos / 23 alertas\n(predict_linear · deriv · histogram_quantile)"]
    end

    subgraph AGENT["🤖 Agente AIOps (Python / FastAPI)"]
        WH["webhook_receiver\nPOST /webhook\nGET /health · /metrics · /runbook"]
        DEDUP["Deduplicação\nfingerprint + TTL 5min"]
        RA["reactive_agent\nReAct loop"]
        TOOLS["tools\nquery_prometheus_instant\nquery_prometheus_range\nget_alert_rules"]
        KB["KnowledgeBase\nRAG + few-shot\nexemplos curados + runbooks"]
        RB["runbook_generator\nMarkdown → HTML"]
        TN["teams_notifier\nAdaptive Card v1.2"]
        METRICS["metrics\nPrometheus client\naiops_* counters + histograms"]
    end

    subgraph LLM["🧠 LLM Local (Ollama)"]
        OLLAMA["qwen2.5:7b\n(ou modelo configurado)"]
    end

    subgraph OBS["📊 Observabilidade"]
        GRAFANA["Grafana\ncamunda-forecasting\ncamunda-aiops-agent"]
    end

    TEAMS["💬 Microsoft Teams\nAdaptive Card\n+ botões de ação"]

    %% Fluxo de dados principal
    CAMUNDA -->|"métricas /actuator/prometheus"| PROM
    PROM -->|"avalia PrometheusRules"| RULES
    RULES -->|"threshold atingido"| AM
    AM -->|"POST /webhook"| WH
    WH --> DEDUP
    DEDUP -->|"BackgroundTask"| RA
    RA <-->|"tool_call"| TOOLS
    TOOLS <-->|"HTTP API"| PROM
    RA <-->|"OpenAI-compatible API"| OLLAMA
    KB -->|"contexto histórico"| RA
    RA -->|"análise"| RB
    RB -->|"runbook_url"| TN
    TN -->|"POST webhook"| TEAMS

    %% Observabilidade
    WH -->|"instrumentação"| METRICS
    METRICS -->|"GET /metrics"| GRAFANA
    PROM --> GRAFANA

    %% Estilos
    style K8S fill:#e8f4f8,stroke:#2196F3,color:#000
    style AGENT fill:#f3e8f8,stroke:#9C27B0,color:#000
    style LLM fill:#fff3e0,stroke:#FF9800,color:#000
    style OBS fill:#e8f5e9,stroke:#4CAF50,color:#000
    style TEAMS fill:#e3f2fd,stroke:#1565C0,color:#000
```

---

## Decisões arquiteturais relevantes

| Decisão | Justificativa |
|---|---|
| **Vendor neutrality (SDK OpenAI)** | Trocar o LLM exige apenas 2 variáveis de ambiente — sem mudança de código |
| **Webhook assíncrono (202)** | Alertmanager recebe confirmação imediata; LLM processa em background sem travar a fila |
| **Deduplicação por fingerprint** | Evita análises repetidas durante `repeatInterval` do Alertmanager |
| **RAG sem vetordb** | `KnowledgeBase` própria com scoring por sobreposição de tokens — zero dependência externa |
| **Prometheus client no agente** | O próprio agente expõe métricas — observabilidade da camada AIOps sem infraestrutura adicional |
