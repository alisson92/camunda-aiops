# Exemplos curados — few-shot para o agente AIOps

Esta pasta contém exemplos de análises ideais usados como **few-shot** pelo agente.
Cada arquivo ensina o LLM o formato e nível de detalhe esperado pelo time — sem treinar o modelo.

## Como funciona

Quando o agente recebe um alerta, a `KnowledgeBase` busca documentos relevantes nesta pasta
e injeta os mais próximos no contexto antes de chamar o LLM. O modelo usa os exemplos como
referência de formato e raciocínio.

## Como adicionar um novo exemplo

1. Crie `<alertname-em-kebab-case>.md` nesta pasta
2. Adicione o frontmatter obrigatório no topo:

```markdown
---
alert_name: NomeExatoDoAlertaCamelCase
type: example
severity: critical | warning | info
---
```

3. Escreva a análise no formato exato esperado pelo time (veja os exemplos existentes)
4. Faça commit — o exemplo é carregado automaticamente na próxima inicialização do agente

> **Nota:** novos exemplos requerem reinicialização do agente para serem carregados
> (são lidos apenas na startup). Runbooks gerados em runtime (pasta `runbooks/`) são
> indexados automaticamente sem reinicialização.

## Exemplos disponíveis

| Arquivo | alertname | Severidade |
|---|---|---|
| `zeebe-backpressure-growing.md` | `ZeebeBackpressureGrowing` | critical |
| `zeebe-memory-predicted-high.md` | `ZeebeMemoryPredictedHigh` | warning |
