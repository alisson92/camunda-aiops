# Etapa 11 — Runbook Generation Automático

## O que foi implementado

O agente agora gera um runbook operacional Markdown automaticamente após cada análise de alerta `firing`. O runbook é servido via endpoint HTTP e o botão "📖 Runbook" no card do Teams aponta para ele.

**Fluxo completo:**
```
Alertmanager → /webhook → run_agent() → análise
                                            ↓
                               generate_runbook() [segunda chamada LLM, sem tool use]
                                            ↓
                           _runbooks[alert_id] = (alert_name, runbook_md)
                                            ↓
            send_alert_to_teams(runbook_url=f"{AGENT_PUBLIC_URL}/runbook/{alert_id}")
                                            ↓
                       GET /runbook/{alert_id} → HTML renderizado no browser
```

## Arquivos criados/alterados

| Arquivo | Mudança |
|---|---|
| `agent/runbook_generator.py` | Novo módulo — geração, fallback, Markdown→HTML |
| `agent/webhook_receiver.py` | Store, endpoint `/runbook/{id}`, integração |
| `agent/teams_notifier.py` | Parâmetro `runbook_url` explícito |
| `tests/unit/test_runbook_generator.py` | 42 testes novos |
| `tests/unit/test_webhook_receiver.py` | 6 testes novos, fixture atualizada |

## Decisões técnicas

### Segunda chamada ao LLM sem tool use
A análise já tem os dados coletados. A geração de runbook é uma transformação de formato, não uma coleta de dados. Uma chamada simples ao LLM com um prompt estruturado é suficiente e mais rápida.

### `alert_id` = slug + MD5[:8]
```python
slug = re.sub(r"[^a-z0-9]+", "-", alert_name.lower()).strip("-")
suffix = hashlib.md5(starts_at.encode()).hexdigest()[:8]
alert_id = f"{slug}-{suffix}"
# Exemplo: "zeebe-memory-predicted-high-a1b2c3d4"
```
URL-safe, único por instância de alerta, determinístico. Sem dependência de UUID externo.

### Fallback local quando o LLM falha
Se `generate_runbook()` lança exceção ou retorna conteúdo vazio, `_fallback_runbook()` gera um runbook mínimo com a análise já disponível. O endpoint `/runbook/{id}` sempre terá conteúdo.

### Renderer Markdown→HTML em Python puro
Sem dependência `markdown` ou outra lib externa. O template do runbook usa apenas: h1/h2/h3, **bold**, `inline code`, fenced code blocks, listas ul/ol. O renderer cobre exatamente esses elementos (~80 linhas). Fenced code blocks escapam caracteres HTML (`<`, `>`, `&`).

### Store em memória
```python
_runbooks: dict[str, tuple[str, str]] = {}  # alert_id → (alert_name, runbook_md)
```
Simples, sem persistência em disco. Se o agente reiniciar, runbooks antigos somem — aceitável para demo. Evolução futura: SQLite ou arquivo em `/tmp`.

### Resolved não gera runbook
Runbooks são sobre remediação — não fazem sentido para alertas `resolved`. O campo `runbook_id` retorna `""` e o botão não aparece no card resolved.

### Prioridade da URL do runbook
`runbook_url` explícita do webhook tem prioridade sobre `runbook_url` da annotation da PrometheusRule. Isso permite que o botão do card sempre aponte para o runbook dinâmico gerado por este alerta específico.

## Como testar manualmente

```bash
# Inicia o agente
make run

# Em outro terminal — dispara alerta de demo
curl -s -X POST http://localhost:5001/webhook \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/zeebe-memory-high.json | jq .analyses[0].runbook_id

# Acessa o runbook gerado (substitua pelo runbook_id retornado)
open http://localhost:5001/runbook/zeebe-memory-predicted-high-a1b2c3d4
```

## Próxima etapa — Etapa 12: Few-shot + RAG

Com runbooks gerados automaticamente, a próxima evolução é alimentar uma base de conhecimento (RAG) com esses runbooks + histórico de incidentes. O agente consultaria essa base antes de cada análise, produzindo respostas mais precisas e alinhadas ao ambiente específico do time.
