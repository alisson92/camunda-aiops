# Etapa 9 — System Prompt v2

## Problema com o v1

O system prompt v1 funcionava, mas tinha lacunas que ficavam evidentes ao comparar outputs:

- **Sem indicação de urgência:** o agente diagnosticava mas não dizia se o operador tinha 5 minutos ou 1 hora para agir
- **Sem tratamento para `resolved`:** alertas encerrados recebiam o mesmo formato de firing (CAUSA_RAIZ, REMEDIAÇÃO), o que não faz sentido — o problema já passou
- **Contexto Camunda genérico:** o prompt mencionava Zeebe mas não descrevia os outros componentes, limitando a capacidade do LLM de raciocinar sobre impacto cruzado
- **Um único exemplo:** o modelo de 7B se beneficia de múltiplos exemplos para internalizar o formato

## O que mudou no v2

### 1. Campo URGÊNCIA no formato `firing`

```
URGÊNCIA: <Imediata (< 15 min) | Alta (< 1 h) | Moderada (monitorar)>
```

Força o LLM a traduzir severidade + métricas coletadas em uma janela de tempo concreta para o operador. É o campo mais prático da análise na hora de um incidente.

### 2. Formato dedicado para `resolved`

O v1 usava o mesmo formato para firing e resolved, o que gerava análises sem sentido (REMEDIAÇÃO para algo que já se resolveu). O v2 define um formato específico:

```
RESOLUÇÃO: <o que normalizou e quando>
CONFIRMAÇÃO: <métrica consultada e valor atual>
PRÓXIMO_PASSO: <ação preventiva ou "Nenhuma ação necessária">
```

O fluxo do agente também é instruído a consultar uma métrica de confirmação antes de produzir o resumo — garante que o resolved é baseado em dado real, não só no status do Alertmanager.

### 3. Contexto dos componentes Camunda 8

Lista os 6 componentes principais (zeebe-broker, zeebe-gateway, operate, tasklist, identity, connectors) com sua responsabilidade em uma linha. Permite ao LLM raciocinar sobre impacto cruzado: ex. backpressure no gateway → impacto em instâncias BPMN no operate.

### 4. Dois exemplos de output

- **Exemplo 1:** firing/critical — ZeebeBackpressureGrowing, mostra URGÊNCIA: Imediata
- **Exemplo 2:** resolved — ZeebeMemoryPredictedHigh normalizado, mostra o formato RESOLUÇÃO

Modelos de 7B aprendem melhor o formato esperado com exemplos concretos do que com descrições abstratas.

## O que não mudou

- Restrições de formatação para o Teams (sem tabelas, sem headings, sem HTML)
- Restrições de segurança (sem comandos destrutivos sem --dry-run)
- Queries PromQL prioritárias (com leve expansão de cobertura)
- Princípio de separação de responsabilidades: LLM produz análise, código Python monta o card

## Como comparar v1 vs v2

```bash
# Com o agente rodando (make demo inicia automaticamente):
make demo-backpressure   # cenário critical — exerce URGÊNCIA e REMEDIAÇÃO
make demo-resolved       # exerce o novo formato RESOLUÇÃO/CONFIRMAÇÃO
```

O texto que aparece no card do Teams é o output direto do LLM — qualquer melhoria de clareza e estrutura é visível imediatamente.

## Rollback

Se o v2 regredir algum comportamento:

```python
# agent/prompts.py — linha 12
SYSTEM_PROMPT = _load("system-prompt-v1.md")  # reverter para v1
```

O arquivo `system-prompt-v1.md` é preservado — nunca apagado.
