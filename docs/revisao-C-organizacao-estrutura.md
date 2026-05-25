---
titulo: Revisão C — Organização e estrutura do repositório
data: 2026-05-25
status: concluída
tipo: revisao
---

# Revisão C — Organização e estrutura do repositório

## Por que esta revisão foi realizada

Com o projeto prestes a ser compartilhado com o time, cada arquivo do repositório
representa a qualidade e maturidade do projeto. Inconsistências estruturais — desde
versões erradas de CI até ausência de índices de navegação — comprometem a percepção
e a usabilidade do projeto por novos colaboradores.

---

## O que foi feito e por quê

### 1. Correção das versões das GitHub Actions (bug crítico)

**Problema:** Todas as occorrências de `actions/checkout` e `actions/setup-python`
no `ci.yml` estavam pinadas em `@v6`, versão que não existe:

```yaml
# antes — versão inexistente, CI falharia
- uses: actions/checkout@v6
- uses: actions/setup-python@v6
```

**Correção:**
```yaml
# depois — versões estáveis e existentes
- uses: actions/checkout@v4
- uses: actions/setup-python@v5
```

**Por quê é crítico:** o CI é a única camada que valida automaticamente qualidade
antes de um merge. Com actions quebradas, a proteção deixa de existir silenciosamente.

---

### 2. Header desatualizado em `check-metrics.sh`

**Problema:** O script foi renomeado de `01-check-metrics.sh` para `check-metrics.sh`
na reestruturação da Etapa 7, mas os comentários no header ainda referenciavam o nome antigo
com os comandos de uso errados.

**Correção:** Header atualizado para refletir o nome atual e o uso correto via `make check-metrics`.

---

### 3. `prompts/GUIDELINES.md` desatualizado

**Problema:** A seção de estrutura da pasta listava apenas `system-prompt-v1.md` como
o "system prompt ativo", ignorando que o `v2` está em uso desde a Etapa 9.

**Correção:** Estrutura atualizada para listar ambas as versões com seus estados:
v1 como depreciado, v2 como versão em uso.

---

### 4. `pyproject.toml` — campos PEP 621 faltantes

**Problema:** O arquivo declarava apenas o mínimo funcional, omitindo campos padrão
que o mercado Python espera em qualquer projeto público ou compartilhado.

**Campos adicionados:**

| Campo | Valor | Por quê |
|---|---|---|
| `readme` | `README.md` | Sem isso, GitHub e PyPI não renderizam o README no pacote |
| `authors` | `Alisson Lima` | Registro de autoria — padrão PEP 621 obrigatório |
| `[project.urls]` | link do repositório | Rastreabilidade do pacote à fonte |
| `keywords` | `aiops, camunda, kubernetes...` | Contexto e discoverability |
| `version` | `0.1.0` → `0.12.0` | Após 12 etapas de desenvolvimento, a versão estava desatualizada |

**Ruff lint expandido:**

```toml
[tool.ruff.lint]
select = ["E", "W", "F", "I", "UP"]
ignore = ["E501"]
```

- `I` (isort): força ordenação consistente de imports — antes não era verificado
- `UP` (pyupgrade): detecta sintaxe Python desatualizada (ex: `timezone.utc` → `UTC`)
- O próprio ruff auto-corrigiu 9 ocorrências nos módulos do agente

---

### 5. `docs/README.md` — índice de navegação criado

**Problema:** A pasta `docs/` tinha 16 arquivos sem nenhum ponto de entrada.
Um colaborador novo não saberia por onde começar nem qual arquivo cobre qual assunto.

**Solução:** `docs/README.md` criado com tabela de navegação em três seções:
etapas de desenvolvimento, revisões de qualidade e fixes/ADR log.

---

### 6. `data/knowledge/examples/README.md` — instruções de uso criadas

**Problema:** O mecanismo de few-shot é central no projeto (Etapa 12), mas não havia
nenhuma instrução dentro do próprio diretório sobre como adicionar novos exemplos.
Um colaborador que abrisse a pasta no GitHub não saberia o que são os arquivos nem como usá-los.

**Solução:** `README.md` criado com: explicação do mecanismo, formato obrigatório de frontmatter,
instrução passo a passo para adicionar exemplos e tabela dos exemplos existentes.

---

### 7. Runbook placeholder removido (recorrência)

**Problema:** O arquivo `data/knowledge/runbooks/zeebe-memory-predicted-high-aabbccdd.md`
com conteúdo placeholder reapareceu localmente após a Revisão A — provavelmente recriado
por uma execução de demo anterior.

**Solução:** Removido novamente. A pasta `data/knowledge/runbooks/` é um diretório de
runtime (gitignored) — a `KnowledgeBase` o cria automaticamente se não existir.
Não é necessário manter arquivos nele entre sessões.

---

## Resultado

| Métrica | Antes | Depois |
|---|---|---|
| Testes unitários | 202 | 202 ✅ |
| Cobertura | 100% | 100% ✅ |
| CI actions com versão inexistente | 5 ocorrências | 0 |
| Ruff rules ativas | 0 (sem `[tool.ruff.lint]`) | 4 conjuntos (E, W, F, I, UP) |
| Violações de lint corrigidas pelo ruff | — | 9 auto-corrigidas |
| Campos PEP 621 faltantes em `pyproject.toml` | 5 | 0 |
| Índices de navegação ausentes | 2 (`docs/`, `examples/`) | 0 |
