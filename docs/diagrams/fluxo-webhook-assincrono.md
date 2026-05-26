# Fluxo do Webhook Assíncrono

Por que o Alertmanager não fica travado e o que acontece em background.

```mermaid
sequenceDiagram
    autonumber

    participant AM as Alertmanager
    participant WH as webhook_receiver
    participant BG as BackgroundTask<br/>(mesmo processo)
    participant LLM as LLM (Ollama)
    participant TEAMS as Teams

    Note over AM,WH: ── Caminho síncrono (rápido) ──────────────────

    AM->>WH: POST /webhook
    Note over WH: 1. Valida JSON
    Note over WH: 2. Filtra por ALERT_FILTER_KEYWORDS (~0ms)
    Note over WH: 3. Verifica fingerprint no _dedup_cache (~0ms)
    WH-->>AM: 202 Accepted {"queued": 1}
    Note over AM: ✔ Alertmanager livre<br/>para receber próximos alertas

    Note over WH,TEAMS: ── Caminho assíncrono (background) ──────────

    WH->>BG: background_tasks.add_task(_process_alert)

    BG->>LLM: chamada 1 — tool_call (qual métrica consultar?)
    LLM-->>BG: query_prometheus_instant(expr=...)
    BG->>BG: executa tool → consulta Prometheus
    BG->>LLM: chamada 2 — análise final com dados reais
    LLM-->>BG: CAUSA_RAIZ · URGÊNCIA · RECOMENDAÇÃO
    BG->>LLM: chamada 3 — gera runbook markdown
    LLM-->>BG: passos de investigação e remediação
    BG->>TEAMS: POST webhook (Adaptive Card)
    TEAMS-->>BG: 200 OK

    Note over BG: Duração total: 30–90s<br/>(LLM local) ou 5–10s (LLM cloud)
```

---

## Comparativo: antes e depois

```mermaid
sequenceDiagram
    participant AM as Alertmanager
    participant WH as webhook_receiver
    participant LLM as LLM

    Note over AM,LLM: ── ANTES (síncrono) ──────────────────────────────

    AM->>WH: POST /webhook
    WH->>LLM: análise... (30–90s bloqueado)
    LLM-->>WH: análise pronta
    WH-->>AM: 200 OK
    Note over AM: Alertmanager esperou<br/>30–90s por alerta<br/>❌ timeout em volume alto<br/>❌ reenvios em cascata

    Note over AM,LLM: ── DEPOIS (assíncrono) ───────────────────────────

    AM->>WH: POST /webhook
    WH-->>AM: 202 Accepted (< 1ms)
    Note over AM: Alertmanager livre imediatamente
    Note over WH,LLM: análise ocorre em background...
    Note over WH: ✔ sem timeout<br/>✔ sem reenvios em cascata<br/>✔ escala com volume
```

---

## Deduplicação por fingerprint

O Alertmanager reenvia o mesmo alerta a cada `repeatInterval` (padrão: 5 min).  
Sem deduplicação, cada reenvio dispararia uma nova análise LLM.

```mermaid
flowchart LR
    A1["Alerta FIRING\n(1ª vez)\nfingerprint: abc123"]
    A2["Alerta FIRING\n(2ª vez — repeatInterval)\nfingerprint: abc123"]
    A3["Alerta RESOLVED\nfingerprint: abc123"]

    CACHE[("_dedup_cache\nabc123 → timestamp")]

    PROCESS1["✔ Processa\nanalisa + Teams"]
    SKIP["⏭ Ignora\n(dentro do TTL de 5min)"]
    PROCESS3["✔ Processa\n(resolved nunca é ignorado)"]

    A1 -->|"fingerprint novo"| CACHE
    CACHE --> PROCESS1

    A2 -->|"fingerprint já existe\n(TTL não expirou)"| SKIP

    A3 -->|"status=resolved\nbypassa TTL"| PROCESS3
```
