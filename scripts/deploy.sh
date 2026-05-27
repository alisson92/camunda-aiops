#!/usr/bin/env bash
# deploy.sh — deploy do agente AIOps no cluster Kind
#
# Executado por 'make deploy' e 'make deploy-fast'.
# Não chamar diretamente — use o Makefile para garantir variáveis corretas.
#
# Passos:
#   1. Build da imagem Docker
#   2. kind load (sem registry externo)
#   3. Verifica Secret com credenciais
#   4. kubectl apply -k deploy/
#   5. Injeta AGENT_PUBLIC_URL com IP real do NodePort
#   6. Aguarda rollout concluir
#   7. Configura Alertmanager via helm upgrade
#   8. Health check final
#   9. Validação do ciclo: webhook → agente → LLM → Teams

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

IMAGE_NAME="${IMAGE_NAME:-camunda-aiops-agent}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
KIND_CLUSTER="${KIND_CLUSTER:-camunda-platform-local}"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'
BOLD='\033[1m'; RESET='\033[0m'

step() { echo -e "\n${BOLD}${CYAN}[$1] $2${RESET}"; }
ok()   { echo -e "  ${GREEN}✔${RESET} $1"; }
info() { echo -e "  ${CYAN}→${RESET} $1"; }
err()  { echo -e "  ${RED}✖${RESET} $1" >&2; }

# ── Pre-flight: Ollama acessível pelo IP da bridge Docker ─────────────────────
# Pods Kind são containers Docker — alcançam o host WSL2 via IP da bridge Docker
# (172.17.0.1), não via gateway padrão (que é o Windows Host, não o WSL2).
# Ollama deve escutar em 0.0.0.0 (não só 127.0.0.1).
# Correção permanente: sudo systemctl edit ollama → Environment="OLLAMA_HOST=0.0.0.0"
echo -e "\n${BOLD}${CYAN}[pre-flight] Verificando Ollama na bridge Docker${RESET}"

DOCKER_HOST_IP=$(ip addr show docker0 2>/dev/null | awk '/inet / {split($2,a,"/"); print a[1]; exit}')

if [ -z "$DOCKER_HOST_IP" ]; then
    err "Interface docker0 não encontrada — Docker está rodando?"
    exit 1
fi

if curl -sf "http://${DOCKER_HOST_IP}:11434/api/tags" -o /dev/null 2>/dev/null; then
    ok "Ollama acessível em http://${DOCKER_HOST_IP}:11434 (bridge Docker — visível aos pods Kind)."
else
    err "Ollama não responde em http://${DOCKER_HOST_IP}:11434"
    echo ""
    echo "  O Ollama está escutando apenas em 127.0.0.1."
    echo "  Pods Kind usam a bridge Docker (${DOCKER_HOST_IP}) para alcançar o host WSL2."
    echo ""
    echo "  Correção permanente (recomendada):"
    echo -e "  ${BOLD}sudo EDITOR=vim systemctl edit ollama${RESET}"
    echo "    # adicione no editor:"
    echo "    [Service]"
    echo "    Environment=\"OLLAMA_HOST=0.0.0.0\""
    echo -e "  ${BOLD}sudo systemctl daemon-reload && sudo systemctl restart ollama${RESET}"
    echo ""
    exit 1
fi

# ── 1. Build ──────────────────────────────────────────────────────────────────
step "1/9" "Build da imagem ${IMAGE_NAME}:${IMAGE_TAG}"
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" "${PROJECT_DIR}"
ok "Imagem construída."

# ── 2. Kind load ──────────────────────────────────────────────────────────────
step "2/9" "Carregando imagem no Kind (${KIND_CLUSTER})"
kind load docker-image "${IMAGE_NAME}:${IMAGE_TAG}" --name "${KIND_CLUSTER}"
ok "Imagem disponível nos nós do cluster."

# ── 3. Secret ─────────────────────────────────────────────────────────────────
step "3/9" "Verificando Secret"
if ! kubectl get secret camunda-aiops-secret -n camunda > /dev/null 2>&1; then
    err "Secret 'camunda-aiops-secret' não encontrado no namespace camunda."
    echo ""
    echo "  Crie o Secret com os valores reais antes de continuar:"
    echo -e "  ${BOLD}cp deploy/secret.example.yaml deploy/secret.yaml${RESET}"
    echo -e "  ${BOLD}# edite deploy/secret.yaml${RESET}"
    echo -e "  ${BOLD}kubectl apply -f deploy/secret.yaml -n camunda${RESET}"
    echo ""
    exit 1
fi
ok "Secret encontrado."

# ── 4. Manifests ──────────────────────────────────────────────────────────────
step "4/9" "Aplicando manifests (PVC, Deployment, Service, CronJob)"
kubectl apply -k "${PROJECT_DIR}/deploy/"
ok "Manifests aplicados."

# ── 5. AGENT_PUBLIC_URL dinâmico ──────────────────────────────────────────────
step "5/9" "Injetando AGENT_PUBLIC_URL com IP do NodePort"
NODE_IP=$(kubectl get nodes \
  -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')

if [ -z "$NODE_IP" ]; then
    err "Não foi possível obter o IP do nó Kind."
    exit 1
fi

kubectl set env deployment/camunda-aiops-agent \
  -n camunda \
  "AGENT_PUBLIC_URL=http://${NODE_IP}:30501"
ok "AGENT_PUBLIC_URL=http://${NODE_IP}:30501"

# ── 6. Rollout ────────────────────────────────────────────────────────────────
step "6/9" "Aguardando rollout concluir"
kubectl rollout status deployment/camunda-aiops-agent -n camunda --timeout=120s
ok "Rollout concluído."

# ── 7. Alertmanager ───────────────────────────────────────────────────────────
step "7/9" "Configurando Alertmanager (helm upgrade)"
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  --reuse-values \
  -f "${PROJECT_DIR}/deploy/alertmanager-values.yaml"
ok "Alertmanager atualizado — receiver aponta para o service interno do cluster."

# ── 8. Health check ───────────────────────────────────────────────────────────
step "8/9" "Health check"
sleep 2
HEALTH=$(curl -sf "http://${NODE_IP}:30501/health" 2>/dev/null || echo "")

if [ -z "$HEALTH" ]; then
    err "Agente não respondeu em http://${NODE_IP}:30501/health"
    echo ""
    echo "  Verifique os logs:"
    echo -e "  ${BOLD}make k8s-logs${RESET}"
    exit 1
fi

echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"
ok "Agente respondendo."

# ── 9. Validação do ciclo: webhook → agente → LLM → Teams ────────────────────
step "9/9" "Validação do ciclo completo (webhook → LLM → Teams)"

FIXTURE="${PROJECT_DIR}/tests/fixtures/zeebe-backpressure-growing-alert.json"
WEBHOOK_URL="http://${NODE_IP}:30501/webhook"
METRICS_URL="http://${NODE_IP}:30501/metrics"
WEBHOOK_RESP="/tmp/deploy-webhook-check-$$.json"

if [ ! -f "$FIXTURE" ]; then
    info "Fixture não encontrado — execute 'make generate-fixtures' e re-deploy."
    info "Pulando validação do ciclo."
else
    # Captura baseline de aiops_alerts_processed_total antes de enviar.
    # A métrica tem labels: aiops_alerts_processed_total{alertname="..."} 1.0
    # grep sem espaço após o nome para casar com '{' que precede os labels.
    BASELINE=$(curl -sf "$METRICS_URL" 2>/dev/null \
        | grep '^aiops_alerts_processed_total{' \
        | awk '{sum += int($NF)} END {print sum+0}' || echo "0")

    info "Enviando fixture ao webhook do pod (${WEBHOOK_URL})..."
    HTTP_STATUS=$(curl -s -o "$WEBHOOK_RESP" -w "%{http_code}" \
        -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d @"$FIXTURE" 2>/dev/null || echo "000")

    if [[ "$HTTP_STATUS" != "200" && "$HTTP_STATUS" != "202" ]]; then
        err "Webhook retornou HTTP ${HTTP_STATUS} — esperado 200 ou 202."
        echo ""
        echo "  Verifique os logs do pod:"
        echo -e "  ${BOLD}make k8s-logs${RESET}"
        exit 1
    fi

    QUEUED=$(python3 -c \
        "import json; print(json.load(open('${WEBHOOK_RESP}')).get('queued', 0))" \
        2>/dev/null || echo "0")
    ok "Webhook recebeu o alerta (HTTP ${HTTP_STATUS}, queued=${QUEUED})"

    # Aguarda LLM processar — Ollama local pode levar até 120s
    info "Aguardando análise do LLM (até 120s)..."
    PROCESSED=0
    for idx in $(seq 1 24); do
        METRICS=$(curl -sf "$METRICS_URL" 2>/dev/null || echo "")
        PROCESSED=$(echo "$METRICS" \
            | grep '^aiops_alerts_processed_total{' \
            | awk '{sum += int($NF)} END {print sum+0}' || echo "0")
        if [ "${PROCESSED}" -gt "${BASELINE}" ]; then
            break
        fi
        info "  [${idx}/24] aguardando... (processed=${PROCESSED}, baseline=${BASELINE})"
        sleep 5
    done

    if [ "${PROCESSED}" -gt "${BASELINE}" ]; then
        ok "LLM processou o alerta (aiops_alerts_processed_total=${PROCESSED})"

        # Confirma entrega no Teams via log do pod
        NOTIFIED=$(kubectl logs -n camunda -l app=camunda-aiops-agent --tail=100 2>/dev/null \
            | grep -c "Notificação enviada" || echo "0")
        if [ "${NOTIFIED}" -ge 1 ]; then
            ok "Teams notificado com sucesso (${NOTIFIED} notificação(ões) no log do pod)."
        else
            info "Notificação Teams não confirmada nos logs ainda — verifique o canal."
        fi
    else
        err "LLM não processou o alerta em 120s."
        echo ""
        echo "  Diagnóstico:"
        echo -e "  ${BOLD}make k8s-logs${RESET}"
        echo -e "  ${BOLD}kubectl describe pod -n camunda -l app=camunda-aiops-agent${RESET}"
        exit 1
    fi
fi

echo ""
echo -e "${BOLD}${GREEN}Deploy concluído.${RESET}"
echo -e "  Webhook:  ${CYAN}http://${NODE_IP}:30501/webhook${RESET}"
echo -e "  Logs:     ${CYAN}make k8s-logs${RESET}"
echo ""

# Exporta o NODE_IP para uso pelo caller (make deploy / deploy-fast)
export AIOPS_NODE_IP="$NODE_IP"
