# Prompt Guidelines — camunda-aiops

## Estrutura da pasta

```
prompts/
├── GUIDELINES.md          # este arquivo — leia antes de qualquer alteração
└── system-prompt-v1.md    # system prompt ativo do agente
```

---

## Princípios

- **Um arquivo por versão.** Nunca edite um arquivo já em uso em produção. Crie `system-prompt-v2.md` e atualize o loader.
- **Sem gambiarras.** Se o prompt precisar de lógica condicional (ex: "se for critical, faça X"), isso é responsabilidade do código Python, não do prompt.
- **Separação de responsabilidades.** O prompt instrui o LLM sobre *como raciocinar*. O código Python cuida de montar o card, injetar metadados e enviar ao Teams.
- **Clareza acima de completude.** Um prompt enxuto e claro performa melhor em modelos menores (7B) do que um prompt longo e detalhado.

---

## Como versionar

| Situação | Ação |
|---|---|
| Ajuste fino de tom ou formatação | Edite o arquivo atual e registre no histórico abaixo |
| Nova seção ou mudança de fluxo | Crie `system-prompt-v{N+1}.md` e atualize `agent/prompts.py` |
| Rollback necessário | Aponte o loader para a versão anterior — o arquivo antigo nunca foi apagado |

---

## Como testar uma mudança de prompt

1. Faça a alteração no arquivo `.md`
2. Rode a demo com um alerta sintético (sem Kind necessário):
   ```bash
   make demo-backpressure   # cenário critical — maior exigência do prompt
   make demo-resolved       # valida o formato RESOLUÇÃO/CONFIRMAÇÃO
   ```
3. Avalie se a resposta segue o formato obrigatório definido no prompt
4. Só commite se o output estiver dentro do esperado

---

## Variáveis injetadas pelo código (não pertencem ao prompt)

O `agent/prompts.py` injeta o seguinte no *user message*, não no system prompt:

- `alert_name` — nome do alerta vindo do Alertmanager
- `alert_labels` — labels (namespace, pod, severity, etc.)
- `alert_annotations` — summary, description, runbook_url
- `status` — firing | resolved

---

## Restrições de formatação (válidas para qualquer versão)

O output do LLM é renderizado num **Adaptive Card do Microsoft Teams**. O card não suporta:

- Tabelas Markdown
- Headings (`#`, `##`, `###`)
- HTML ou LaTeX

Use apenas: listas com `-`, **negrito**, blocos de código com backticks.

---

## Histórico de versões

| Versão | Data | Autor | Descrição |
|---|---|---|---|
| v1 | 2026-05-23 | Alisson Lima | Versão inicial — fluxo obrigatório, queries PromQL prioritárias, formato estruturado de resposta |
| v2 | 2026-05-24 | Alisson Lima | Adiciona URGÊNCIA ao formato firing; formato dedicado para resolved (RESOLUÇÃO/CONFIRMAÇÃO/PRÓXIMO_PASSO); contexto dos componentes Camunda 8; dois exemplos de output (critical + resolved) |
