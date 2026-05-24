---
titulo: "Etapa 5 — GitHub Actions CI"
data: "2026-05-24"
status: "concluída"
depende-de: "etapa-4-ollama-local-llm"
---

# Etapa 5 — GitHub Actions CI

## Objetivo

Introduzir uma esteira de CI automatizada que valide o repositório a cada push e pull request para a branch `main`, garantindo que o código Python e os manifestos Kubernetes estejam sempre em bom estado antes de qualquer merge.

**Problemas que esta etapa resolve:**

1. **Feedback tardio**: sem CI, erros de lint e testes quebrados só aparecem quando alguém roda manualmente na máquina local.
2. **Inconsistência de ambiente**: "funciona na minha máquina" — o CI executa em ambiente limpo e reproduzível.
3. **Manifestos YAML silenciosamente inválidos**: erros de sintaxe em PrometheusRules podem passar despercebidos e só falhar ao aplicar no cluster.

---

## Pré-requisitos

- Repositório publicado no GitHub (já existia desde a sessão de 2026-05-20)
- Nenhuma configuração adicional de secrets necessária para esta etapa — os jobs não acessam serviços externos

---

## O que foi feito

### Decisões de arquitetura do workflow

**Por que dois jobs separados (`python` e `yaml-lint`) em vez de um único job?**

Jobs separados dão feedback paralelo e mais claro no GitHub: se o lint Python passa mas o YAML falha, você vê isso de imediato na UI sem precisar ler os logs inteiros. O custo é negligenciável para um repositório de lab.

**Por que não usar `promtool check rules` para validar os PrometheusRules?**

`promtool` é a ferramenta correta para validar a semântica de PrometheusRules (expressões PromQL, nomes de alertas). No entanto, exigiria baixar o binário do Prometheus no runner ou usar uma imagem Docker, adicionando complexidade e tempo de build. Para esta etapa, `yamllint` valida a sintaxe YAML dos manifestos, que é a camada de erro mais comum em dia a dia. `promtool` pode ser adicionado como job opcional em uma próxima iteração.

**Por que o smoke test (`test_teams_notifier.py`) não roda no CI?**

O arquivo foi intencionalmente escrito sem funções com prefixo `test_`, portanto o pytest o ignora. O smoke test envia requests reais para o canal Teams e depende de um webhook URL configurado em `agent/.env` — não faz sentido rodar em CI sem um ambiente real e secrets configurados.

### Arquivos criados

| Arquivo | Propósito |
|---|---|
| `.github/workflows/ci.yml` | Workflow principal com os dois jobs |
| `.yamllint.yml` | Config do yamllint com regras adaptadas para manifestos Kubernetes |

### Estrutura do workflow

```
CI
├── python (ubuntu-latest)
│   ├── actions/checkout@v4
│   ├── actions/setup-python@v5  (Python 3.11, cache pip)
│   ├── pip install -e ".[dev]"  ← instala ruff + pytest via pyproject.toml
│   ├── ruff check agent/        ← lint
│   └── pytest                   ← testes unitários
│
└── yaml-lint (ubuntu-latest)
    ├── actions/checkout@v4
    └── ibiqlik/action-yamllint@v3  ← valida alerting/ com .yamllint.yml
```

---

## Como replicar do zero

### 1. Criar o diretório do workflow

```bash
mkdir -p .github/workflows
```

### 2. Criar o arquivo `.yamllint.yml` na raiz do repositório

O yamllint usa `extends: default` como base e relaxa duas regras críticas para manifestos Kubernetes:
- `line-length: disable` — expressões PromQL dentro de `expr:` costumam ter 100+ caracteres
- `comments.min-spaces-from-content: 1` — manifestos gerados por tooling às vezes omitem o espaço

```bash
# Verificar se o arquivo está correto localmente antes de commitar
pip install yamllint
yamllint -c .yamllint.yml alerting/
# Saída esperada: nenhuma linha de erro
```

### 3. Criar o workflow `.github/workflows/ci.yml`

Pontos de atenção ao adaptar para outro projeto:

```yaml
# Trigger: roda em push para main E em qualquer PR direcionado à main
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

```yaml
# Cache de pip: evita baixar as dependências a cada execução
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
    cache: "pip"
```

```yaml
# Instala o pacote em modo editável com as dependências de dev (ruff, pytest)
# Isso funciona porque pyproject.toml define [project.optional-dependencies] dev
- run: pip install -e ".[dev]"
```

### 4. Validar localmente antes de commitar

```bash
# Simular o que o CI vai rodar
ruff check agent/    # deve retornar sem erros
pytest               # todos os testes devem passar
yamllint -c .yamllint.yml alerting/   # nenhum erro de sintaxe
```

### 5. Commitar e observar o resultado

```bash
git add .github/workflows/ci.yml .yamllint.yml
git commit -m "ci: adiciona GitHub Actions com lint Python e validação YAML"
git push
```

Após o push, a aba **Actions** do repositório no GitHub exibirá a execução com os dois jobs em paralelo.

---

## Como validar (critério de aceite)

```
✅ Aba Actions do GitHub mostra execução verde (ambos os jobs passam)
✅ Job "python": ruff e pytest concluem sem erros
✅ Job "yaml-lint": yamllint não reporta erros nos arquivos de alerting/
✅ Um PR com erro proposital de lint (ex: linha sem espaço após ':') é bloqueado pelo CI
```

---

## Problemas encontrados

Nenhum durante esta etapa — a configuração foi direta. O único ponto de atenção foi a necessidade do `.yamllint.yml` customizado: sem ele, o yamllint com configuração padrão rejeitaria as expressões PromQL longas nos manifestos.

---

## Próximo passo

- **Teste com alerta real**: o ciclo AIOps foi validado apenas com alertas sintéticos. Rodar `./scripts/load-generator.sh --duration 30 --intensity high` e observar o fluxo completo: Prometheus → Alertmanager → agente → Teams.
- **Etapa 6 — Pipeline Python/Prophet**: gatilho é 4+ semanas de histórico de métricas (previsão: junho/2026).
