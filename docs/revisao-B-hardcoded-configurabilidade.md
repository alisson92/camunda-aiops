---
titulo: Revisão B — Hardcoded e configurabilidade
data: 2026-05-25
status: concluída
tipo: revisao
---

# Revisão B — Hardcoded e configurabilidade

## Por que esta revisão foi realizada

Um projeto escalável e de fácil manutenção não deve exigir alteração de código para
mudanças de ambiente ou de escopo operacional. Esta revisão levantou todos os valores
hardcoded do projeto, classificou cada um por categoria e corrigiu os que precisavam
de intervenção.

---

## Metodologia de classificação

Cada valor hardcoded foi avaliado segundo o critério:

> *"Se alguém precisar mudar este valor no futuro, terá que editar código ou apenas
> uma variável de ambiente / flag?"*

Quatro categorias foram definidas:

| Categoria | Critério | Ação |
|---|---|---|
| **Correto — configurável** | Já tem override via env var, documentado no `.env.example` | Nenhuma |
| **Correto — justificado tecnicamente** | Valor fixo por natureza (quirk de SDK, constante de segurança) | Nenhuma |
| **Aceitável para este contexto** | Mudança seria over-engineering dado o escopo do lab | Documentar |
| **Problema real** | Exige edição de código para mudança operacional legítima | **Corrigir** |

---

## Valores corretos — sem alteração necessária

### Defaults configuráveis via env var (`config.py`)

Todos os defaults abaixo têm override via variável de ambiente e estão documentados
no `.env.example`:

| Constante | Default | Variável env |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | `OLLAMA_BASE_URL` |
| `OLLAMA_MODEL` | `qwen2.5:7b` | `OLLAMA_MODEL` |
| `PROMETHEUS_URL` | `http://localhost:9090` | `PROMETHEUS_URL` |
| `ALERTMANAGER_URL` | `http://localhost:9093` | `ALERTMANAGER_URL` |
| `GRAFANA_URL` | `http://localhost:3000` | `GRAFANA_URL` |
| `GRAFANA_DASHBOARD_UID` | `camunda-local-forecasting` | `GRAFANA_DASHBOARD_UID` |
| `AGENT_PUBLIC_URL` | `http://localhost:5001` | `AGENT_PUBLIC_URL` |
| `LOG_LEVEL` | `INFO` | `LOG_LEVEL` |

### Valores justificados tecnicamente

| Local | Valor | Justificativa |
|---|---|---|
| `reactive_agent.py:21` | `MAX_TOOL_ROUNDS = 6` | Constante de segurança do loop agentic — não é configuração de ambiente |
| `reactive_agent.py:37` | `api_key="ollama"` | Placeholder exigido pelo SDK OpenAI; Ollama não valida o valor |
| `run-cycle-test.sh:35` | `DEFAULT_KIND_CONTEXT` | Decisão documentada: fail fast, fail loud (ver `etapa-6-ciclo-completo.md`) |

### Valores aceitáveis para este contexto

| Local | Valor | Por quê aceitar |
|---|---|---|
| `config.py` | `UTC-3` (fuso BRT) | Time brasileiro; timezone dinâmica seria over-engineering |
| `tools.py / teams_notifier.py` | `timeout=10` / `timeout=15` | Valores razoáveis para localhost; raramente precisam mudar |
| Scripts | `namespace monitoring` / `namespace camunda` | Namespaces padrão documentados nos pré-requisitos do `CLAUDE.md` |
| `webhook_receiver.py:90` | `k=2` (docs KB) | Parâmetro de tuning interno do RAG, não configuração operacional |
| `prompts.py` | `excerpt(500)` | Parâmetro de tuning do contexto LLM, não configuração operacional |

---

## Problemas corrigidos

### Correção 1 — Filtro de alertas (`ALERT_FILTER_KEYWORDS`)

**Problema:** O filtro que define quais alertas o agente processa estava hardcoded em dois
lugares no código:

```python
# webhook_receiver.py — antes
if not any(kw in alert_name for kw in ("Zeebe", "Camunda")):

# tools.py — antes
kw in rule["name"] for kw in ("Zeebe", "Camunda")
```

Adicionar um novo componente monitorado (ex: `Operate`, `Identity`, um microserviço próprio)
exigia editar código e fazer redeploy.

**Solução:** Nova variável de ambiente `ALERT_FILTER_KEYWORDS` (padrão: `Zeebe,Camunda`)
adicionada ao `config.py` com parsing para lista:

```python
# config.py — depois
_raw_keywords = os.environ.get("ALERT_FILTER_KEYWORDS", "Zeebe,Camunda")
ALERT_FILTER_KEYWORDS: list[str] = [kw.strip() for kw in _raw_keywords.split(",") if kw.strip()]
```

Ambos os pontos de uso substituídos para consumir `ALERT_FILTER_KEYWORDS`.
Variável documentada no `.env.example` com exemplo de uso.

**Impacto operacional:** adicionar um novo componente agora é uma linha no `.env`:
```
ALERT_FILTER_KEYWORDS=Zeebe,Camunda,Operate
```

---

### Correção 2 — URL do Grafana no fallback de runbook

**Problema:** O template de fallback de runbook (gerado localmente quando o LLM falha)
usava `http://localhost:3000` diretamente, ignorando o `GRAFANA_URL` já configurável:

```python
# runbook_generator.py — antes
- Verifique métricas no Grafana: `http://localhost:3000`
```

Inconsistência: todo o resto do agente usa `GRAFANA_URL` de `config.py`; esse trecho era
a única exceção. Se `GRAFANA_URL` fosse alterado para um endereço de produção, o link
no runbook de fallback continuaria apontando para localhost.

**Solução:** Substituído por `{GRAFANA_URL}` no f-string, consumindo a constante importada
de `config.py`.

---

### Correção 3 — Porta do agente no `make run`

**Problema:** O target `make run` tinha a porta `5001` hardcoded, desacoplada de
`AGENT_PUBLIC_URL`:

```makefile
# Makefile — antes
cd agent && uvicorn webhook_receiver:app --host 0.0.0.0 --port 5001 --reload
```

Se `AGENT_PUBLIC_URL=http://localhost:8080` fosse configurado no `.env`, o `make run`
ainda subiria o agente na porta 5001 — causando inconsistência silenciosa.

**Solução:** A porta é extraída dinamicamente de `AGENT_PUBLIC_URL` via Python inline:

```makefile
# Makefile — depois
--port $$(python3 -c "import urllib.parse,os; u=os.environ.get('AGENT_PUBLIC_URL','http://localhost:5001'); print(urllib.parse.urlparse(u).port or 5001)")
```

---

## Resultado

| Métrica | Antes | Depois |
|---|---|---|
| Testes unitários | 198 | 202 (+4 para `ALERT_FILTER_KEYWORDS`) |
| Cobertura | 100% | 100% |
| Valores hardcoded problemáticos | 3 | 0 |
| Variáveis configuráveis via env | 8 | 9 (`+ALERT_FILTER_KEYWORDS`) |
