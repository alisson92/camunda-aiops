---
titulo: "Etapa 4 — Migração para LLM Local com Ollama"
data: "2026-05-22"
status: "concluída"
depende-de: "etapa-3-agente-reativo-claude-api"
---

# Etapa 4 — Migração para LLM Local com Ollama

## Objetivo

Substituir a dependência da Anthropic Cloud API por um modelo de linguagem rodando localmente via Ollama.

**Problemas que esta etapa resolve:**

1. **Custo**: em escala, cada alerta dispara chamadas à API paga. Inviável para produção.
2. **Privacidade de dados**: métricas de infraestrutura (uso de CPU, memória, padrões de carga) são dados sensíveis que não devem sair do ambiente corporativo.
3. **Dependência de internet**: ambientes com restrição de acesso externo não podem depender de APIs em nuvem.

---

## Pré-requisitos

```bash
# Confirmar contexto Kind
kubectl config current-context  # deve retornar kind-*

# Ollama deve estar instalado
ollama --version  # testado com v0.19.0

# GPU disponível (recomendado — CPU funciona, mas com latência alta)
nvidia-smi
```

---

## O que foi feito

### Parte A — Instalação e validação do modelo

**Por que `qwen2.5:7b`?**

| Critério | Decisão |
|---|---|
| Suporte a function calling | qwen2.5:7b é um dos melhores na categoria open-source |
| Tamanho do modelo | 4.7 GB — cabe inteiramente na VRAM da RTX 4060 (8 GB) |
| Velocidade | Inferência via GPU: latência aceitável para uso em alertas |
| Alternativa | `llama3.1:8b` (5.5 GB) — viável, mas function calling mais fraco |

```bash
# Pull do modelo
ollama pull qwen2.5:7b

# Verificar presença
ollama list
# NAME           ID              SIZE      MODIFIED
# qwen2.5:7b     845dbda0ea48    4.7 GB    ...

# Smoke test
ollama run qwen2.5:7b 'Responda apenas com "OK": teste de verificação.'
# Saída esperada: OK
```

**Resultado:** modelo respondeu corretamente. GPU carregada (~4.5 GB VRAM). ✓

---

### Parte B — Migração do agente (Anthropic SDK → OpenAI SDK + Ollama)

**O que mudou no código:**

| Arquivo | Mudança |
|---|---|
| `reactive_agent.py` | Troca de `anthropic.Anthropic` por `openai.OpenAI` apontando para `http://localhost:11434/v1` |
| `tools.py` | Conversão dos schemas de ferramentas do formato Anthropic para OpenAI |
| `requirements.txt` | Remove `anthropic`, adiciona `openai` |
| `agent/.env` | Remove `ANTHROPIC_API_KEY`, adiciona `OLLAMA_BASE_URL` e `OLLAMA_MODEL` |

**Diferença de formato dos schemas de ferramenta:**

```python
# Formato Anthropic (antes)
{
    "name": "query_prometheus_instant",
    "description": "...",
    "input_schema": { "type": "object", "properties": {...} }
}

# Formato OpenAI/Ollama (depois)
{
    "type": "function",
    "function": {
        "name": "query_prometheus_instant",
        "description": "...",
        "parameters": { "type": "object", "properties": {...} }
    }
}
```

**Diferença no loop do agente:**

```python
# Anthropic (antes)
response.stop_reason == "end_turn"   # agente concluiu
response.stop_reason == "tool_use"   # agente quer chamar ferramenta
block.type == "tool_use"             # identifica chamada de ferramenta

# OpenAI/Ollama (depois)
choice.finish_reason == "stop"       # agente concluiu
choice.finish_reason == "tool_calls" # agente quer chamar ferramenta
choice.message.tool_calls            # lista de chamadas de ferramenta
```

---

## Como validar

```bash
# 1. Garantir que Ollama está rodando
curl -s http://localhost:11434/api/tags | python3 -m json.tool | grep qwen

# 2. Garantir que o Prometheus está acessível
curl -s http://localhost:9090/-/healthy

# 3. Iniciar o agente
cd agent && uvicorn webhook_receiver:app --host 0.0.0.0 --port 5001

# 4. Enviar alerta sintético
curl -s -X POST http://localhost:5001/webhook \
  -H "Content-Type: application/json" \
  -d @test-fixtures/zeebe-memory-alert.json | python3 -m json.tool

# Critério de aceite:
# - O campo "analysis" deve conter texto gerado pelo modelo local
# - O log do agente deve mostrar chamadas às ferramentas Prometheus
# - Nenhuma chamada de rede externa deve ocorrer (confirmar com: ss -tnp | grep ESTAB | grep -v 11434)
```

---

## Problemas encontrados

### Ambiente Python gerenciado pelo sistema (PEP 668)

**Sintoma:** `pip install` falha com "externally-managed-environment".

**Causa:** Ubuntu/Debian recentes protegem o Python do sistema de instalações diretas.

**Solução adotada (lab/POC):** `pip install --break-system-packages -r requirements.txt`. Para produção, usar `python3 -m venv .venv` na pasta `agent/`.

### `api_key` obrigatório no SDK OpenAI

**Sintoma:** `OpenAI()` lança erro se `api_key` estiver vazio.

**Causa:** O SDK valida a presença da key, mesmo que o servidor (Ollama) não a use.

**Solução:** Passar `api_key="ollama"` como placeholder — o Ollama ignora o valor.

### Modelo pode descrever tool calls em vez de executá-las

**Sintoma:** Em certas perguntas o modelo gera JSON de tool call como texto em vez de fazer a chamada real.

**Causa:** Limitação inerente de modelos 7B — o suporte a function calling não é tão robusto quanto em modelos maiores.

**Mitigação:** O system prompt instrui o modelo a SEMPRE consultar os dados antes de concluir. Para produção, considerar `qwen2.5:14b` ou `llama3.1:70b` (requer hardware maior).

---

## Próximo passo

- Etapa C: Tornar a configuração do Alertmanager resiliente a `helm upgrade`
- Etapa E: Validar ciclo end-to-end com alerta real (load generator)
