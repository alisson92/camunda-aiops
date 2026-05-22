---
titulo: Etapa 3 — Agente reativo com Claude API
data: 2026-05-21
status: concluída
depende-de: etapa-2-grafana-mcp-server.md
---

# Etapa 3 — Agente reativo com Claude API

## Objetivo

Fechar o ciclo AIOps: quando um alerta preditivo da Etapa 1 dispara, um agente Python acorda automaticamente, consulta métricas reais via Prometheus HTTP API, raciocina sobre a causa raiz com a Claude API (tool use) e sugere comandos de remediação — sem executar nada sem aprovação humana.

### Fluxo completo

```
Prometheus → PrometheusRule (Etapa 1)
  → Alertmanager → rota webhook (porta 5001)
    → agent/webhook_receiver.py
      → Claude API (claude-sonnet-4-6, tool use)
        → tools: query_prometheus, get_alert_context
      → Output: causa raiz + comandos kubectl/helm sugeridos
```

---

## Pré-requisitos

```bash
# 1. Contexto Kind (nunca EKS)
kubectl config current-context
# esperado: kind-camunda-platform-local

# 2. Port-forwards ativos
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093 &

# 3. Etapas 1 e 2 concluídas
#    Alertas preditivos ativos: ZeebeMemoryPredictedHigh, ZeebeBackpressureGrowing, CamundaNamespaceMemoryPressure

# 4. Variável de ambiente da Claude API
export ANTHROPIC_API_KEY=<sua-chave>

# 5. Dependências Python
cd agent && pip install -r requirements.txt
```

---

## O que foi feito

### 1. Estrutura de arquivos

```
agent/
  webhook_receiver.py   # FastAPI: recebe payload do Alertmanager
  reactive_agent.py     # Lógica do agente: tools + loop Claude API
  tools.py              # Implementação das ferramentas Prometheus
  prompts.py            # System prompt e templates
  requirements.txt      # fastapi, uvicorn, anthropic, httpx
```

### 2. Configuração do Alertmanager

Adicionada rota no `values` do kube-prometheus-stack para enviar alertas do Camunda ao webhook local:

```yaml
# alertmanager-values-patch.yaml
alertmanager:
  config:
    route:
      routes:
        - matchers:
            - alertname =~ "Zeebe.*|Camunda.*"
          receiver: camunda-aiops-webhook
    receivers:
      - name: camunda-aiops-webhook
        webhook_configs:
          - url: http://host.docker.internal:5001/webhook
            send_resolved: true
```

Aplicar com:
```bash
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f alertmanager-values-patch.yaml \
  --reuse-values
```

> `host.docker.internal` resolve o host do Kind para o processo Python rodando na máquina local.

### 3. Ferramentas disponíveis para o agente

| Tool | Descrição |
|---|---|
| `query_prometheus_instant` | Executa PromQL instant query em `localhost:9090` |
| `query_prometheus_range` | Executa PromQL range query (para ver tendência) |
| `get_alert_rules` | Lista regras de alerta e seus thresholds |

O agente decide quais ferramentas chamar e em que ordem — o código não prescreve a sequência de análise.

---

## Como validar

Critério de aceite objetivo — a etapa está concluída quando:

1. O webhook recebe um payload do Alertmanager (simulado com `curl` ou alerta real) e o agente responde sem erro
2. O agente chama ao menos 2 ferramentas Prometheus durante a análise (visível nos logs)
3. A resposta final contém:
   - Identificação do recurso problemático
   - Hipótese de causa raiz fundamentada em dados reais
   - Ao menos 1 comando kubectl/helm de remediação sugerido
4. Teste com alerta simulado:

```bash
# Simular disparo do alerta ZeebeMemoryPredictedHigh
curl -X POST http://localhost:5001/webhook \
  -H "Content-Type: application/json" \
  -d @agent/test-fixtures/zeebe-memory-alert.json
```

---

## Validação executada (critério de aceite)

Validação realizada em 2026-05-21 com alerta simulado via `test-fixtures/zeebe-memory-alert.json`.

**Ferramentas chamadas pelo agente:**
- `get_alert_rules` — leu thresholds reais das PrometheusRules do cluster
- `query_prometheus_instant` — G1 Old Gen atual, backpressure, GC activity, memória do namespace
- `query_prometheus_range` — tendência dos últimos 30min do heap Zeebe

**Diagnóstico gerado:**
- Causa raiz identificada: spike transitório na G1 Old Gen com GC intervindo
- Heap atual: 88.8 MB (11.85% do Xmx de 750 MB) — risco baixo no momento da análise
- Descoberta extra: divergência entre threshold absoluto (600 MB) e relativo (85% Xmx) nas PrometheusRules

**Remediação sugerida pelo agente:** 7 comandos kubectl/helm catalogados por prioridade (imediata, preventiva, investigação de regras)

---

## Problemas encontrados

### Saldo insuficiente na Claude API

Na primeira execução, a API retornou `400 - credit balance is too low`. O agente chegou até a chamada da API corretamente — o bloqueio era apenas de créditos. Resolvido com recarga na conta Anthropic.

### `~` não expande em `-d @` do curl

O curl não expande `~` dentro de `-d @~/caminho`. Usar caminho absoluto (`/home/alisson/...`) ou executar o curl a partir do diretório do projeto.

### `host.docker.internal` não resolve em Kind no Linux/WSL2

O hostname `host.docker.internal` é injetado automaticamente apenas no Docker Desktop (Mac/Windows). Em Kind rodando em Linux/WSL2, o Alertmanager (dentro de um pod) não consegue resolver esse nome.

**Solução:** usar o IP do bridge da rede Kind, que é o IP do host visto de dentro dos pods:
```bash
# Descobrir o IP correto
ip addr show | grep "172.18"
# Resultado: 172.18.0.1 (bridge da rede Docker do Kind)
```
Esse IP é fixo enquanto a rede Docker existir. Documentar em qualquer config que use webhook apontando para o host.

### Incompatibilidade entre kube-prometheus-stack v84.3.0 e Prometheus Operator v0.90+

O chart v84 gera o secret do Alertmanager com `group_interval`, `group_wait` e `repeat_interval` no bloco `global` — campos que o Operator v0.90+ rejeita (esses campos pertencem ao `route`). O operator caía em loop de erro e não reconciliava nada, incluindo `AlertmanagerConfig` CRDs.

**Solução:** fornecer `alertmanager.config` completo no values file com `global` contendo apenas `resolve_timeout: 5m`, e aplicar patch direto no secret para garantir que o conteúdo correto seja carregado imediatamente (sem aguardar o operator reconciliar via Helm).

### URL do webhook no AlertmanagerConfig CRD não atualiza imediatamente

O operator não reconcilia CRDs enquanto o base secret é inválido. Após corrigir o secret, é necessário deletar e recriar o `AlertmanagerConfig` para forçar a reconciliação com a nova URL.

---

## Próximo passo

Etapa 4 — Pipeline Python/Prophet: quando houver 4+ semanas de histórico de métricas, substituir `predict_linear` por modelo Prophet com sazonalidade semanal e feriados brasileiros.
