# Evolução do Projeto — camunda-aiops (ADR Log)

Este documento é o registro de **decisões arquiteturais e técnicas** (Architecture Decision Records — ADRs simplificados) do projeto.
Complementa o `CHANGELOG.md` (que registra *o que* mudou) documentando o *porquê* de cada decisão: contexto, opções consideradas, trade-offs e fontes.

**Diferença em relação ao CHANGELOG:**
- `CHANGELOG.md` → histórico de mudanças por versão (o quê)
- `projeto-evolucao.md` → raciocínio por trás das decisões (por quê)

Essencial para manutenção, onboarding e auditorias de arquitetura.

---

## 2026-05-23 — Refatoração estrutural para padrões da comunidade Python/DevOps

### Contexto

Após análise criteriosa da estrutura do projeto, foram identificados pontos de melhoria
para elevar a maturidade de organização ao padrão da comunidade. O projeto estava funcional,
mas apresentava problemas que dificultariam manutenção e reprodutibilidade em outros ambientes.

### Problemas identificados

| # | Problema | Impacto |
|---|---|---|
| 1 | Leitura de `.env` duplicada em 3 arquivos Python | Qualquer mudança na lógica precisa ser replicada manualmente |
| 2 | `PROMETHEUS_URL` hardcoded em `tools.py` | Não funciona em ambientes diferentes sem editar código |
| 3 | `agent/` sem `__init__.py` | Não é um pacote Python formal; imports implícitos dependem do CWD |
| 4 | `test-fixtures/` e `test/` dentro de `agent/` | Mistura código fonte com artefatos de teste |
| 5 | `test-teams-notification.py` com nome em kebab-case | PEP 8 exige snake_case; pytest não descobre arquivos com hífen |
| 6 | Apenas `print()` para logging | Sem nível de severidade, timestamp ou contexto estruturado |
| 7 | `requirements.txt` sem pin exato de versões | Builds não são reprodutíveis (`>=` permite regressões silenciosas) |
| 8 | Scripts com prefixo numérico (`01-`, `02-`) | Ordem de uso documentada no nome; renomear um quebra a sequência |
| 9 | Sem `Makefile` | Operações comuns não documentadas de forma executável |
| 10 | Sem `.env.example` | Quem clona o repositório não sabe quais variáveis configurar |
| 11 | Sem `CHANGELOG.md` | Sem histórico de mudanças por versão |

### Mudanças aplicadas

#### 1. `agent/config.py` — ponto único de configuração
**O que:** Criado módulo centralizado que carrega o `.env` e expõe todas as variáveis
de ambiente como constantes tipadas. Todos os outros módulos importam daqui.

**Por que:** The Twelve-Factor App (Factor III — Config) determina que configuração
deve ser separada do código e carregada do ambiente. Ter a lógica de leitura de `.env`
em um único lugar elimina duplicação e facilita auditoria de quais variáveis o projeto usa.

**Fonte:** [12factor.net/config](https://12factor.net/config)

---

#### 2. Logging estruturado — substituição de `print()` por `logging`
**O que:** Todos os módulos Python agora usam `logging.getLogger(__name__)` ao invés
de `print()`. A configuração (`basicConfig`) é feita apenas nos entry points
(`webhook_receiver.py`, `tests/test_teams_notifier.py`). Nível configurável via `LOG_LEVEL`.

**Por que:** The Twelve-Factor App (Factor XI — Logs) define que logs devem ser streams
de eventos com severidade. `print()` não tem nível, não tem timestamp e não pode ser
filtrado. O módulo `logging` da stdlib resolve isso sem dependência extra.

**Fonte:** [12factor.net/logs](https://12factor.net/logs) · [docs.python.org/logging](https://docs.python.org/3/library/logging.html)

---

#### 3. `tests/` na raiz — separação entre código e testes
**O que:** Criado diretório `tests/` na raiz com `__init__.py`. Fixtures movidas de
`agent/test-fixtures/` para `tests/fixtures/`. Script de smoke test movido e renomeado
de `agent/test-teams-notification.py` para `tests/test_teams_notifier.py`.

**Por que:** A convenção do pytest é ter os testes fora do pacote fonte, em `tests/`
na raiz. Misturar testes com código fonte dificulta a separação de responsabilidades
e pode incluir fixtures em distribuições do pacote.

**Fonte:** [pytest — Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) · [PEP 8 — Package and Module Names](https://peps.python.org/pep-0008/#package-and-module-names)

---

#### 4. `agent/__init__.py` — pacote Python formal
**O que:** Arquivo vazio criado para tornar `agent/` um pacote Python reconhecível.

**Por que:** Sem `__init__.py`, `agent/` é apenas um diretório. O Python trata
diretórios com `__init__.py` como pacotes, habilitando imports absolutos corretos
e descoberta por ferramentas como pytest e linters.

**Fonte:** [Python Packaging User Guide](https://packaging.python.org/en/latest/tutorials/packaging-projects/)

---

#### 5. `pyproject.toml` — substitui `requirements.txt`
**O que:** Arquivo `pyproject.toml` criado seguindo PEP 621. Define metadados do projeto,
dependências com versões mínimas e configuração do pytest (`pythonpath`, `testpaths`).

**Por que:** PEP 517/518/621 estabelecem `pyproject.toml` como o padrão moderno
para projetos Python. `requirements.txt` não tem campo para metadados do projeto
e não descreve o ambiente de desenvolvimento (ferramentas de dev, configuração de teste).

**Fonte:** [PEP 621](https://peps.python.org/pep-0621/) · [Python Packaging User Guide](https://packaging.python.org/en/latest/)

---

#### 6. `Makefile` — task runner como documentação executável
**O que:** `Makefile` com targets `run`, `test`, `smoke` e `lint`.

**Por que:** Um Makefile documenta as operações mais comuns do projeto de forma
executável — qualquer pessoa que clonar o repositório sabe imediatamente como
rodar, testar e validar o projeto sem ler documentação adicional.

**Fonte:** Padrão amplamente adotado em projetos como [Kubernetes](https://github.com/kubernetes/kubernetes/blob/master/Makefile) e [Prometheus](https://github.com/prometheus/prometheus/blob/main/Makefile)

---

#### 7. Scripts renomeados — sem prefixo numérico
**O que:** `01-check-metrics.sh` → `check-metrics.sh`, `02-load-generator.sh` →
`load-generator.sh`, `03-import-dashboard.sh` → `import-dashboard.sh`.

**Por que:** Prefixos numéricos codificam ordem de uso no nome do arquivo.
Se um novo script for inserido no meio, todos precisam ser renomeados.
A ordem de uso pertence ao `README.md` e ao `Makefile`, não ao nome do arquivo.

**Fonte:** Unix Philosophy — *"Programs should do one thing and do it well"*

---

#### 8. `.env.example` — template público de variáveis
**O que:** Arquivo `.env.example` criado com todas as variáveis necessárias
e valores fictícios/descritivos. Commitado no repositório.

**Por que:** Quem clona o repositório precisa saber quais variáveis configurar.
`.env.example` é a convenção da comunidade para documentar isso sem expor segredos.

**Fonte:** [dotenv — .env.example convention](https://www.dotenv.org/docs/security/env-example)

---

#### 9. `CHANGELOG.md` — histórico de versões
**O que:** `CHANGELOG.md` criado seguindo o formato Keep a Changelog.

**Por que:** Rastreabilidade de mudanças por versão. Facilita entender
o que mudou entre versões sem precisar ler o histórico de commits completo.

**Fonte:** [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)

---

### Próximas melhorias planejadas

- [x] GitHub Actions CI — lint Python (ruff) + validação YAML (yamllint) a cada push/PR (`856f8ab`)
- [x] Fix build-backend inválido no pyproject.toml — `setuptools.build_meta` (`9dc238c`)
- [x] Atualização das GitHub Actions para Node.js 24 — checkout e setup-python v6 (`4961c3e`)
- [x] Testes unitários do webhook receiver e do agente — 75 testes, 99.65% de cobertura (2026-05-24)
- [x] Script de ciclo completo automatizado com auto-recuperação — `run-cycle-test.sh` (2026-05-24)
- [ ] Pipeline Python/Prophet para forecasting com sazonalidade (gatilho: 4+ semanas de histórico)

---

## 2026-05-24 — Testes unitários, ciclo automatizado e análise estática de scripts

### Contexto

Com o ciclo AIOps funcional (PromQL → Alertmanager → agente Python → Teams), o próximo nível
de maturidade exigia cobertura de testes e capacidade de validar o ciclo completo de forma
automatizada e repetível — sem depender de infraestrutura externa para cada PR.

---

### 1. Suite de testes unitários — 75 testes, 99.65% de cobertura

**O que:** Quatro arquivos de teste criados em `tests/`:

| Arquivo | Cobertura | Técnica |
|---|---|---|
| `test_webhook_receiver.py` | 22 testes — `/health`, `/webhook`, `/silence` | `FastAPI TestClient` + `unittest.mock.patch` |
| `test_reactive_agent.py` | 12 testes — loop agentic com tool use | Mock do `openai.OpenAI` client |
| `test_tools.py` | 15 testes — queries Prometheus | Mock do `httpx` via `unittest.mock` |
| `test_teams_notifier_unit.py` | 19 testes — helpers puros + Adaptive Card | Testes de lógica pura sem I/O |

**Por que:** Testes unitários permitem verificar regressões sem infraestrutura (sem Kind, sem
Ollama, sem Prometheus). Cada dependência externa é mockada no limite do sistema.

**Decisão de arquitetura:** Ao usar `from module import func` em `webhook_receiver.py`, o
Python cria uma referência local na hora do import. O `patch` deve apontar para o **namespace
consumidor**, não para o módulo definidor:

```python
# CORRETO — patcha a referência que webhook_receiver mantém
patch("webhook_receiver.run_agent", ...)

# ERRADO — patcha o original, mas webhook_receiver já tem sua cópia
patch("reactive_agent.run_agent", ...)
```

**Fonte:** [unittest.mock — Where to patch](https://docs.python.org/3/library/unittest.mock.html#where-to-patch)

---

### 2. pytest-cov + threshold de cobertura no CI

**O que:** `pytest-cov>=5.0.0` adicionado como dependência de dev. Threshold de 100%
configurado em `pyproject.toml`:

```toml
[tool.coverage.report]
show_missing = true
fail_under = 100
```

CI atualizado para rodar `pytest --cov --cov-report=term-missing`.

**Por que:** `fail_under = 100` garante que qualquer linha nova de código sem teste bloqueia
o merge. Não há margem — ou está coberto ou o CI falha. Cobertura atual: 100% (82 testes,
0 linhas descobertas).

**Fonte:** [pytest-cov — Configuration](https://pytest-cov.readthedocs.io/en/latest/config.html)

---

### 3. ShellCheck no CI — análise estática de scripts Bash

**O que:** Job `shell-lint` adicionado ao workflow CI usando `ludeeus/action-shellcheck@2.0.0`
com `severity: warning`. Escaneando o diretório `scripts/`.

**Por que:** Scripts operacionais sem análise estática acumulam bugs insidiosos que só
aparecem em execução: variáveis sem aspas quebrando em paths com espaços (SC2206),
`cd` sem tratamento de falha deixando o script num diretório inesperado (SC2164), shebangs
ausentes (SC2148). O ShellCheck é o padrão de facto para esta análise.

**Por que `severity=warning` e não apenas `error`?** O nível `warning` captura exatamente
os bugs mais comuns em produção. Rodar só `error` deixa passar os `warning` — que são mais
insidiosos por não causarem falha imediata, apenas comportamento incorreto.

**Por que `ludeeus/action-shellcheck` e não `apt-get install shellcheck`?** A Action pina
a versão do ShellCheck junto com o workflow (reproducibilidade). Com `apt-get`, a versão
depende do Ubuntu runner e pode mudar silenciosamente.

**Correções aplicadas nos scripts:** 11 issues em 4 arquivos:
- SC2148: `test-port-metrics.sh` sem shebang → adicionado `#!/usr/bin/env bash`
- SC2206: `BG_PIDS+=($var)` sem aspas → corrigido para `BG_PIDS+=("$var")`
- SC2164: `cd "$dir"` sem `|| exit` → corrigido para `cd "$dir" || exit 1`
- SC2034: variáveis `i` não utilizadas em loops `for i in $(seq...)` → renomeadas para `_`

**Fonte:** [ShellCheck wiki — Severity levels](https://github.com/koalaman/shellcheck/wiki/Severity) · [ludeeus/action-shellcheck](https://github.com/ludeeus/action-shellcheck)

---

### 4. `run-cycle-test.sh` — script de ciclo completo com auto-recuperação

**O que:** Script que automatiza o ciclo completo de validação do lab:
1. Validação do contexto Kind
2. Verificação/início dos port-forwards (Prometheus `:9090`, Grafana `:3000`)
3. Início do agente FastAPI (com tentativa de auto-start do Ollama se necessário)
4. Geração de carga sintética via `load-generator.sh`
5. Monitoramento dos alertas disparados
6. Cleanup automático via `trap EXIT INT TERM`

**Resiliência:** Cada etapa tem handler próprio. O script usa `set -uo pipefail` sem `set -e`
para degradação graciosa — se o port-forward do Grafana falhar, o ciclo continua (Grafana
não é obrigatório para o ciclo core).

**`DEFAULT_KIND_CONTEXT` hardcoded:** `kind-camunda-platform-local` definido no topo do
script, sobrescrevível via `--context`. Se o contexto padrão não existir no kubeconfig, o
script aborta com diagnóstico claro: lista os contextos `kind-*` disponíveis e exibe o
comando para criar o cluster. Segue o princípio **fail fast, fail loud** — melhor abortar
com mensagem clara do que silenciosamente operar no cluster errado.

**Por que não auto-selecionar o contexto ativo ou o primeiro `kind-*`?** O contexto ativo
pode não ser o correto. Múltiplos clusters `kind-*` são comuns em ambientes de desenvolvimento
(ex: `kind-camunda`, `kind-dev`, `kind-testes`). Seleção automática por prefixo não é
determinística e cria risco de executar no cluster errado.

**Fonte:** [The Twelve-Factor App — IV. Backing services](https://12factor.net/backing-services)

---

### 5. Makefile — `.DEFAULT_GOAL` e novos targets

**O que:** `.DEFAULT_GOAL := help` adicionado ao topo do Makefile. Novos targets:
- `cycle-test` — executa `run-cycle-test.sh` com parâmetros configuráveis via variáveis
- `cycle-test-fast` — executa sem carga sintética (para validação rápida de conectividade)

**Por que `.DEFAULT_GOAL := help`?** Sem isso, rodar `make` sozinho executa o primeiro
target do Makefile. Se o primeiro target for `run`, isso inicia o agente silenciosamente.
`.DEFAULT_GOAL := help` garante que `make` sem argumentos exibe as opções disponíveis
— comportamento seguro e autodocumentado.

**Fonte:** [GNU Make — Special Variables](https://www.gnu.org/software/make/manual/make.html#Special-Variables)

---

### 6. ADRs (Architecture Decision Records) — decisões documentadas com trade-offs

**O que:** 6 ADRs criados no Obsidian (vault pessoal) documentando as decisões arquiteturais
do projeto com contexto, opções consideradas, decisão final e consequências:

| ADR | Decisão |
|---|---|
| ADR-001 | LLM local com Ollama (`qwen2.5:7b`) vs cloud |
| ADR-002 | SDK OpenAI-compatible para abstração do LLM |
| ADR-003 | Arquitetura reativa via webhook vs polling |
| ADR-004 | PrometheusRules como Infrastructure as Code |
| ADR-005 | ShellCheck no CI com `severity=warning` |
| ADR-006 | `DEFAULT_KIND_CONTEXT` hardcoded com override via `--context` |

**Por que ADRs?** Decisões arquiteturais têm contexto e trade-offs que não aparecem no código.
Um ADR responde "por que X e não Y?" — a pergunta mais frequente em code review e onboarding.
Sem ADRs, esse conhecimento vive na cabeça de quem tomou a decisão e se perde com o tempo.

**Fonte:** [Documenting Architecture Decisions — Michael Nygard](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
