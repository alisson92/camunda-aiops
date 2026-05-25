---
titulo: Revisão D — CONTRIBUTING.md e padrões do projeto
data: 2026-05-25
status: concluída
tipo: revisao
---

# Revisão D — CONTRIBUTING.md e padrões do projeto

## Por que esta revisão foi realizada

O projeto estava prestes a ser compartilhado com o time. Sem um arquivo de padrões
centralizado, cada colaborador novo precisaria inferir convenções lendo o código —
commits, estrutura de testes, como adicionar variáveis de ambiente, onde documentar.

Além disso, o ciclo de desenvolvimento usado nas Revisões A–C (implementar → documentar →
validar → commitar → push) estava documentado apenas no `CLAUDE.md`, visível só durante
sessões com o assistente. O time precisava de um ponto de referência permanente.

---

## O que foi feito

### 1. `CONTRIBUTING.md` criado na raiz do repositório

O arquivo cobre todas as convenções que um colaborador precisa conhecer:

| Seção | Conteúdo |
|---|---|
| Pré-requisitos | Como instalar o ambiente, variáveis de ambiente necessárias |
| Fluxo de contribuição | O ciclo obrigatório de 5 pontos ao fechar qualquer etapa |
| Conventional Commits | Tipos, escopos comuns, exemplos válidos |
| Padrão de código | Ruff rules, ordem de imports, line-length |
| Configuração | Regra: toda config via `config.py`, nada hardcoded nos módulos |
| Testes | Estrutura de diretórios, cobertura 100% obrigatória, markers |
| Nova etapa | Checklist passo a passo para adicionar uma etapa ao projeto |
| Few-shot / RAG | Ponteiro para `data/knowledge/examples/README.md` |
| Alertas e PrometheusRules | Convenção de nomes, validação local antes do push |
| ADRs | Formato de entrada em `docs/projeto-evolucao.md` |
| CI | Tabela dos 5 jobs e quando cada um falha |
| O que nunca commitar | `.env`, `runbooks/`, `*.egg-info/`, placeholders |

### 2. `docs/README.md` atualizado

Revisão D adicionada à tabela de revisões de qualidade.

---

## Decisões de escopo

**Por que CONTRIBUTING.md e não uma pasta `docs/contributing/`?**
A raiz é o local padrão esperado pelo GitHub — renderiza automaticamente no repositório
e é encontrado por qualquer colaborador sem precisar saber da pasta `docs/`.

**Por que repetir o ciclo de 5 pontos (já no CLAUDE.md)?**
O `CLAUDE.md` é instruções para o assistente, não para o time. O CONTRIBUTING.md é o
contrato do time consigo mesmo — precisa estar em um lugar que o time acessa diretamente.

**Não há CODEOWNERS, templates de PR ou issue templates?**
O projeto é um lab interno. Adicionar infraestrutura de OSS (CODEOWNERS, PR templates)
seria prematura complexity. Se o projeto evoluir para multi-contribuidor, essa infraestrutura
pode ser adicionada como Etapa incremental.

---

## Resultado

| Arquivo | Status |
|---|---|
| `CONTRIBUTING.md` | ✅ Criado (raiz do repositório) |
| `docs/revisao-D-contributing.md` | ✅ Este documento |
| `docs/README.md` | ✅ Entrada da Revisão D adicionada |
| `CHANGELOG.md` | ✅ Entrada em `[Unreleased]` |
