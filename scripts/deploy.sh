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

# ── 1. Build ──────────────────────────────────────────────────────────────────
step "1/7" "Build da imagem ${IMAGE_NAME}:${IMAGE_TAG}"
docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" "${PROJECT_DIR}"
ok "Imagem construída."

# ── 2. Kind load ──────────────────────────────────────────────────────────────
step "2/7" "Carregando imagem no Kind (${KIND_CLUSTER})"
kind load docker-image "${IMAGE_NAME}:${IMAGE_TAG}" --name "${KIND_CLUSTER}"
ok "Imagem disponível nos nós do cluster."

# ── 3. Secret ─────────────────────────────────────────────────────────────────
step "3/7" "Verificando Secret"
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
step "4/7" "Aplicando manifests (PVC, Deployment, Service, CronJob)"
kubectl apply -k "${PROJECT_DIR}/deploy/"
ok "Manifests aplicados."

# ── 5. AGENT_PUBLIC_URL dinâmico ──────────────────────────────────────────────
step "5/7" "Injetando AGENT_PUBLIC_URL com IP do NodePort"
NODE_IP=$(kubectl get nodes \
  -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')

if [ -z "$NODE_IP" ]; then
    err "Não foi possível obter o IP do nó Kind."
    exit 1
fi

kubectl set env deployment/camunda-aiops-agent \
  -n camunda \
  "AGENT_PUBLIC_URL=http://${NODE_IP}:30501"

info "AGENT_PUBLIC_URL=http://${NODE_IP}:30501"
info "Aguardando rollout concluir..."
kubectl rollout status deployment/camunda-aiops-agent -n camunda --timeout=120s
ok "Rollout concluído."

# ── 6. Alertmanager ───────────────────────────────────────────────────────────
step "6/7" "Configurando Alertmanager (helm upgrade)"
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  --reuse-values \
  -f "${PROJECT_DIR}/deploy/alertmanager-values.yaml"
ok "Alertmanager atualizado — receiver aponta para o service interno do cluster."

# ── 7. Health check ───────────────────────────────────────────────────────────
step "7/7" "Health check"
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

echo ""
echo -e "${BOLD}${GREEN}Deploy concluído.${RESET}"
echo -e "  Webhook:  ${CYAN}http://${NODE_IP}:30501/webhook${RESET}"
echo -e "  Logs:     ${CYAN}make k8s-logs${RESET}"
echo ""

# Exporta o NODE_IP para uso pelo caller (make deploy / deploy-fast)
export AIOPS_NODE_IP="$NODE_IP"
