#!/usr/bin/env bash
# demo.sh — ciclo de demo do agente AIOps para apresentação ao time
#
# Injeta payloads reais do Alertmanager no webhook local sem precisar do Kind.
# Pré-requisitos: make run (agente rodando na porta 5001) + Ollama com qwen2.5:7b
#
# Uso:
#   ./scripts/demo.sh                  # ciclo completo (4 cenários)
#   ./scripts/demo.sh --scenario zeebe # apenas ZeebeMemoryPredictedHigh
#   ./scripts/demo.sh --list           # lista os cenários disponíveis
#   ./scripts/demo.sh --dry-run        # mostra o que seria enviado sem executar

set -euo pipefail

# ── Constantes ────────────────────────────────────────────────────────────────

WEBHOOK_URL="${WEBHOOK_URL:-http://localhost:5001/webhook}"
FIXTURES_DIR="$(cd "$(dirname "$0")/../tests/fixtures" && pwd)"
DELAY_BETWEEN="${DELAY_BETWEEN:-3}"  # segundos entre cenários

# Cores para output legível
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────

log_banner() {
    echo ""
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${CYAN}  $1${RESET}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
}

log_step() {
    echo -e "${BOLD}▶ $1${RESET}"
}

log_ok() {
    echo -e "${GREEN}✔ $1${RESET}"
}

log_warn() {
    echo -e "${YELLOW}⚠ $1${RESET}"
}

log_error() {
    echo -e "${RED}✖ $1${RESET}" >&2
}

# Envia um fixture para o webhook e exibe a resposta formatada
send_scenario() {
    local label="$1"
    local fixture_file="$2"
    local severity="$3"

    echo ""
    log_step "Cenário: ${label} [${severity}]"
    echo -e "  Fixture: ${fixture_file}"
    echo -e "  Endpoint: ${WEBHOOK_URL}"
    echo ""

    if [[ "${DRY_RUN}" == "true" ]]; then
        log_warn "dry-run: payload não enviado"
        return
    fi

    local response
    local http_code

    # Captura o corpo da resposta e o HTTP status code separadamente
    response=$(curl -s -w "\n__HTTP_STATUS__%{http_code}" \
        -X POST "${WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d @"${FIXTURES_DIR}/${fixture_file}" \
        --max-time 120)  # 120s: LLM local pode demorar

    http_code=$(echo "${response}" | grep '__HTTP_STATUS__' | sed 's/__HTTP_STATUS__//')
    body=$(echo "${response}" | grep -v '__HTTP_STATUS__')

    if [[ "${http_code}" == "200" ]]; then
        log_ok "HTTP ${http_code} — webhook processado"
        # Extrai e exibe o texto de análise se presente
        if command -v python3 &>/dev/null; then
            analysis=$(echo "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    analyses = data.get('analyses', [])
    if analyses:
        print('\n  📋 Análise do agente:')
        for a in analyses:
            text = a.get('analysis', '')[:400]
            for line in text.split('\n')[:6]:
                print(f'  {line}')
        if len(analyses[0].get('analysis','')) > 400:
            print('  ...')
    else:
        print('  (alerta filtrado — nenhuma análise gerada)')
except Exception as e:
    pass
" 2>/dev/null || true)
            echo -e "${analysis}"
        fi
    else
        log_error "HTTP ${http_code} — erro no webhook"
        echo "${body}"
        return 1
    fi
}

# Verifica se o agente está respondendo antes de iniciar
check_agent_running() {
    if ! curl -sf "${WEBHOOK_URL%/webhook}/health" --max-time 3 > /dev/null 2>&1; then
        log_error "Agente não está respondendo em ${WEBHOOK_URL%/webhook}"
        echo ""
        echo "  Inicie o agente em outro terminal:"
        echo -e "  ${BOLD}make run${RESET}"
        echo ""
        exit 1
    fi
    log_ok "Agente respondendo em ${WEBHOOK_URL%/webhook}"
}

list_scenarios() {
    echo ""
    echo -e "${BOLD}Cenários disponíveis:${RESET}"
    echo ""
    echo "  zeebe        ZeebeMemoryPredictedHigh  (warning)  — heap JVM crescendo"
    echo "  namespace    CamundaNamespaceMemoryPressure (warning) — namespace > 6GB"
    echo "  backpressure ZeebeBackpressureGrowing  (critical) — gateway saturado"
    echo "  resolved     ZeebeMemoryPredictedHigh  (resolved) — alerta encerrado"
    echo ""
    echo "  all          Todos os cenários acima em sequência (padrão)"
    echo ""
}

# ── Parsing de argumentos ─────────────────────────────────────────────────────

SCENARIO="all"
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --scenario)
            SCENARIO="$2"
            shift 2
            ;;
        --list)
            list_scenarios
            exit 0
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --webhook-url)
            WEBHOOK_URL="$2"
            shift 2
            ;;
        --delay)
            DELAY_BETWEEN="$2"
            shift 2
            ;;
        -h|--help)
            echo "Uso: $0 [--scenario <nome>] [--dry-run] [--list] [--delay <s>] [--webhook-url <url>]"
            list_scenarios
            exit 0
            ;;
        *)
            log_error "Argumento desconhecido: $1"
            exit 1
            ;;
    esac
done

# ── Execução principal ────────────────────────────────────────────────────────

log_banner "camunda-aiops — Demo Mode"
echo -e "  Webhook: ${WEBHOOK_URL}"
echo -e "  Cenário: ${SCENARIO}"
[[ "${DRY_RUN}" == "true" ]] && echo -e "  ${YELLOW}Modo: dry-run (nenhum payload será enviado)${RESET}"

if [[ "${DRY_RUN}" != "true" ]]; then
    echo ""
    check_agent_running
fi

case "${SCENARIO}" in
    zeebe)
        send_scenario "ZeebeMemoryPredictedHigh" "zeebe-memory-alert.json" "warning"
        ;;
    namespace)
        send_scenario "CamundaNamespaceMemoryPressure" "namespace-memory-alert.json" "warning"
        ;;
    backpressure)
        send_scenario "ZeebeBackpressureGrowing" "zeebe-backpressure-alert.json" "critical"
        ;;
    resolved)
        send_scenario "ZeebeMemoryPredictedHigh (resolved)" "zeebe-resolved.json" "resolved"
        ;;
    all)
        send_scenario "ZeebeMemoryPredictedHigh" "zeebe-memory-alert.json" "warning"
        sleep "${DELAY_BETWEEN}"

        send_scenario "CamundaNamespaceMemoryPressure" "namespace-memory-alert.json" "warning"
        sleep "${DELAY_BETWEEN}"

        send_scenario "ZeebeBackpressureGrowing" "zeebe-backpressure-alert.json" "critical"
        sleep "${DELAY_BETWEEN}"

        send_scenario "ZeebeMemoryPredictedHigh (resolved)" "zeebe-resolved.json" "resolved"
        ;;
    *)
        log_error "Cenário desconhecido: '${SCENARIO}'. Use --list para ver os disponíveis."
        exit 1
        ;;
esac

echo ""
log_banner "Demo concluída"
echo -e "  ${GREEN}Todos os cenários foram processados.${RESET}"
echo -e "  Verifique o Microsoft Teams para os cards gerados."
echo ""
