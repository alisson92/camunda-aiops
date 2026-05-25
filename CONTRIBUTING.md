# Contributing — camunda-aiops

Guia de padrões, convenções e fluxo de contribuição para o projeto.

---

## Pré-requisitos

```bash
# Python 3.11+
python --version

# Instalar dependências (incluindo ferramentas de dev)
pip install -e ".[dev]"

# Verificar que o ambiente está funcional
make test
make lint
```

Variáveis de ambiente necessárias para execução local e smoke tests:

```bash
cp agent/.env.example agent/.env
# Edite agent/.env e preencha TEAMS_WEBHOOK_URL
```

---

## Fluxo de contribuição

O ciclo obrigatório para qualquer mudança — feature, fix, refactor ou doc:

```
Implementar → Documentar → Validar (testes) → Commitar → Push
```

**Nunca fechar uma etapa sem:**

1. Entrada no `CHANGELOG.md` (seção `[Unreleased]`)
2. `README.md` atualizado nas seções afetadas
3. Documento em `docs/` criado ou atualizado (`etapa-N-<nome>.md` ou `revisao-X-<nome>.md`)
4. `CLAUDE.md` atualizado se comandos principais ou roadmap mudaram
5. Memória interna do projeto atualizada (`memory/project_historico_evolucao.md`)

---

## Padrão de commits — Conventional Commits

Todos os commits seguem [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<tipo>(<escopo>): <descrição curta em português>
```

| Tipo | Quando usar |
|---|---|
| `feat` | Nova funcionalidade ou etapa de desenvolvimento |
| `fix` | Correção de bug |
| `refactor` | Mudança interna sem alterar comportamento externo |
| `test` | Adição ou correção de testes |
| `docs` | Documentação apenas |
| `chore` | Infraestrutura, CI, dependências |
| `perf` | Melhoria de performance |

Escopos comuns: `agent`, `config`, `ci`, `tests`, `docs`, `alerting`, `prompts`, `pyproject`.

Exemplos válidos:

```
feat(agent): adiciona suporte a alertas ZeebeDiskPressure
fix(config): corrige parsing de ALERT_FILTER_KEYWORDS com espaços
refactor(tools): extrai lógica de filtragem para função separada
test(knowledge_base): adiciona casos de borda para search sem resultado
docs(etapa-13): documenta pipeline Prophet com sazonalidade
chore(ci): atualiza dependência pytest para 8.3
```

---

## Padrão de código

### Python

- **Python 3.11+** — sem compatibilidade retroativa
- Lint: `ruff check agent/` (configurado em `pyproject.toml`)
  - `E/W` — PEP 8
  - `F` — Pyflakes (imports não usados, variáveis indefinidas)
  - `I` — isort (ordenação de imports)
  - `UP` — pyupgrade (sintaxe moderna, ex: `datetime.UTC` em vez de `timezone.utc`)
- Formatação automática: `ruff format agent/` (opcional, mas recomendado)
- Line length: 100 caracteres

### Imports

Ordem obrigatória (isort):
1. Stdlib (`import json`, `import logging`)
2. Terceiros (`from openai import OpenAI`)
3. Internos do projeto (`from config import OLLAMA_MODEL`)

Separe cada grupo com uma linha em branco.

### Variáveis de ambiente e configuração

**Toda configuração vive em `agent/config.py`.** Nenhum valor hardcoded nos módulos do agente.

Padrão para nova variável de ambiente:

```python
# agent/config.py
MINHA_VARIAVEL: str = os.environ.get("MINHA_VARIAVEL", "valor_default")
```

E em `.env.example`:

```bash
# Descrição do que a variável controla e seu impacto
# Exemplo: MINHA_VARIAVEL=valor_alternativo
MINHA_VARIAVEL=valor_default
```

Valores que **podem** ser hardcoded (não são config):
- Constantes de protocolo (HTTP status codes, nomes de campos JSON)
- Timeouts internos ao ciclo de tool use (`MAX_TOOL_ROUNDS = 6`)
- Caminhos relativos dentro do pacote (`data/knowledge/`)

---

## Testes

### Estrutura

```
tests/
  unit/         Testes sem infraestrutura — rápidos, sem Docker, sem rede
  integration/  Prometheus real via Testcontainers (requer Docker)
  e2e/          Ciclo completo: webhook → agente → Prometheus → LLM → Teams (mocks HTTP)
  smoke/        Smoke tests manuais — requerem TEAMS_WEBHOOK_URL real
```

### Requisitos

- **Cobertura mínima: 100%** — `fail_under = 100` em `pyproject.toml`. O CI falha se cair.
- Todo novo módulo em `agent/` precisa de cobertura completa em `tests/unit/`.
- Testes de integração só para código que interage com infraestrutura externa (Prometheus, Docker).
- Use `@pytest.mark.integration` e `@pytest.mark.e2e` nos markers corretos.

### Executar

```bash
make test             # unitários + cobertura (rápido, sem Docker)
make test-integration # Testcontainers — requer Docker
make test-e2e         # ciclo completo com mock HTTP
make lint             # ruff check
```

---

## Adicionando uma nova etapa de desenvolvimento

1. Implemente os módulos em `agent/`
2. Escreva os testes em `tests/unit/` (e `integration/` se precisar de infra)
3. Execute `make test && make lint` — ambos devem passar
4. Atualize `CLAUDE.md`: roadmap + comandos se necessário
5. Crie `docs/etapa-N-<nome>.md` com: o que foi feito, decisões técnicas, como usar
6. Atualize `docs/README.md`: adicione a entrada na tabela de etapas
7. Adicione entrada no `CHANGELOG.md` em `[Unreleased]`
8. Atualize `README.md` nas seções afetadas (estrutura de arquivos, tabela de testes, comandos)
9. Commit com `feat(agent): ...` e push

---

## Adicionando exemplos few-shot (RAG)

Os exemplos few-shot ficam em `data/knowledge/examples/`. Consulte o
[README dos exemplos](data/knowledge/examples/README.md) para o formato obrigatório de
frontmatter e o processo passo a passo.

---

## Alertas e PrometheusRules

Regras de alerta ficam em `alerting/`. O CI valida a sintaxe YAML automaticamente com
`yamllint` (job `yaml-lint`).

Para adicionar uma nova regra:

1. Crie ou edite o arquivo em `alerting/`
2. Siga a convenção de nomes: `<componente>-<metrica>-<condicao>.yaml`
3. Execute `yamllint alerting/` localmente para validar antes do push
4. Documente a regra no documento de etapa correspondente

---

## Decisões arquiteturais (ADRs)

Decisões técnicas importantes são registradas em [`docs/projeto-evolucao.md`](docs/projeto-evolucao.md).

Quando registrar: sempre que uma decisão de design não for óbvia a partir do código — escolha de
biblioteca, trade-off de arquitetura, por que não usamos X, por que revertemos Y.

Formato de entrada:

```markdown
## ADR-N — <título>

**Data:** YYYY-MM-DD
**Status:** Aceito | Substituído por ADR-X

**Contexto:** O que motivou a decisão.
**Decisão:** O que foi decidido.
**Consequências:** Impactos positivos e negativos.
```

---

## CI — o que é verificado automaticamente

| Job | O que verifica | Quando falha |
|---|---|---|
| `python` | `ruff check` + `pytest` + cobertura 100% | Lint ou qualquer teste falha; cobertura < 100% |
| `integration` | Testcontainers com Prometheus real | Falha após `python` passar |
| `e2e` | Ciclo completo com mock HTTP | Falha após `integration` passar |
| `shell-lint` | `shellcheck` nos scripts de `scripts/` | Warning ou erro em qualquer script |
| `yaml-lint` | `yamllint` nos manifestos de `alerting/` | Erro de sintaxe YAML |

**Nunca faça push com CI vermelho.** Se o pipeline quebrar, corrija antes de continuar.

---

## O que nunca commitar

- `agent/.env` — contém `TEAMS_WEBHOOK_URL` e outros segredos (já no `.gitignore`)
- `data/knowledge/runbooks/` — diretório de runtime, populado pelo agente ao vivo
- Arquivos de build: `*.egg-info/`, `__pycache__/`, `.pytest_cache/`
- Placeholders ou arquivos de teste manual com conteúdo fictício

---

## Referências

- [README do projeto](README.md) — visão geral, stack, comandos
- [CHANGELOG](CHANGELOG.md) — histórico de mudanças por etapa
- [docs/](docs/README.md) — documentação de cada etapa, revisões e ADR log
- [docs/projeto-evolucao.md](docs/projeto-evolucao.md) — decisões arquiteturais
- [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/)
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
