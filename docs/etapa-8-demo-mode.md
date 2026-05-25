# Etapa 8 — Demo Mode (`make demo`)

## Problema

O ciclo completo do agente AIOps funciona, mas a forma anterior de demonstrá-lo era frágil:

- Dependia do cluster Kind estar rodando
- Dependia de alertas reais disparando no momento certo
- Dependia do `load-generator.sh` gerar carga suficiente
- Em máquinas sem Kind ou em apresentações remotas: ciclo quebrava

Para uma demo ao time, previsibilidade é essencial. Qualquer falha de infraestrutura no momento da apresentação destrói a percepção do projeto.

## Solução

Script `scripts/demo.sh` que injeta payloads reais do Alertmanager diretamente no webhook local, simulando exatamente o que o Alertmanager enviaria em produção — sem precisar do Kind.

**Pré-requisitos mínimos para a demo:**
1. `make run` — agente rodando na porta 5001
2. Ollama com `qwen2.5:7b` — análise real pelo LLM local
3. `agent/.env` com `TEAMS_WEBHOOK_URL` — para os cards chegarem no Teams

Sem Kubernetes. Sem Prometheus. Sem cluster.

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
# Terminal 1 — iniciar o agente
make run

# Terminal 2 — rodar a demo
make demo                # ciclo completo: 4 alertas em sequência
# ou por cenário:
make demo-backpressure   # começa pelo critical para impacto máximo
```

Para ensaiar sem enviar nada:
```bash
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
