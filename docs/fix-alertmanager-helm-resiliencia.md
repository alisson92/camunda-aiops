---
titulo: "Fix — Alertmanager: config resiliente a helm upgrade"
data: "2026-05-22"
status: "concluído"
relacionado: "etapa-3-agente-reativo-claude-api"
---

# Fix — Alertmanager: config resiliente a helm upgrade

## Problema

A configuração do Alertmanager (webhook para o agente AIOps) estava sendo mantida via `kubectl patch` direto no Secret `alertmanager-kube-prometheus-stack-alertmanager`. Isso tornava a config frágil: qualquer `helm upgrade` regenerava o Secret a partir dos Helm values e revertia para a URL errada (`host.docker.internal`), quebrando o ciclo silenciosamente.

Dois problemas estavam presentes:
1. A URL `host.docker.internal` não resolve em Kind/WSL2 — o IP correto do host é `172.18.0.1`.
2. O bloco `alertmanager.config` não existia no values file — foi inserido via `helm upgrade --set` numa sessão anterior, sem persistência no arquivo versionado.

---

## Como foi resolvido

A config completa do Alertmanager foi adicionada ao arquivo `prometheus-values.yaml` do projeto `camunda-kind`:

```
camunda-kind/monitoring/prometheus-values.yaml
```

Trecho adicionado:

```yaml
alertmanager:
  config:
    global:
      resolve_timeout: 5m
    receivers:
      - name: "null"
      - name: camunda-aiops-webhook
        webhook_configs:
          - url: "http://172.18.0.1:5001/webhook"  # IP do host na rede bridge do Docker/Kind em WSL2
            send_resolved: true
            http_config:
              follow_redirects: true
    route:
      receiver: "null"
      routes:
        - matchers: ['alertname =~ "InfoInhibitor|Watchdog"']
          receiver: "null"
        - group_wait: 10s
          matchers: ['alertname =~ "Zeebe.*|Camunda.*"']
          receiver: camunda-aiops-webhook
          repeat_interval: 1h
```

### Conflito de field manager

O `kubectl patch` anterior criou uma entrada `kubectl-patch` nos `managedFields` do Secret. Isso causou conflito ao tentar fazer o `helm upgrade` normalmente.

**Resolução:**

```bash
# Deletar o Secret para limpar o field manager (o Helm o recria no upgrade)
kubectl delete secret alertmanager-kube-prometheus-stack-alertmanager -n monitoring

# Aplicar o upgrade — o Helm recria o Secret como owner correto
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --version 84.3.0 \
  --reuse-values \
  -f camunda-kind/monitoring/prometheus-values.yaml
```

---

## Como validar

```bash
# Confirmar URL correta no Secret gerenciado pelo Helm
kubectl get secret alertmanager-kube-prometheus-stack-alertmanager -n monitoring \
  -o jsonpath='{.data.alertmanager\.yaml}' | base64 -d | grep url
# Esperado: url: http://172.18.0.1:5001/webhook

# Confirmar que não há mais conflito de field manager
kubectl get secret alertmanager-kube-prometheus-stack-alertmanager -n monitoring \
  -o jsonpath='{.metadata.managedFields[*].manager}'
# Esperado: apenas "helm" ou "Go-http-client" — sem "kubectl-patch"
```

---

## Atenção para o time

- **Se o cluster Kind for recriado:** reaplicar o Helm upgrade com o values file — a config volta automaticamente.
- **Para descobrir o IP do host em um novo ambiente:**
  ```bash
  ip route show | grep default | awk '{print $3}'
  # ou
  cat /etc/resolv.conf | grep nameserver | awk '{print $2}'
  ```
- **Nunca usar `host.docker.internal` neste ambiente** — não resolve em Kind/WSL2. Usar o IP da bridge Docker diretamente.

---

## Próximo passo

Executar `helm upgrade` sempre com o values file para garantir consistência:

```bash
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --version 84.3.0 \
  --reuse-values \
  -f camunda-kind/monitoring/prometheus-values.yaml
```
