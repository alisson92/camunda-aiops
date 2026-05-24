#!/usr/bin/env bash
# =============================================================================
# run-cycle-test.sh
#
# Executa o ciclo completo de teste do agente AIOps:
#   1. Aplica PrometheusRule no cluster
#   2. Inicia port-forwards (Prometheus 9090, Alertmanager 9093, Grafana 3000)
#   3. Inicia o agente (webhook receiver, porta 5001)
#   4. Fast check — envia fixture real ao webhook para confirmar agente → Teams
#   5. Inicia load-generator para criar pressão sustentada
#   6. Monitora alertas disparando e logs do agente em tempo real
#
# Uso:
#   ./scripts/run-cycle-test.sh [--skip-load] [--intensity low|medium|high] [--duration <min>]
#
# Flags:
#   --skip-load    Pula o load-generator (só fast check + observação)
#   --intensity    Intensidade da carga (default: medium)
#   --duration     Duração do load em minutos (default: 20)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# --- Defaults ----------------------------------------------------------------
SKIP_LOAD=false
INTENSITY="medium"
DURATION_MIN=20

# --- Cores -------------------------------------------------------------------
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

# --- Logs e PIDs -------------------------------------------------------------
LOG_DIR="/tmp/camunda-aiops-cycle-$$"
AGENT_LOG="$LOG_DIR/agent.log"
PF_LOG="$LOG_DIR/port-forwards.log"
mkdir -p "$LOG_DIR"

declare -a BG_PIDS=()

# =============================================================================
# Parsing de argumentos
# =============================================================================
while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-load)  SKIP_LOAD=true;      shift   ;;
    --intensity)  INTENSITY="$2";      shift 2 ;;
    --duration)   DURATION_MIN="$2";   shift 2 ;;
    *) echo -e "${RED}Flag desconhecida: $1${NC}"; exit 1 ;;
  esac
done

# =============================================================================
# Helpers
# =============================================================================
log_step() { echo -e "\n${BOLD}${CYAN}━━━ $1 ${NC}"; }
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
log_err()  { echo -e "  ${RED}✗${NC} $1"; }

wait_for_port() {
  local port="$1"
  local label="$2"
  local max_attempts=20
  local attempt=0
  while ! curl -sf "http://localhost:${port}" -o /dev/null 2>/dev/null \
     && ! curl -sf "http://localhost:${port}/-/ready" -o /dev/null 2>/dev/null \
     && ! curl -sf "http://localhost:${port}/api/v1/status/config" -o /dev/null 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge "$max_attempts" ]; then
      log_warn "$label (porta $port) não respondeu após ${max_attempts}s — continuando mesmo assim"
      return 0
    fi
    sleep 1
  done
  log_ok "$label acessível em localhost:${port}"
}

# =============================================================================
# Cleanup — encerra todos os processos em background ao sair
# =============================================================================
cleanup() {
  echo -e "\n${YELLOW}━━━ Encerrando ciclo de teste ━━━${NC}"
  for pid in "${BG_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  # Mata port-forwards pelo padrão do kubectl
  pkill -f "kubectl port-forward.*kube-prometheus" 2>/dev/null || true
  # Remove namespace de carga se existir
  kubectl delete namespace load-test --ignore-not-found=true 2>/dev/null || true
  echo -e "  ${GREEN}✓${NC} Cleanup concluído. Logs em: ${LOG_DIR}"
}
trap cleanup EXIT INT TERM

# =============================================================================
# Passo 0 — Validações iniciais
# =============================================================================
log_step "Passo 0 — Validações"

CURRENT_CONTEXT=$(kubectl config current-context 2>&1)
if [[ "$CURRENT_CONTEXT" != *"kind"* ]]; then
  log_err "Contexto atual é '${CURRENT_CONTEXT}' — não é Kind. Abortando."
  exit 1
fi
log_ok "Contexto Kind confirmado: ${CURRENT_CONTEXT}"

# Verifica que o agente não está já rodando na 5001
if lsof -ti:5001 &>/dev/null; then
  log_warn "Porta 5001 já em uso. Matando processo anterior..."
  lsof -ti:5001 | xargs kill -9 2>/dev/null || true
  sleep 1
fi

# =============================================================================
# Passo 1 — Aplicar PrometheusRule
# =============================================================================
log_step "Passo 1 — Aplicar PrometheusRule"

kubectl apply -f "${PROJECT_DIR}/alerting/camunda-forecasting-rules.yaml"
log_ok "PrometheusRule camunda-forecasting-alerts aplicada"

# Confirma que o Operator carregou as regras (aguarda até 30s)
log_info "Aguardando Prometheus Operator recarregar as regras..."
for i in $(seq 1 6); do
  RULE_COUNT=$(kubectl get prometheusrule -n monitoring camunda-forecasting-alerts \
    -o jsonpath='{.spec.groups[*].rules}' 2>/dev/null | grep -o '"alert"' | wc -l || echo 0)
  if [ "$RULE_COUNT" -gt 0 ]; then
    log_ok "PrometheusRule carregada ($RULE_COUNT regras detectadas)"
    break
  fi
  sleep 5
done

# =============================================================================
# Passo 2 — Port-forwards
# =============================================================================
log_step "Passo 2 — Port-forwards"

log_info "Iniciando port-forward: Prometheus → localhost:9090"
kubectl port-forward -n monitoring \
  svc/kube-prometheus-stack-prometheus 9090:9090 \
  >> "$PF_LOG" 2>&1 &
BG_PIDS+=($!)

log_info "Iniciando port-forward: Alertmanager → localhost:9093"
kubectl port-forward -n monitoring \
  svc/kube-prometheus-stack-alertmanager 9093:9093 \
  >> "$PF_LOG" 2>&1 &
BG_PIDS+=($!)

log_info "Iniciando port-forward: Grafana → localhost:3000"
kubectl port-forward -n monitoring \
  svc/kube-prometheus-stack-grafana 3000:80 \
  >> "$PF_LOG" 2>&1 &
BG_PIDS+=($!)

# Aguarda os serviços responderem
wait_for_port 9090 "Prometheus"
wait_for_port 9093 "Alertmanager"
wait_for_port 3000 "Grafana"

# =============================================================================
# Passo 3 — Iniciar agente
# =============================================================================
log_step "Passo 3 — Agente AIOps (webhook receiver)"

log_info "Iniciando agente em background (log: ${AGENT_LOG})"
cd "${PROJECT_DIR}/agent" && \
  ../.venv/bin/uvicorn webhook_receiver:app \
    --host 0.0.0.0 --port 5001 \
    --log-level info \
    >> "$AGENT_LOG" 2>&1 &
AGENT_PID=$!
BG_PIDS+=($AGENT_PID)
cd "$PROJECT_DIR"

# Aguarda o agente responder
log_info "Aguardando agente subir..."
for i in $(seq 1 15); do
  if curl -sf http://localhost:5001/health -o /dev/null 2>/dev/null; then
    HEALTH=$(curl -s http://localhost:5001/health)
    log_ok "Agente respondendo: ${HEALTH}"
    break
  fi
  sleep 1
done

# =============================================================================
# Passo 4 — Fast check (fixture real → agente → Teams)
# =============================================================================
log_step "Passo 4 — Fast check: fixture → agente → Teams"

FIXTURE="${PROJECT_DIR}/tests/fixtures/zeebe-memory-alert.json"
log_info "Enviando fixture: $(basename $FIXTURE)"

HTTP_STATUS=$(curl -s -o /tmp/cycle-fast-check.json \
  -w "%{http_code}" \
  -X POST http://localhost:5001/webhook \
  -H "Content-Type: application/json" \
  -d @"$FIXTURE")

if [ "$HTTP_STATUS" = "200" ]; then
  PROCESSED=$(python3 -c "import json,sys; d=json.load(open('/tmp/cycle-fast-check.json')); print(d.get('message','?'))" 2>/dev/null || echo "?")
  log_ok "Fast check OK (HTTP $HTTP_STATUS) — $PROCESSED"
  log_info "Aguarde o card chegar no Teams. Logs do agente em tempo real:"
  echo ""
  # Mostra os últimos logs do agente (análise LLM)
  sleep 3
  tail -n 20 "$AGENT_LOG" 2>/dev/null | grep -v "^$" | sed 's/^/    /'
else
  log_warn "Fast check retornou HTTP $HTTP_STATUS. Resposta:"
  cat /tmp/cycle-fast-check.json 2>/dev/null | python3 -m json.tool 2>/dev/null | sed 's/^/    /'
fi

# =============================================================================
# Passo 5 — Load generator (opcional)
# =============================================================================
if [ "$SKIP_LOAD" = true ]; then
  log_warn "Load-generator pulado (--skip-load). Agente continuará rodando para receber alertas reais."
else
  log_step "Passo 5 — Load generator (${INTENSITY}, ${DURATION_MIN}min)"
  log_info "A carga cria pressão de CPU/memória para alimentar as séries temporais."
  log_info "Alertas predict_linear precisam de 30m+ de histórico para disparar organicamente."
  log_warn "Para forçar um alerta agora, envie o fixture manualmente:"
  echo -e "    ${CYAN}curl -X POST http://localhost:5001/webhook -H 'Content-Type: application/json' -d @tests/fixtures/zeebe-memory-alert.json${NC}"
  echo ""

  "${PROJECT_DIR}/scripts/load-generator.sh" \
    --duration "$DURATION_MIN" \
    --intensity "$INTENSITY" &
  LOAD_PID=$!
  BG_PIDS+=($LOAD_PID)
fi

# =============================================================================
# Passo 6 — Monitoramento em tempo real
# =============================================================================
log_step "Passo 6 — Monitoramento"

echo -e "  ${BOLD}Endpoints disponíveis:${NC}"
echo -e "    Prometheus:   ${CYAN}http://localhost:9090/alerts${NC}"
echo -e "    Alertmanager: ${CYAN}http://localhost:9093${NC}"
echo -e "    Grafana:      ${CYAN}http://localhost:3000${NC}  (admin / senha via kubectl)"
echo -e "    Agente:       ${CYAN}http://localhost:5001/health${NC}"
echo ""
echo -e "  ${BOLD}Verificar roteamento do Alertmanager:${NC}"
echo -e "    ${CYAN}curl -s http://localhost:9093/api/v2/status | python3 -m json.tool | grep -A3 camunda${NC}"
echo ""
echo -e "  ${BOLD}Acompanhar logs do agente ao vivo:${NC}"
echo -e "    ${CYAN}tail -f ${AGENT_LOG}${NC}"
echo ""
echo -e "  ${BOLD}Enviar alerta manualmente a qualquer momento:${NC}"
echo -e "    ${CYAN}curl -X POST http://localhost:5001/webhook -H 'Content-Type: application/json' \\"
echo -e "      -d @${PROJECT_DIR}/tests/fixtures/zeebe-memory-alert.json${NC}"
echo ""
echo -e "${YELLOW}  Pressione Ctrl+C para encerrar o ciclo e limpar todos os recursos.${NC}"
echo ""

# Tail do log do agente em primeiro plano (bloqueia até Ctrl+C)
tail -f "$AGENT_LOG"
