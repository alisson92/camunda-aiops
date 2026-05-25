---
titulo: Revisão A — Limpeza e organização do repositório
data: 2026-05-25
status: concluída
tipo: revisao
---

# Revisão A — Limpeza e organização do repositório

## Por que esta revisão foi realizada

Antes de avançar para novas features (Etapas 13+) e de apresentar o projeto ao time, foi
realizado um pente fino no repositório para garantir que ele reflita o estado atual do projeto,
sem arquivos orphãos, numeração inconsistente de documentos ou estruturas fora do padrão.

**Motivação:** o projeto será compartilhado com o time. Qualidade de repositório é tão
importante quanto qualidade de código — documentação desatualizada, arquivos mal posicionados
e scripts sem entrada no Makefile geram confusão e reduzem a credibilidade do projeto.

---

## O que foi feito e por quê

### 1. Remoção de artefato de teste manual

**Arquivo:** `data/knowledge/runbooks/zeebe-memory-predicted-high-aabbccdd.md`

**Por quê:** Conteúdo placeholder (`# Runbook: ZeebeMemoryPredictedHigh\n\nconteúdo`) criado
durante testes manuais de desenvolvimento. A pasta `data/knowledge/runbooks/` já está no
`.gitignore` (runbooks são artefatos de runtime), mas o arquivo estava presente localmente.
Mantê-lo causaria confusão pois sugeriria que o sistema já tinha gerado um runbook real.

---

### 2. Reorganização do smoke test para `tests/smoke/`

**Antes:** `tests/test_teams_notifier.py` (raiz de `tests/`)
**Depois:** `tests/smoke/test_teams_notifier.py`

**Por quê:** O projeto já adota uma estrutura clara de subdiretórios por tipo de teste:
`tests/unit/`, `tests/integration/`, `tests/e2e/`. O smoke test estava "solto" na raiz de
`tests/`, violando o padrão estabelecido.

O smoke test não é executado pelo pytest (não tem funções `test_*`) — é um script de execução
manual via `make smoke` / `scripts/smoke.sh`. A pasta `tests/smoke/` deixa explícito o tipo
e evita que futuros contribuidores questionem por que há um `test_*.py` sem testes pytest.

**Impacto:** `scripts/smoke.sh` atualizado para referenciar o novo caminho.

---

### 3. Correção da numeração de docs (`etapa-5` → `etapa-7`)

**Antes:** `docs/etapa-5-github-actions.md` (tratava de CI/qualidade)
**Depois:** `docs/etapa-7-qualidade-ci.md`

**Por quê:** O roadmap do projeto define:
- Etapa 5 = Notificações Teams com Adaptive Card
- Etapa 7 = Qualidade: 100% cobertura + CI

O arquivo estava com numeração errada desde sua criação. Isso causava inconsistência entre
o roadmap documentado no `CLAUDE.md` e os docs existentes.

---

### 4. Criação de docs faltantes (Etapas 6 e 12)

**Arquivos criados:**
- `docs/etapa-6-ciclo-completo.md` — `run-cycle-test.sh`, decisões sobre `DEFAULT_KIND_CONTEXT`
- `docs/etapa-12-rag-conhecimento.md` — `KnowledgeBase`, scoring, few-shot, decisões de design

**Por quê:** Ambas as etapas foram implementadas mas nunca documentadas. O padrão do projeto
(definido em `CLAUDE.md`) exige doc por etapa ao concluir. A ausência criava lacunas na
narrativa do projeto para quem o lê pela primeira vez.

---

### 5. Nota histórica em `docs/etapa-3-agente-reativo-claude-api.md`

**Por quê:** O documento descreve o agente usando a Claude API (Anthropic Cloud), que foi
substituída pelo Ollama local na Etapa 4. Sem a nota, um leitor poderia assumir que o projeto
ainda depende de cloud — contrário à proposta central de ser 100% air-gapped.

A nota foi adicionada no topo com referência ao `superseded-by: etapa-4-ollama-local-llm.md`,
mantendo o histórico intacto.

---

### 6. Clarificação do papel de `docs/projeto-evolucao.md`

**Por quê:** O arquivo registra ADRs (Architecture Decision Records) e decisões técnicas com
contexto e trade-offs — um papel diferente do `CHANGELOG.md` (que registra o quê mudou).
Sem o cabeçalho explicativo, era difícil entender por que o arquivo existia em paralelo ao
CHANGELOG. A distinção agora está documentada no próprio arquivo.

---

### 7. Notice de deprecação em `prompts/system-prompt-v1.md`

**Por quê:** O v1 está mantido como referência histórica — útil para entender a evolução do
system prompt. Mas sem marcação explícita, um contribuidor poderia usá-lo acidentalmente ou
não saber que há uma versão mais recente. O notice no topo direciona para o v2 e para o
`GUIDELINES.md`.

---

### 8. `make check-pod-metrics` adicionado ao Makefile

**Script:** `scripts/test-port-metrics.sh`

**Por quê:** O script existia mas não tinha target no Makefile nem documentação. Tem utilidade
real e distinta de `make check-metrics`:

| Target | O que faz | Quando usar |
|---|---|---|
| `make check-metrics` | Consulta o Prometheus: "você já coleta essas métricas?" | Verificar se o scraping está funcionando |
| `make check-pod-metrics` | `kubectl exec` nos pods: "o endpoint `/actuator/prometheus` responde?" | Diagnosticar quando métricas não aparecem no Prometheus |

Sem o target, o script era descoberto apenas por quem lesse o código — conhecimento implícito
que não escala para novos membros do time.

---

### 9. README e estrutura de arquivos atualizados

**Por quê:** A árvore de diretórios no README refletia o estado anterior (158 testes, sem
`tests/smoke/`, sem `system-prompt-v2.md` listado, contagens desatualizadas). Documentação
desatualizada é pior que documentação ausente — induz a erros de interpretação.

---

## Resultado

| Métrica | Antes | Depois |
|---|---|---|
| Testes unitários | 198 ✅ | 198 ✅ |
| Cobertura | 100% ✅ | 100% ✅ |
| Docs de etapas faltantes | 2 (etapas 6, 12) | 0 |
| Arquivos fora do lugar | 1 (`tests/test_teams_notifier.py`) | 0 |
| Scripts sem target no Makefile | 1 (`test-port-metrics.sh`) | 0 |
| Docs com numeração errada | 1 (`etapa-5-github-actions`) | 0 |
