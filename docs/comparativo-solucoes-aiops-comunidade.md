# Comparativo: camunda-aiops vs. Soluções da Comunidade

**Contexto:** Este documento foi criado a partir de uma discussão com o time sobre o questionamento legítimo: *"já existe algo pronto feito pela comunidade que poderíamos usar?"* O objetivo é mapear o que existe, entender onde cada solução atua, e deixar claro que as soluções são complementares — não excludentes.

---

## TL;DR

| Pergunta | Resposta |
|---|---|
| Existe algo pronto da comunidade? | Sim — **HolmesGPT** (CNCF Sandbox) é o mais próximo do que foi construído aqui |
| Podemos simplesmente substituir? | Não diretamente — cada solução cobre um escopo diferente |
| As soluções se excluem? | Não — são complementares e podem coexistir no mesmo stack |
| Cabe junto com o `kube-prometheus-stack`? | Sim — HolmesGPT, Robusta e K8sGPT têm Helm charts prontos para isso |
| Qual a contribuição única do `camunda-aiops`? | Forecasting preditivo com PromQL + análise específica do Camunda 8 |

---

## As soluções mapeadas

### 1. HolmesGPT (CNCF Sandbox)

- **Repositório:** [HolmesGPT/holmesgpt](https://github.com/HolmesGPT/holmesgpt) — 2.500 stars
- **Origem:** Robusta.Dev + contribuições da Microsoft. Projeto CNCF Sandbox.
- **O que é:** Agente SRE com loop ReAct que investiga alertas em produção buscando a causa raiz em múltiplas fontes de dados.

**Como funciona:**
```
Alerta (Alertmanager / PagerDuty / OpsGenie)
  → HolmesGPT recebe
  → Loop ReAct: consulta Prometheus, kubectl, Loki, Grafana, etc.
  → Escreve análise de volta no Slack / Teams / PagerDuty
```

**Integrações relevantes para nosso stack:**
- Prometheus/AlertManager nativos
- Microsoft Teams (via Robusta)
- Kubernetes (kubectl describe, logs, eventos)
- Loki, Grafana, Tempo, Helm
- Ollama — **suporte experimental** (tool-calling inconsistente em modelos pequenos)

**Deploy junto com `kube-prometheus-stack`:**
```yaml
# Helm values para instalar junto com kube-prometheus-stack
helm repo add holmesgpt https://holmesgpt.github.io/holmesgpt
helm install holmes holmesgpt/holmes \
  --set config.alertmanager_url=http://kube-prometheus-stack-alertmanager:9093 \
  --set additionalEnvVars[0].name=OLLAMA_API_BASE \
  --set additionalEnvVars[0].value=http://ollama-service:11434 \
  --set modelList.ollama-qwen.model=ollama_chat/qwen2.5:7b \
  --set modelList.ollama-qwen.api_base="{{ env.OLLAMA_API_BASE }}"
```

**Limitação importante para nosso cenário air-gapped:**
O suporte a Ollama é marcado como **experimental** na documentação oficial. A equipe recomenda usar modelos hospedados (Claude, OpenAI) primeiro para validar, depois migrar para local. Tool-calling com modelos menores pode ser inconsistente.

---

### 2. K8sGPT + K8sGPT Operator

- **Repositório:** [k8sgpt-ai/k8sgpt](https://github.com/k8sgpt-ai/k8sgpt) — 7.800 stars
- **Repositório do Operator:** [k8sgpt-ai/k8sgpt-operator](https://github.com/k8sgpt-ai/k8sgpt-operator) — 456 stars
- **O que é:** Scanner de clusters Kubernetes que diagnostica problemas em recursos K8s com linguagem natural. Projeto CNCF.

**Como funciona:**
```
K8sGPT Operator (roda no cluster)
  → Periodicamente varre: Pods, Deployments, Services, Ingresses, etc.
  → Identifica recursos em estado anômalo
  → Enriquece com LLM: "O pod X está em CrashLoopBackOff porque..."
  → Armazena como CRD K8sGPT.Result no cluster
```

**Diferença fundamental em relação ao camunda-aiops:**
K8sGPT não é dirigido por alertas — ele *escaneia ativamente* o cluster. Não recebe webhook do Alertmanager, não analisa métricas Prometheus, não gera runbook por alerta. É mais próximo de um `kubectl describe` inteligente e contínuo.

**Deploy junto com `kube-prometheus-stack`:**
```bash
helm repo add k8sgpt https://charts.k8sgpt.ai/
helm install release k8sgpt/k8sgpt-operator \
  -n k8sgpt-operator-system --create-namespace

# Suporte a LocalAI (OpenAI-compat — funciona com Ollama)
kubectl apply -f - <<EOF
apiVersion: core.k8sgpt.ai/v1alpha1
kind: K8sGPT
metadata:
  name: k8sgpt-local
  namespace: k8sgpt-operator-system
spec:
  ai:
    enabled: true
    model: qwen2.5:7b
    backend: localai
    baseUrl: http://ollama-service.ollama.svc.cluster.local:11434/v1
  noCache: false
EOF
```

---

### 3. Robusta (Classic)

- **Repositório:** [robusta-dev/robusta](https://github.com/robusta-dev/robusta) — 3.000 stars
- **O que é:** Motor de enriquecimento de alertas baseado em regras. Complementa o AlertManager adicionando contexto (screenshots de dashboards, logs recentes, diff de deploys) às notificações.

**Como funciona:**
```
Alerta (Alertmanager) → Robusta
  → Regras: "se ZeebeMemoryPredictedHigh → anexa gráfico Grafana + últimos eventos K8s"
  → Notifica Slack/Teams com contexto enriquecido (sem LLM)
  → Opcional: dispara HolmesGPT para análise AI
```

**Relação com kube-prometheus-stack:**
Robusta tem instalação "all-in-one" com `kube-prometheus-stack` incluído, ou pode ser instalado standalone ao lado de um Prometheus existente. É o wrapper que conecta HolmesGPT ao Alertmanager no cluster.

---

### 4. Grafana LLM App (Plugin Grafana)

- **Repositório:** [grafana/grafana-llm-app](https://github.com/grafana/grafana-llm-app)
- **O que é:** Plugin oficial da Grafana Labs que funciona como **gateway/proxy de LLM dentro do Grafana**. Não é um agente AIOps.

**O que faz:**
- Armazena API keys de providers (OpenAI, Anthropic, Azure, custom)
- Faz proxy de chamadas LLM para outros plugins Grafana não precisarem guardar chaves
- Habilita features como "Explain this panel", resumo de incidentes no Grafana IRM
- Fornece ferramentas MCP (dashboards, OnCall, Asserts) para uso em chat

**O que NÃO faz:**
- Não recebe webhooks do Alertmanager
- Não executa loop ReAct de investigação
- Não gera runbooks por alerta
- Não notifica o Teams com análise estruturada

---

## Comparativo direto: camunda-aiops vs. comunidade

| Capacidade | camunda-aiops | HolmesGPT | K8sGPT | Robusta | Grafana LLM App |
|---|:---:|:---:|:---:|:---:|:---:|
| **Receber alertas do Alertmanager (webhook)** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Loop ReAct com tool use** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Consultar Prometheus como ferramenta** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Forecasting preditivo (predict_linear, deriv)** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Análise específica Camunda 8 (Zeebe, etc.)** | ✅ | ⚠️ genérico | ❌ | ⚠️ genérico | ❌ |
| **Geração de runbook por alerta** | ✅ | ⚠️ básico | ❌ | ⚠️ links | ❌ |
| **RAG com histórico de incidentes** | ✅ | ✅ catálogos | ❌ | ❌ | ❌ |
| **Notificação Teams com Adaptive Card** | ✅ | ✅ via Robusta | ❌ | ✅ | ❌ |
| **Deduplicação por fingerprint** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Webhook assíncrono (202 imediato)** | ✅ | ✅ | ❌ | ✅ | ❌ |
| **Observabilidade do agente (/metrics)** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Ollama / LLM local (air-gapped)** | ✅ nativo | ⚠️ experimental | ✅ LocalAI | ⚠️ via HolmesGPT | ❌ |
| **Scan proativo de recursos K8s** | ❌ | ❌ | ✅ | ❌ | ❌ |
| **"Explain this panel" no Grafana** | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Helm chart pronto** | ❌ ainda | ✅ | ✅ | ✅ | ✅ plugin |
| **Deploy como pod no cluster** | ⚠️ manual | ✅ | ✅ | ✅ | ✅ |
| **CNCF / comunidade** | lab | ✅ CNCF Sandbox | ✅ CNCF | comunidade | Grafana Labs |

Legenda: ✅ suportado · ⚠️ parcial/limitações · ❌ não cobre

---

## Por que as soluções são complementares, não excludentes

Cada ferramenta atua em uma **camada diferente do ciclo AIOps**:

```
┌─────────────────────────────────────────────────────────────────┐
│  PREVENÇÃO (antes do alerta)                                    │
│  camunda-aiops: forecasting preditivo com PromQL                │
│  → predict_linear, deriv, double_exponential_smoothing          │
│  → PrometheusRules: alerta ANTES do problema ocorrer            │
└─────────────────────────┬───────────────────────────────────────┘
                          │ alerta dispara
┌─────────────────────────▼───────────────────────────────────────┐
│  TRIAGEM E ENRIQUECIMENTO (contexto inicial)                    │
│  Robusta Classic: regras determinísticas                        │
│  → screenshot do dashboard Grafana                              │
│  → últimos eventos K8s no namespace                             │
│  → diff de deploys recentes                                     │
└─────────────────────────┬───────────────────────────────────────┘
                          │ alerta enriquecido
┌─────────────────────────▼───────────────────────────────────────┐
│  INVESTIGAÇÃO COM IA (causa raiz)                               │
│  HolmesGPT ou camunda-aiops:                                   │
│  → loop ReAct: consulta Prometheus, kubectl, Loki               │
│  → análise específica por componente (Zeebe, Elasticsearch)     │
│  → geração de runbook                                           │
└─────────────────────────┬───────────────────────────────────────┘
                          │ análise concluída
┌─────────────────────────▼───────────────────────────────────────┐
│  NOTIFICAÇÃO E AÇÃO                                             │
│  Teams (Adaptive Card) · Slack · PagerDuty · Jira               │
└─────────────────────────────────────────────────────────────────┘
                          +
┌─────────────────────────────────────────────────────────────────┐
│  DIAGNÓSTICO PROATIVO (paralelo, não reativo)                   │
│  K8sGPT Operator: varre recursos K8s continuamente              │
│  → detecta pods CrashLoopBackOff, Pending, configurações ruins  │
│  → antes do alerta surgir                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Cenário ideal de adoção: junto com kube-prometheus-stack

O `kube-prometheus-stack` já fornece Prometheus + AlertManager + Grafana. O stack AIOps pode ser adicionado sem substituir nada:

```
kube-prometheus-stack (existente)
├── prometheus
├── alertmanager
│   └── webhook → HolmesGPT (ou camunda-aiops) ← novo
└── grafana
    └── plugin grafana-llm-app ← novo (opcional)

Adicionados como releases Helm separados:
├── robusta/robusta ← enriquecimento de alertas
├── holmesgpt/holmes ← investigação com AI
└── k8sgpt/k8sgpt-operator ← diagnóstico proativo K8s
```

**Configuração mínima do Alertmanager para rotear para HolmesGPT:**
```yaml
# Trecho do alertmanager config (values do kube-prometheus-stack)
alertmanager:
  config:
    receivers:
      - name: holmesgpt
        webhook_configs:
          - url: http://holmes-service:80/api/alerts
            send_resolved: true
    route:
      receiver: holmesgpt
      # Para coexistir com outros receivers (Teams, Slack, etc.):
      routes:
        - receiver: holmesgpt
          continue: true  # continua para os demais receivers
```

---

## Quando usar cada um

| Cenário | Recomendação |
|---|---|
| Alertas K8s genéricos (CrashLoop, OOM, Pending) | HolmesGPT — tem toolsets K8s prontos |
| Alertas específicos do Camunda 8 (Zeebe, backpressure) | camunda-aiops — análise direcionada ao Camunda |
| Diagnóstico proativo (antes do alerta) | K8sGPT Operator |
| Enriquecimento visual (screenshot, eventos, diff) | Robusta Classic |
| Air-gapped com Ollama em produção | camunda-aiops — suporte nativo vs. experimental no HolmesGPT |
| Chat e "explain panel" dentro do Grafana | Grafana LLM App |
| Time sem capacidade de manter código Python | HolmesGPT — solução pronta da comunidade |

---

## O que o camunda-aiops tem de único

Mesmo com soluções da comunidade maduras, o `camunda-aiops` cobre um nicho não coberto por nenhuma delas:

1. **Forecasting preditivo específico para Camunda 8** — PrometheusRules com `predict_linear`, `deriv` e `double_exponential_smoothing` calibradas para o comportamento do Zeebe (JVM heap com GC, filas de backpressure, RocksDB)

2. **Suporte Ollama nativo e validado** — HolmesGPT tem Ollama marcado como "experimental" com ressalva sobre tool-calling inconsistente. O camunda-aiops foi construído com Ollama como provider primário e validado com `qwen2.5:7b`

3. **RAG com conhecimento de incidentes do time** — base de conhecimento local (`data/knowledge/`) com exemplos curados pelo próprio time sobre os alertas que eles já enfrentaram

4. **Ciclo completo documentado e testado** — 224 testes unitários + integração + E2E, 100% cobertura, CI em 5 jobs

---

## Caminho recomendado

A sequência de menor fricção para adicionar AIOps ao `kube-prometheus-stack`:

**Curto prazo — adicionar soluções da comunidade:**
1. Instalar **K8sGPT Operator** → diagnóstico proativo K8s sem configuração de LLM
2. Instalar **HolmesGPT** com OpenAI/Claude → validar investigação de alertas genéricos
3. Instalar **Grafana LLM App** → habilitar "explain panel" no Grafana

**Médio prazo — Ollama no cluster:**
4. Deploy Ollama como pod (`ollama/ollama` Helm chart) com o modelo `qwen2.5:7b`
5. Configurar HolmesGPT → Ollama (testar tool-calling com alertas reais)
6. Configurar `camunda-aiops` → como serviço focado em alertas Camunda

**Longo prazo — consolidação:**
7. Avaliar se HolmesGPT + toolset customizado Camunda cobre o mesmo que `camunda-aiops`
8. Se sim: migrar lógica de análise Camunda para toolset HolmesGPT (contribuição upstream possível)
9. Se não: manter `camunda-aiops` focado no nicho Camunda + forecasting

---

## Referências

| Recurso | Link |
|---|---|
| HolmesGPT — documentação | https://holmesgpt.dev |
| HolmesGPT — suporte Ollama | https://holmesgpt.dev/ai-providers/ollama/ |
| HolmesGPT — Helm chart | https://github.com/HolmesGPT/holmesgpt/tree/master/helm/holmes |
| K8sGPT — documentação | https://docs.k8sgpt.ai |
| K8sGPT Operator — Helm | https://github.com/k8sgpt-ai/k8sgpt-operator |
| Robusta — instalação | https://docs.robusta.dev/master/setup-robusta/installation/ |
| Grafana LLM App — GitHub | https://github.com/grafana/grafana-llm-app |
| Grafana LLM App — plugin | https://grafana.com/grafana/plugins/grafana-llm-app/ |
