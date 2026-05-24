---
titulo: Etapa 2 — Grafana MCP Server (AIOps básico)
data: 2026-05-21
status: concluída
depende-de: etapa-1-prometheus-rules.md
---

# Etapa 2 — Grafana MCP Server (AIOps básico)

## Objetivo

Conectar o Claude ao Grafana via **Grafana MCP Server**, permitindo que o modelo consulte métricas e alertas do ambiente em linguagem natural — sem necessidade de escrever PromQL manualmente.

Esta etapa transforma o lab de "visualização preditiva + alertas automáticos" em **AIOps básico**: o Claude passa a ser um interlocutor ativo que pode responder perguntas como "qual alerta preditivo está mais próximo de disparar?" ou "qual namespace está consumindo mais memória agora?" com dados reais do cluster.

### Escopo desta etapa

Datasources disponíveis e cobertos:
- **Prometheus** — métricas e alertas preditivos (Etapa 1)
- **Alertmanager** — estado de alertas, silêncios

Fora de escopo (sem Loki instalado):
- Correlação métricas + logs — postergado para quando Loki estiver disponível no ambiente

---

## Pré-requisitos

```bash
# 1. Contexto Kind (nunca EKS)
kubectl config current-context
# esperado: kind-camunda-platform-local

# 2. Port-forwards ativos
# Prometheus
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
# Grafana
kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &
# Alertmanager (necessário para o MCP gerenciar silêncios)
kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager 9093:9093 &

# 3. Grafana acessível
curl -s http://localhost:3000/api/health | jq .

# 4. Alertas da Etapa 1 validados
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[].rules[].name'
# esperado: ZeebeMemoryPredictedHigh, ZeebeBackpressureGrowing, CamundaNamespaceMemoryPressure
```

---

## O que foi feito

### 1. Instalação do binário `mcp-grafana`

```bash
go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest
# binário instalado em ~/go/bin/mcp-grafana (v0.14.0)
```

> O binário não é adicionado ao PATH automaticamente. A configuração abaixo usa o caminho absoluto para evitar dependência de PATH.

### 2. Service account no Grafana

Criada via API (role `Viewer` — suficiente para leitura de métricas e alertas):

```bash
GRAFANA_PASS=$(kubectl get secret -n monitoring kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d)

# Criar service account (caso já exista, buscar o ID)
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{"name":"mcp-grafana-sa","role":"Viewer"}' \
  -u "admin:${GRAFANA_PASS}" \
  http://localhost:3000/api/serviceaccounts

# Buscar ID se já existir
curl -s -u "admin:${GRAFANA_PASS}" \
  "http://localhost:3000/api/serviceaccounts/search?query=mcp-grafana-sa" \
  | jq '.serviceAccounts[0].id'

# Gerar token (SA_ID = ID retornado acima)
curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{"name":"mcp-token","secondsToLive":0}' \
  -u "admin:${GRAFANA_PASS}" \
  "http://localhost:3000/api/serviceaccounts/${SA_ID}/tokens"
```

O token gerado (`key`) é o valor de `GRAFANA_API_KEY`. `secondsToLive: 0` = sem expiração.

### 3. Arquivos de configuração do Claude Code

**`.mcp.json`** (commitável — sem secrets):
```json
{
  "mcpServers": {
    "grafana": {
      "command": "/home/alisson/go/bin/mcp-grafana",
      "args": [],
      "env": {
        "GRAFANA_URL": "http://localhost:3000"
      }
    }
  }
}
```

**`.claude/settings.json`** (commitável):
```json
{
  "enableAllProjectMcpServers": true
}
```

**`.claude/settings.local.json`** (gitignored — contém o token):
```json
{
  "env": {
    "GRAFANA_API_KEY": "<token gerado no passo 2>"
  },
  "enableAllProjectMcpServers": true
}
```

> O processo `mcp-grafana` herda as variáveis de env da sessão do Claude Code — `GRAFANA_API_KEY` definido em `settings.local.json` chega ao servidor MCP sem precisar estar no `.mcp.json`.

**`.gitignore`** atualizado com:
```
.claude/settings.local.json
```

### 4. Ativar o MCP server

O servidor só carrega ao **reiniciar a sessão** do Claude Code:

```bash
cd ~/personal/projects/camunda-aiops
claude
```

Após reiniciar, verificar em `/mcp` — deve aparecer `grafana` com status `connected`.

---

## Como validar

Critério de aceite objetivo — a etapa está concluída quando:

1. O Claude Code consegue, via MCP, executar a query abaixo e retornar valor numérico:
   ```
   predict_linear(container_memory_working_set_bytes{namespace="camunda"}[15m], 1800)
   ```

2. O Claude consegue listar os alertas ativos/pendentes do Alertmanager via MCP

3. Pelo menos uma pergunta em linguagem natural respondida com dados reais do cluster, ex:
   > "Qual dos três alertas preditivos está mais próximo de disparar?"

---

## Validação executada (critério de aceite)

Validações realizadas em 2026-05-21 com MCP conectado (`grafana` — `connected`):

### 1. Datasources listados via MCP

```
mcp__grafana__list_datasources →
  - Prometheus  (UID: prometheus,   tipo: prometheus, default: true)
  - Alertmanager (UID: alertmanager, tipo: alertmanager)
```

### 2. Dashboard encontrado via MCP

```
mcp__grafana__search_dashboards(query="camunda") →
  - uid: camunda-local-forecasting
  - title: "Camunda Local — Forecasting com PromQL"
  - tags: [camunda, forecasting, kind, local]
```

### 3. Query PromQL executada via MCP com dados reais

```promql
predict_linear(jvm_memory_used_bytes{pod="camunda-zeebe-0", id="G1 Old Gen"}[30m], 1800)
→ ~92.5 MB projetado em 30min (threshold do alerta: 600 MB)
```

### 4. Pergunta em linguagem natural respondida com dados reais

> "Qual dos três alertas preditivos está mais próximo de disparar?"

| Alerta | Valor projetado (30min) | Threshold | % do limite |
|---|---|---|---|
| `CamundaNamespaceMemoryPressure` | ~3.74 GB | 6 GB | **62%** — mais próximo |
| `ZeebeMemoryPredictedHigh` | ~92.5 MB | 600 MB | 15% |
| `ZeebeBackpressureGrowing` | sem dados | deriv > 0 | N/A |

O maior consumidor de memória do namespace é `camunda-optimize` (~1.36 GB projetado).

---

## Problemas encontrados

### `zeebe_backpressure_requests_total` sem dados

A métrica `zeebe_backpressure_requests_total` não retornou dados via `deriv()`.

**Causa provável:** o ServiceMonitor do Zeebe pode não estar coletando esse endpoint específico, ou a métrica ainda não foi exposta pelo Zeebe 8.9 neste ambiente. Em um ambiente com carga real, o Zeebe expõe backpressure via `/actuator/prometheus`.

**Impacto:** o alerta `ZeebeBackpressureGrowing` fica com `state: inactive` por ausência de série temporal, não por ausência de problema real. Monitorar se a métrica aparecer após geração de carga com `02-load-generator.sh`.

---

## Próximo passo

Etapa 3 — Agente reativo com Claude API: ao disparar um alerta da Etapa 1, acionar automaticamente um agente que consulta o MCP e gera hipótese de causa raiz.
