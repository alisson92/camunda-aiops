# Evolução do Projeto — camunda-aiops

Este documento registra decisões técnicas, refatorações e melhorias aplicadas ao projeto.
Cada entrada documenta: o que foi feito, por que foi feito e as fontes consultadas.
Serve como histórico de decisões (ADR simplificado) para facilitar manutenção e onboarding.

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
- [ ] Testes unitários do webhook receiver e do agente (webhook_receiver.py, reactive_agent.py, tools.py)
- [ ] Teste com alerta real — exercitar o ciclo completo via load-generator → alerta real → Teams
- [ ] Pipeline Python/Prophet para forecasting com sazonalidade (gatilho: 4+ semanas de histórico)
