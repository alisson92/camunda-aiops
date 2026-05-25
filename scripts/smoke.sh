#!/usr/bin/env bash
# smoke.sh — envia cards de teste para o Teams e mantém port-forwards ativos
#
# Uso (via Makefile):
#   make smoke                    # todos os cenários
#   make smoke-critical           # cenário específico
#
# Ou diretamente:
#   ./scripts/smoke.sh [critical|warning|info|resolved]

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="/tmp/camunda-aiops-smoke-$$"
mkdir -p "$LOG_DIR"

# ── Cores ─────────────────────────────────────────────────────────────────────

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RED='\033[0;31m'; BOLD='\033[1m'; RESET='\033[0m'

log_step()  { echo -e "\n${BOLD}${CYAN}━━━ $1 ${RESET}"; }
log_ok()    { echo -e "  ${GREEN}✔${RESET} $1"; }
log_info()  { echo -e "  ${CYAN}→${RESET} $1"; }
log_warn()  { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
log_error() { echo -e "  ${RED}✖${RESET} $1" >&2; }

# ── Cleanup ────────────────────────────────────────────────────────────────────

declare -a BG_PIDS=()

cleanup() {
    echo ""
    echo -e "${YELLOW}━━━ Encerrando smoke ━━━${RESET}"
    local pid
    for pid in "${BG_PIDS[@]}"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    done
    log_ok "Port-forwards encerrados. Logs em: ${LOG_DIR}"
}
trap cleanup EXIT INT TERM

# ── Port-forwards opcionais (só quando Kind está ativo) ───────────────────────

ensure_port_forwards() {
    local context
    context=$(kubectl config current-context 2>/dev/null || echo "")

    if [[ "$context" != kind-* ]]; then
        log_warn "Cluster Kind não detectado — links de Dashboard e Silence não funcionarão."
        log_info "Para ativá-los, inicie o Kind e execute: make port-forward"
        return
    fi

    log_step "Kind detectado (${context}) — iniciando port-forwards"

    kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana \
        3000:80 >> "${LOG_DIR}/pf-grafana.log" 2>&1 &
    BG_PIDS+=("$!")
    log_ok "Grafana:      http://localhost:3000"

    kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager \
        9093:9093 >> "${LOG_DIR}/pf-alertmanager.log" 2>&1 &
    BG_PIDS+=("$!")
    log_ok "Alertmanager: http://localhost:9093"

    sleep 2
}

# ── Execução ──────────────────────────────────────────────────────────────────

log_step "Port-forwards (Grafana + Alertmanager)"
ensure_port_forwards

log_step "Enviando cards de teste"
PYTHONPATH="${PROJECT_DIR}/agent" \
    "${PROJECT_DIR}/.venv/bin/python" \
    "${PROJECT_DIR}/tests/smoke/test_teams_notifier.py" "$@"

echo ""
echo -e "  ${YELLOW}Port-forwards ainda ativos.${RESET}"
echo -e "  Interaja com os cards no Teams e pressione ${BOLD}ENTER${RESET} quando terminar."
echo ""
read -r
