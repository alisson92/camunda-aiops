# Etapa 8 — Demo Mode (`make demo`)

## Problema

O ciclo completo do agente AIOps funciona, mas a forma anterior de demonstrá-lo era frágil:

- Dependia do cluster Kind estar rodando
- Dependia de alertas reais disparando no momento certo
- Dependia do `load-generator.sh` gerar carga suficiente
- Exigia abrir múltiplos terminais (`make run` em um, demo em outro)
- Em máquinas sem Kind ou em apresentações remotas: ciclo quebrava

Para uma demo ao time, previsibilidade é essencial. Qualquer falha de infraestrutura no momento da apresentação destrói a percepção do projeto.

## Solução

Script `scripts/demo.sh` totalmente autossuficiente:

1. Verifica pré-requisitos (venv, `.env`)
2. Inicia o Ollama automaticamente se não estiver rodando
3. Verifica/baixa o modelo LLM se ausente
4. Inicia o agente em background se não estiver rodando
5. Executa os cenários de alerta em sequência
6. Encerra tudo via `trap cleanup EXIT INT TERM`

**Pré-requisito único:** `agent/.env` com `TEAMS_WEBHOOK_URL` configurada.

Sem Kubernetes. Sem Prometheus. Sem segundo terminal.

## Implementação

### Fixtures criados

| Arquivo | Alerta | Severidade |
|---|---|---|
| `zeebe-memory-alert.json` | `ZeebeMemoryPredictedHigh` | warning |
| `namespace-memory-alert.json` | `CamundaNamespaceMemoryPressure` | warning |
| `zeebe-backpressure-alert.json` | `ZeebeBackpressureGrowing` | **critical** |
| `zeebe-resolved.json` | `ZeebeMemoryPredictedHigh` | resolved |

Os dois novos fixtures (`backpressure` e `resolved`) completam o lifecycle de um alerta:
- **critical**: impacto visual máximo — mostra o pior caso
- **resolved**: mostra que o agente também processa o fechamento do alerta

### Script `scripts/demo.sh`

Funcionalidades:
- `--scenario <nome>`: roda apenas um cenário (zeebe, namespace, backpressure, resolved)
- `--dry-run`: mostra o que seria enviado sem executar — útil para ensaiar
- `--list`: lista os cenários disponíveis
- `--delay <s>`: pausa entre cenários (padrão: 3s)
- `--webhook-url <url>`: substitui o endpoint padrão (`http://localhost:5001/webhook`)
- Verifica se o agente está respondendo antes de enviar (exit com diagnóstico se não estiver)
- Exibe os primeiros 400 chars da análise do LLM no terminal após cada cenário
- `curl --max-time 120`: acomoda o tempo de resposta do Ollama local (10–30s)
- ShellCheck: zero warnings em `severity=warning`

### Targets no Makefile

```makefile
make demo                # ciclo completo (4 cenários)
make demo-zeebe          # apenas ZeebeMemoryPredictedHigh
make demo-namespace      # apenas CamundaNamespaceMemoryPressure
make demo-backpressure   # apenas ZeebeBackpressureGrowing (critical)
make demo-resolved       # apenas ZeebeMemoryPredictedHigh (resolved)
```

## Como usar na demo ao time

```bash
# Um único comando — o script cuida de tudo
make demo

# Por cenário específico (critical primeiro para impacto máximo)
make demo-backpressure

# Ensaiar sem enviar nada (verifica pré-requisitos e mostra o que seria feito)
./scripts/demo.sh --dry-run
```

## Decisões técnicas

**Por que um script Bash em vez de Python?**
Mantém consistência com os outros scripts operacionais do projeto. Qualquer pessoa pode ler e entender sem precisar do virtualenv.

**Por que `--max-time 120` no curl?**
O `qwen2.5:7b` em hardware com CPU moderada pode levar de 10s a 30s por análise. Sem esse timeout, o curl cancelaria a requisição antes do LLM terminar.

**Por que exibir apenas 400 chars da análise no terminal?**
A análise completa vai para o Teams. O terminal é apenas um indicador de que o ciclo funcionou — não precisa ser verboso. Quem assiste a demo olha para o card do Teams, não para o terminal.

**Por que `python3 -c` inline para parsear o JSON?**
`jq` não é garantido em todas as máquinas. `python3` está sempre disponível no mesmo ambiente onde o agente roda.
