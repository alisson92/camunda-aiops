# Análise de Desempenho — LLM Local e Gargalo de Processamento

**Data:** 2026-05-26  
**Contexto:** Identificado durante execução do `make demo` com 23 alertas simultâneos.  
**Status:** Em investigação — modelos candidatos a serem testados.

---

## Problema identificado

Com `qwen2.5:7b` rodando localmente via Ollama, o tempo de processamento por alerta é de **30–90 segundos**. Com 23 alertas na fila, o último card chegou ao Teams após ~35 minutos.

O agente atual usa `BackgroundTasks` do FastAPI, que executa as tarefas **sequencialmente no mesmo processo**. Cada alerta aguarda o anterior terminar antes de começar. Somado ao tempo de inferência local, o gargalo fica evidente em cenários com volume.

### Observação no dashboard do agente

Comportamento observado no painel "Camunda AIOps Agent":

- **Webhooks Recebidos:** 23 simultâneos — chegaram todos de uma vez (202 imediato ✓)
- **Alertas Analisados:** atualizava um por vez, conforme o LLM terminava cada análise
- **Notificações Enviadas com Sucesso:** atualizava junto com o card no Teams
- **Notificações com Falha:** exibia "No data" (ausência de falhas, comportamento correto — corrigido com `or vector(0)`)

---

## Decomposição do gargalo

O ciclo de processamento por alerta envolve **três chamadas sequenciais ao LLM**:

```
Alerta recebido (202 imediato)
    ↓
1. run_agent() — chamada 1: LLM decide qual ferramenta usar (tool_call)     ~10–30s
2. query_prometheus() — consulta a métrica                                  ~1s
3. run_agent() — chamada 2: LLM analisa os dados e gera conclusão           ~10–30s
4. generate_runbook() — chamada 3: LLM gera markdown do runbook             ~10–30s
5. send_alert_to_teams() — POST para o webhook do Teams                     ~1s
                                                                           ─────────
                                                              Total:        ~30–90s/alerta
```

Com `BackgroundTasks` sequencial: 23 alertas × 60s médio = **~23 minutos** (melhor caso).

---

## Por que não cloud LLM

Modelos cloud (OpenAI, Anthropic, Google) resolveriam a latência (~2–5s por chamada), mas:

- **Custo em larga escala:** 3 chamadas por alerta × N alertas × custo/token torna insustentável
- **Dependência externa:** violar o princípio air-gapped do projeto
- **LGPD/compliance:** dados de alertas de produção enviados para terceiros

Decisão: **manter modelos locais gratuitos**, otimizar por outras vias.

---

## Modelos locais candidatos

Todos rodam via Ollama, sem custo. Instalação: `ollama pull <modelo>`.

| Modelo | Params | Fabricante | Foco | Velocidade estimada* | Status |
|---|---|---|---|---|---|
| `qwen2.5:7b` | 7B | Alibaba | Instrução geral | baseline (~60s) | **Em uso** |
| `qwen2.5:3b` | 3B | Alibaba | Instrução geral | ~3× mais rápido | A testar |
| `phi4-mini` | 3.8B | Microsoft | Raciocínio compacto | ~3× mais rápido | A testar |
| `llama3.2:3b` | 3B | Meta | Instrução geral | ~3× mais rápido | A testar |
| `gemma3:4b` | 4B | Google | Análise estruturada | ~2× mais rápido | A testar |
| `mistral:7b` | 7B | Mistral AI | Instrução geral | similar ao baseline | A testar |

*Estimativa relativa em CPU sem GPU dedicada. Resultados reais dependem do hardware.

---

## Como testar um modelo diferente

Para trocar o modelo, edite `agent/.env`:

```bash
OLLAMA_MODEL=phi4-mini
```

Certifique-se de que o modelo está disponível localmente:

```bash
ollama pull phi4-mini
ollama list   # confirma modelos disponíveis
```

Reinicie o agente para carregar a nova configuração:

```bash
# Se rodando via make run (modo dev):
make run

# Se rodando via demo:
make demo    # reinicia automaticamente
```

---

## Template de resultado por modelo

Preencher durante os testes para comparar objetivamente. Métricas coletadas do
dashboard "Camunda AIOps Agent" e da observação direta dos cards no Teams.

### Ambiente de teste

```
Hardware:     ___________________________
SO/WSL:       ___________________________
RAM disponível para Ollama: _____________
GPU (se aplicável): _____________________
```

### Resultados

| Modelo | Tempo médio/alerta (s) | Qualidade análise (1–5) | Runbook gerado OK? | Observações |
|---|---|---|---|---|
| `qwen2.5:7b` (baseline) | ~60s | — | Sim | Modelo atual de referência |
| `qwen2.5:3b` | | | | |
| `phi4-mini` | | | | |
| `llama3.2:3b` | | | | |
| `gemma3:4b` | | | | |
| `mistral:7b` | | | | |

### Critérios de qualidade da análise (1–5)

Avaliar lendo o card recebido no Teams e o runbook gerado:

| Critério | O que observar |
|---|---|
| **CAUSA_RAIZ** | Identifica a causa provável com precisão? Usa os dados do Prometheus? |
| **URGÊNCIA** | Classifica corretamente (Imediata / Alta / Moderada)? |
| **MÉTRICAS_COLETADAS** | Lista os valores reais coletados (não genérico)? |
| **RECOMENDAÇÃO** | Ação concreta e específica para o contexto Camunda/Kubernetes? |
| **Runbook** | Estrutura markdown válida, passos aplicáveis, sem alucinações? |

### Método de medição do tempo

```bash
# Opção 1: via dashboard Grafana
# Painel "Duração da Análise" mostra p50/p90/p99 em tempo real

# Opção 2: via logs do agente (ao rodar make demo)
tail -f /tmp/camunda-aiops-demo-*/agent.log | grep "Análise concluída"

# Opção 3: medir delta entre webhook recebido e card no Teams (cronômetro manual)
make demo-zeebe   # alerta único — mais fácil de medir
```

---

## Levers de otimização além do modelo

Mesmo com um modelo mais rápido, há outras alavancas independentes:

### 1. Paralelismo Ollama (`OLLAMA_NUM_PARALLEL`)

Permite que o Ollama processe múltiplas requisições simultâneas. Útil **apenas se o agente tiver workers paralelos** (caso contrário as tasks ainda chegam sequencialmente).

```bash
# Configurar via variável de ambiente antes de iniciar o Ollama
OLLAMA_NUM_PARALLEL=4 ollama serve
```

**Limitação:** em CPU, paralelismo divide os recursos — 4 análises simultâneas cada uma levará 4× mais tempo. O ganho real só aparece com GPU ou múltiplas CPUs dedicadas.

### 2. Worker pool real (Celery + Redis) — evolução futura

Substitui `BackgroundTasks` por uma fila de mensagens com múltiplos workers. Habilita paralelismo real: diferentes workers processam diferentes alertas simultaneamente.

```
Alerta → Redis (fila) → Worker 1, Worker 2, Worker 3... (paralelos)
```

Esforço: médio. Acrescenta dependência de Redis e do processo Celery. Candidato à Etapa 16 do roadmap se o volume de alertas justificar.

### 3. Cache de análises (deduplicação semântica)

Para alertas do mesmo tipo disparando repetidamente, reutilizar a análise recente em vez de reprocessar com o LLM. Implementável sobre a `KnowledgeBase` existente.

### 4. Reduzir de 3 chamadas para 1 ou 2

O ciclo atual faz 3 chamadas LLM por alerta. Avaliar se `generate_runbook()` pode ser mesclado na segunda chamada de `run_agent()` (um prompt que gera análise + runbook juntos), reduzindo 33% das chamadas.

---

## Decisão de modelo — critérios

Ao concluir os testes, a decisão deve levar em conta:

1. **Tempo aceitável em produção:** alertas `critical` devem chegar em < 5 minutos
2. **Qualidade mínima de análise:** score ≥ 3/5 em todos os critérios (análise genérica é pior que nenhuma)
3. **Qualidade do runbook:** runbooks com alucinações (passos inventados) são perigosos — melhor um fallback conservador
4. **Estabilidade do modelo:** verificar se o modelo tem tendência a encerrar antes de completar a resposta (`finish_reason: length`)

Se nenhum modelo local 3B atingir qualidade mínima, a alternativa é **otimizar o pipeline** (reduzir chamadas, adicionar cache) antes de recorrer a cloud.
