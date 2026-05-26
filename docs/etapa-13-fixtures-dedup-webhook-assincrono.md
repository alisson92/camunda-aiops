# Etapa 13 — Fixtures Dinâmicos, Deduplicação por Fingerprint e Webhook Assíncrono

**Versão:** 0.14.0  
**Data:** 2026-05-26  
**Motivação:** A demo disparava apenas 4 alertas hardcoded; re-disparos do mesmo alerta chegavam ao LLM repetidamente; o Alertmanager aguardava o LLM terminar antes de receber confirmação.

---

## Problema

Três limitações independentes foram identificadas durante a evolução do modo demo:

1. **Fixtures hardcoded:** `demo.sh` referenciava 4 arquivos por nome fixo. Cada novo alerta adicionado ao `alerting/` exigia edição manual do script — fraturava o ciclo IaC→alerta→demo.

2. **Sem deduplicação no agente:** O Alertmanager reenvia o mesmo alerta em cada `repeatInterval` (ex: 5 em 5 minutos). Sem deduplicação, cada reenvio disparava uma nova análise LLM — gasto desnecessário de tokens e risco de flooding no Teams.

3. **Webhook síncrono:** O endpoint `/webhook` aguardava o ciclo completo (análise LLM + runbook + Teams) antes de retornar. Dependendo do modelo, isso levava 30–90 segundos. O Alertmanager tem timeout; se estourado, marca o webhook como falho e tenta novamente — agravando o flooding.

---

## Solução 1 — Geração automática de fixtures

### `scripts/generate-fixtures.py`

Lê todos os `alerting/*.yaml` via `pyyaml`, extrai cada alerta e gera `tests/fixtures/<kebab>-alert.json`.

**Convenção de nomenclatura:** CamelCase → kebab-case em dois passos de regex:
```python
def camel_to_kebab(name: str) -> str:
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1-\2", s)
    return s.lower()
# ZeebePodOOMKilled → zeebe-pod-oom-killed
# ElasticsearchClusterHealthCritical → elasticsearch-cluster-health-critical
```

**Resolução de templates Go:** PrometheusRules usam `{{ $labels.xxx }}` e `{{ $value | humanizePercentage }}` — sintaxe Prometheus que não faz sentido em JSON estático. O script substitui por valores padrão por componente:
```python
_LABEL_DEFAULTS = {
    "zeebe":         {"pod": "camunda-zeebe-0", "namespace": "camunda", ...},
    "elasticsearch": {"cluster": "elasticsearch", "node": "es-node-0", ...},
    "kube":          {"pod": "camunda-app-0",    "namespace": "camunda", ...},
}
# {{ $labels.pod }} → "camunda-zeebe-0"
# {{ $value | humanizePercentage }} → "87.3%"
```

**Idempotência:** verifica se `<kebab>-alert.json` já existe antes de gerar. Fixtures curados manualmente nunca são sobrescritos.

**Extração automática de labels:** analisa `annotations.summary` e `annotations.description` para identificar labels referenciados e os injeta no payload gerado.

### Integração com demo.sh

`ensure_fixtures()` é chamado antes da execução principal:
```bash
ensure_fixtures() {
    python scripts/generate-fixtures.py
}
```

O modo `all` usa descoberta dinâmica:
```bash
find "${FIXTURES_DIR}" -name "*-alert.json" | sort
```

Qualquer alerta novo adicionado ao `alerting/` aparece automaticamente na próxima execução de `make demo`.

### Fixtures renomeados (convenção kebab-case)

| Antes | Depois |
|---|---|
| `zeebe-memory-alert.json` | `zeebe-memory-predicted-high-alert.json` |
| `zeebe-backpressure-alert.json` | `zeebe-backpressure-growing-alert.json` |
| `namespace-memory-alert.json` | `camunda-namespace-memory-pressure-alert.json` |
| `zeebe-resolved.json` | `zeebe-memory-predicted-high-resolved.json` |

---

## Solução 2 — Deduplicação por fingerprint

### Design

O Alertmanager inclui um campo `fingerprint` em cada alerta — hash que identifica unicamente a combinação regra+labels. Se ausente, o agente deriva um via MD5(alertname + labels ordenados).

```python
_dedup_cache: dict[str, datetime] = {}  # fingerprint → timestamp do último processamento

def _is_duplicate(fingerprint: str, status: str) -> bool:
    if status == "resolved":
        return False  # resolved sempre passa — encerramento nunca é suprimido
    now = datetime.now(UTC)
    # limpa entradas expiradas (evita crescimento ilimitado)
    expired = [fp for fp, ts in _dedup_cache.items()
               if (now - ts).total_seconds() > DEDUP_TTL_SECONDS]
    for fp in expired:
        del _dedup_cache[fp]
    if fingerprint in _dedup_cache:
        return True
    _dedup_cache[fingerprint] = now
    return False
```

### Configuração

```bash
DEDUP_TTL_SECONDS=300  # padrão: 5 minutos
```

Define por quanto tempo o agente suprime re-disparos do mesmo alerta. Deve ser ≥ `repeatInterval` do Alertmanager para ser efetivo.

### Observabilidade

Novo Counter `aiops_alerts_deduplicated_total` exposto em `GET /metrics` — permite monitorar quantos alertas estão sendo suprimidos por deduplicação.

### Regra para `resolved`

Alertas `resolved` **nunca** são deduplicados. O encerramento de um incidente deve sempre ser notificado, independente de quanto tempo passou desde o último `firing`. Isso garante que o card "✅ RESOLVED" chegue ao Teams mesmo que o alerta tenha sido suprimido durante a fase `firing`.

### Isolamento em testes

`_dedup_cache` é module-level — persiste entre testes na mesma sessão pytest. Todas as fixtures de teste que enviam alertas ao webhook devem limpar o cache:

```python
with patch.dict("webhook_receiver._dedup_cache", {}, clear=True):
    yield TestClient(app)
```

Sem isso, o segundo teste que enviar o mesmo alerta receberá `queued: 0` porque o fingerprint ainda está no cache do primeiro teste.

---

## Solução 3 — Webhook assíncrono (202 Accepted)

### Motivação

O ciclo completo (LLM + runbook + Teams) leva 30–90s. O Alertmanager tem timeout de webhook — se expirado, marca a rota como falha e reenvia, piorando o flooding. A solução é retornar imediatamente e processar em background.

### Implementação

A lógica de análise foi extraída para `_process_alert(alert, alert_id)`:

```python
@app.post("/webhook", status_code=202)
async def alertmanager_webhook(request: Request, background_tasks: BackgroundTasks):
    # filtro + dedup = operações rápidas, síncronas
    for alert in alerts:
        if not _passes_filter(alert):
            continue
        if _is_duplicate(fingerprint, status):
            continue
        background_tasks.add_task(_process_alert, alert, alert_id)
        queued += 1
    # retorna 202 IMEDIATAMENTE — antes do LLM ser chamado
    return JSONResponse({"message": f"{queued} alerta(s) enfileirado(s)", "queued": queued},
                        status_code=202)
```

### Contrato de resposta

| Campo | Tipo | Descrição |
|---|---|---|
| `message` | string | Mensagem legível: "N alerta(s) enfileirado(s)" |
| `queued` | int | Número de alertas aceitos para processamento |

Status sempre `202 Accepted` — o `200 OK` anterior implicava que o processamento havia terminado, o que era falso.

### Compatibilidade com Starlette TestClient

`BackgroundTasks` do FastAPI usa `starlette.background.BackgroundTasks`. O `TestClient` do Starlette executa as tasks **síncronamente antes de retornar** — os testes unitários e E2E funcionam sem modificação de lógica. Apenas o contrato de resposta (202 + `queued`) precisou ser atualizado.

### Diagrama antes/depois

**Antes (síncrono):**
```
Alertmanager → POST /webhook
                   ↓ (bloqueia até o LLM terminar, 30–90s)
               run_agent → generate_runbook → send_teams
                   ↓
               200 OK (Alertmanager esperou tudo)
```

**Depois (assíncrono):**
```
Alertmanager → POST /webhook
                   ↓ (filtro + dedup, ~1ms)
               202 Accepted ← Alertmanager recebe confirmação aqui
               
               [background]
               run_agent → generate_runbook → send_teams
```

---

## Fix — ALERT_FILTER_KEYWORDS default incompleto

O default de `ALERT_FILTER_KEYWORDS` era `"Zeebe,Camunda"`. Com a geração automática de fixtures cobrindo alertas `Kube*` e `Elasticsearch*`, a demo mostrava "alerta filtrado" para todos esses alertas.

**Fix:** default atualizado para `"Zeebe,Camunda,Kube,Elasticsearch"`.

Comportamento sem alteração de código ou configuração:
- `ZeebeMemoryPredictedHigh` → processado ✓ (Zeebe)
- `KubePodCrashLooping` → processado ✓ (Kube)  
- `ElasticsearchUnassignedShards` → processado ✓ (Elasticsearch)
- `NodeHighCPU` → filtrado ✓ (fora do escopo)

---

## Impacto em testes

| Arquivo | Mudanças |
|---|---|
| `test_webhook_receiver.py` | Status `200` → `202`; campo `analyses` → `queued`; fixture `client` limpa `_dedup_cache`; 7 novos testes em `TestDeduplication` |
| `test_alert_fixtures.py` | `ALERT_FIXTURES` dinâmico via `glob("*.json")` — não precisa mais ser atualizado ao adicionar fixtures |
| `tests/e2e/test_alert_cycle.py` | Status `200` → `202`; campo `analyses` → `queued` |
| `tests/e2e/conftest.py` | `e2e_client` envolve yield em `patch.dict(_dedup_cache, {}, clear=True)` |

Total de testes unitários: 219 → 224 (+5 líquido: +7 dedup, -2 testes de contrato de resposta que foram convertidos).

---

## Decisões técnicas e trade-offs

### BackgroundTasks vs Queue+Worker (Celery/RQ)

`BackgroundTasks` foi escolhido por:
- Zero dependências externas (sem Redis, sem broker)
- Compatibilidade transparente com TestClient (execução síncrona em testes)
- Simplicidade de deploy (sem worker separado)

**Limitação aceita:** em carga alta, múltiplas análises rodam concorrentemente no mesmo processo Python. O GIL não é problema aqui (o bottleneck é I/O — chamadas HTTP ao LLM e Prometheus). Se o volume de alertas crescer, a migração para Celery+Redis seria a próxima evolução.

### Deduplicação no agente vs Alertmanager

O Alertmanager já tem inibition rules e silences nativos, mas estes são por regra configurada manualmente. A deduplicação no agente é automática e baseada em fingerprint — sem necessidade de configurar rules no Alertmanager para cada novo tipo de alerta.

### TTL de 5 minutos

Alinhado com o `repeatInterval` típico de Alertmanager (5 min default). O operador pode ajustar via `DEDUP_TTL_SECONDS` sem tocar no código.
