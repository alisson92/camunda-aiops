# Revisão G — Documentação final e consistência

## Objetivo

Revisão final antes da demo ao time. Auditar consistência entre código, testes e
documentação — garantir que qualquer membro do time possa navegar no repositório
sem informações desatualizadas ou contraditórias.

---

## Itens auditados e corrigidos

### README.md

| Seção | Antes | Depois |
|---|---|---|
| `alerting/` na árvore | 3 arquivos listados | 7 arquivos (todos os PrometheusRules) |
| `dashboards/` na árvore | apenas `camunda-forecasting.json` | + `camunda-aiops-agent.json` |
| Seção "Alertas preditivos" | 3 alertas, uma tabela simples | Tabela completa com 7 arquivos e técnicas |
| Contagem total de testes | 218 | 219 |
| `test_webhook_receiver.py` | 36 testes | 37 testes |
| `test_teams_notifier_unit.py` | 32 testes | 34 testes |
| Tabela suítes (Unitários) | 159 | 219 |

### CLAUDE.md

| Item | Antes | Depois |
|---|---|---|
| `make test` descrição | `88 testes unitários` | `219 testes unitários` |
| Seção arquitetura | `unit/ 88 testes` | `unit/ 219 testes` |
| Seção arquitetura | `dashboards/` sem agente | dashboards + alerting mencionados |

### pyproject.toml

- `version`: `0.12.0` → `0.13.0`

### CHANGELOG.md

- `[Unreleased]` convertido em `[0.13.0] — 2026-05-25`
- Novo `[Unreleased]` vazio criado para próximos ciclos

---

## Bugs de CI corrigidos nesta revisão

### Coverage 99.50% → 100%

**Causa raiz:** o loop de startup em `webhook_receiver.py` era executado uma vez no
import do módulo. Em CI (ambiente limpo), `_kb.get_runbooks()` retorna `{}` → corpo
do for nunca executa → 3 linhas descobertas.

**Por que não aparecia localmente:** existia um arquivo de runbook em
`data/knowledge/runbooks/` de uma execução anterior de demo, populando o KB.

**Solução:** extraído para `_reload_runbooks_from_kb()` + `TestStartupReload` que
injeta um `Document` mock via `patch.object` e verifica que ambos os dicts são
populados. Testável independentemente do estado do disco.

### namespace=~"jorn.*" não capturava pods locais

**Causa raiz:** os 4 alertas migrados do Grafana usavam `namespace=~"jorn.*"` do
ambiente de homologação dos colegas. O Kind local usa `namespace="camunda"`.

**Solução:** `namespace=~"camunda.*|jorn.*"` — cobre ambos os ambientes sem exigir
duas versões dos manifestos. A regex é portável para qualquer namespace que comece
com `camunda` (ex: `camunda-staging`).

---

## Estado final do repositório

```
Testes unitários : 219 (100% cobertura, 605 statements)
Testes integração: 7 (Prometheus real via Testcontainers)
Testes E2E       : 3 (ciclo completo, Prometheus + mock HTTP)
PrometheusRules  : 7 arquivos, 21 alertas
Dashboards       : 2 (forecasting + observabilidade do agente)
CI jobs          : 5 (python, yaml-lint, shell-lint, integration, e2e)
```

## Próximos passos pós-demo

Ver roadmap em `CLAUDE.md`:
- **Etapa 12:** Few-shot + RAG já implementado; próximo passo é expandir o knowledge base com mais exemplos curados
- **Etapa 13:** Pipeline Prophet para sazonalidade — detecção de anomalias com contexto de dia da semana
- **Etapa 14:** Dynamic dashboard creation — agente cria painéis Grafana para alertas novos
