#!/usr/bin/env bash
# demo.sh — ciclo de demo do agente AIOps para apresentação ao time
#
# Totalmente autossuficiente: verifica pré-requisitos, inicia Ollama e o agente
# automaticamente se necessário, executa os cenários e encerra tudo ao final.
# Não requer o cluster Kind — apenas Ollama instalado e agent/.env configurado.
#
# Uso:
#   ./scripts/demo.sh                      # ciclo completo (4 cenários)
#   ./scripts/demo.sh --scenario zeebe     # apenas ZeebeMemoryPredictedHigh
#   ./scripts/demo.sh --scenario backpressure  # critical — maior impacto
#   ./scripts/demo.sh --list               # lista os cenários disponíveis
#   ./scripts/demo.sh --dry-run            # mostra o que seria feito sem executar

set -uo pipefail

# ── Diretórios ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FIXTURES_DIR="${PROJECT_DIR}/tests/fixtures"
LOG_DIR="/tmp/camunda-aiops-demo-$$"
AGENT_LOG="${LOG_DIR}/agent.log"
mkdir -p "$LOG_DIR"

# ── Constantes configuráveis via env ─────────────────────────────────────────

WEBHOOK_URL="${WEBHOOK_URL:-http://localhost:5001/webhook}"
AGENT_PORT="5001"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
DELAY_BETWEEN="${DELAY_BETWEEN:-3}"  # segundos entre cenários

# ── Cores ─────────────────────────────────────────────────────────────────────

RED='\033[0;31m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
GREEN='\033[0;32m'; BOLD='\033[1m'; RESET='\033[0m'

# ── Estado interno ────────────────────────────────────────────────────────────

AGENT_PID=""          # PID do agente iniciado por este script (vazio = já estava rodando)
OLLAMA_PID=""         # PID do ollama serve iniciado por este script
declare -a BG_PIDS=()

# ── Helpers de log ────────────────────────────────────────────────────────────

log_banner() {
    echo ""
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
    echo -e "${BOLD}${CYAN}  $1${RESET}"
    echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════${RESET}"
}
log_step()  { echo -e "\n${BOLD}${CYAN}━━━ $1 ${RESET}"; }
log_ok()    { echo -e "  ${GREEN}✔${RESET} $1"; }
log_info()  { echo -e "  ${CYAN}→${RESET} $1"; }
log_warn()  { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
log_error() { echo -e "  ${RED}✖${RESET} $1" >&2; }

# ── Cleanup — encerra apenas o que este script iniciou ────────────────────────

cleanup() {
    echo ""
    echo -e "${YELLOW}━━━ Encerrando demo ━━━${RESET}"
    local pid
    for pid in "${BG_PIDS[@]}"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    done
    echo -e "  ${GREEN}✔${RESET} Recursos encerrados. Logs em: ${LOG_DIR}"
}
trap cleanup EXIT INT TERM

# ── Verificações de pré-requisito ─────────────────────────────────────────────

check_venv() {
    if [ ! -f "${PROJECT_DIR}/.venv/bin/uvicorn" ]; then
        log_error "Virtualenv não encontrado."
        echo ""
        echo "  Execute primeiro:"
        echo -e "  ${BOLD}python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'${RESET}"
        echo ""
        exit 1
    fi
}

check_env_file() {
    if [ ! -f "${PROJECT_DIR}/agent/.env" ]; then
        log_warn "agent/.env não encontrado — cards Teams podem não ser enviados."
        log_info "Copie o template: cp .env.example agent/.env"
        log_info "Defina ao menos TEAMS_WEBHOOK_URL para receber os cards."
    else
        # Avisa se TEAMS_WEBHOOK_URL está vazia mas não aborta — demo do agente ainda funciona
        local teams_url
        teams_url=$(grep -E "^TEAMS_WEBHOOK_URL=" "${PROJECT_DIR}/agent/.env" 2>/dev/null \
            | cut -d= -f2 | tr -d '"' || true)
        if [ -z "$teams_url" ]; then
            log_warn "TEAMS_WEBHOOK_URL não definida em agent/.env — notificação Teams será silenciada."
        else
            log_ok "agent/.env carregado com TEAMS_WEBHOOK_URL configurada."
        fi
    fi
}

# ── Gerenciamento do Ollama ───────────────────────────────────────────────────

ensure_ollama() {
    if curl -sf "${OLLAMA_URL}/api/tags" -o /dev/null 2>/dev/null; then
        log_ok "Ollama respondendo em ${OLLAMA_URL}."
    else
        log_warn "Ollama não está respondendo. Tentando iniciar 'ollama serve'..."

        if ! command -v ollama &>/dev/null; then
            log_error "Comando 'ollama' não encontrado no PATH."
            echo ""
            echo "  Instale o Ollama em: https://ollama.com/download"
            echo "  Em seguida: ollama pull qwen2.5:7b"
            echo ""
            exit 1
        fi

        ollama serve >> "${LOG_DIR}/ollama.log" 2>&1 &
        OLLAMA_PID=$!
        BG_PIDS+=("$OLLAMA_PID")

        log_info "Aguardando Ollama iniciar (até 20s)..."
        local i
        for i in $(seq 1 20); do
            if curl -sf "${OLLAMA_URL}/api/tags" -o /dev/null 2>/dev/null; then
                log_ok "Ollama iniciado (PID ${OLLAMA_PID})."
                break
            fi
            if [ "$i" -eq 20 ]; then
                log_error "Ollama não respondeu após 20s."
                tail -5 "${LOG_DIR}/ollama.log" 2>/dev/null | sed 's/^/    /'
                exit 1
            fi
            sleep 1
        done
    fi

    # Verifica se o modelo necessário está disponível
    local model
    model=$(grep -E "^OLLAMA_MODEL=" "${PROJECT_DIR}/agent/.env" 2>/dev/null \
        | cut -d= -f2 | tr -d '"' || echo "qwen2.5:7b")

    if ! curl -sf "${OLLAMA_URL}/api/tags" 2>/dev/null | grep -q "\"${model}\""; then
        log_warn "Modelo '${model}' não encontrado localmente. Iniciando download..."
        log_info "Isso pode levar alguns minutos na primeira vez."
        if ! ollama pull "$model"; then
            log_error "Falha ao baixar o modelo '${model}'."
            exit 1
        fi
        log_ok "Modelo '${model}' pronto."
    else
        log_ok "Modelo '${model}' disponível."
    fi
}

# ── Gerenciamento do agente ───────────────────────────────────────────────────

ensure_agent() {
    # Se já está respondendo (iniciado externamente), só usa — não toca nele no cleanup
    if curl -sf "http://localhost:${AGENT_PORT}/health" -o /dev/null 2>/dev/null; then
        log_ok "Agente já está rodando na porta ${AGENT_PORT} — reutilizando."
        return
    fi

    # Verifica se a porta está ocupada por outro processo que não responde ao /health
    if lsof -ti:"${AGENT_PORT}" &>/dev/null; then
        log_warn "Porta ${AGENT_PORT} ocupada por processo não-agente. Liberando..."
        lsof -ti:"${AGENT_PORT}" | xargs kill -9 2>/dev/null || true
        sleep 1
    fi

    log_info "Iniciando agente (log: ${AGENT_LOG})..."
    (cd "${PROJECT_DIR}/agent" && \
        ../.venv/bin/uvicorn webhook_receiver:app \
            --host 0.0.0.0 --port "${AGENT_PORT}" \
            --log-level info \
        >> "${AGENT_LOG}" 2>&1) &
    AGENT_PID=$!
    BG_PIDS+=("$AGENT_PID")

    log_info "Aguardando agente subir (até 20s)..."
    local i
    for i in $(seq 1 20); do
        if curl -sf "http://localhost:${AGENT_PORT}/health" -o /dev/null 2>/dev/null; then
            local health
            health=$(curl -s "http://localhost:${AGENT_PORT}/health" 2>/dev/null || echo "{}")
            log_ok "Agente respondendo: ${health}"
            return
        fi
        # Verifica se o processo ainda está vivo
        if ! kill -0 "$AGENT_PID" 2>/dev/null; then
            log_error "Processo do agente morreu prematuramente. Log:"
            tail -15 "${AGENT_LOG}" 2>/dev/null | sed 's/^/    /'
            echo ""
            log_info "Diagnóstico provável:"
            log_info "  • Erro de import: cd agent && ../.venv/bin/python -c 'import webhook_receiver'"
            log_info "  • Dependência ausente: .venv/bin/pip install -e '.[dev]'"
            exit 1
        fi
        sleep 1
    done

    log_error "Agente não respondeu em 20s. Log:"
    tail -15 "${AGENT_LOG}" 2>/dev/null | sed 's/^/    /'
    exit 1
}

# ── Envio de cenário ──────────────────────────────────────────────────────────

send_scenario() {
    local label="$1"
    local fixture_file="$2"
    local severity="$3"

    echo ""
    log_step "Cenário: ${label} [${severity}]"
    log_info "Fixture: ${fixture_file}"

    if [[ "${DRY_RUN}" == "true" ]]; then
        log_warn "dry-run: payload não enviado"
        return
    fi

    # Injeta o timestamp atual no payload — os fixtures têm datas estáticas
    local payload
    payload=$(python3 -c "
import json, sys, datetime
data = json.load(open('${FIXTURES_DIR}/${fixture_file}'))
now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
data['startsAt'] = now
for alert in data.get('alerts', []):
    alert['startsAt'] = now
print(json.dumps(data))
")

    local response http_code body
    response=$(curl -s -w "\n__HTTP_STATUS__%{http_code}" \
        -X POST "${WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        --max-time 120)  # 120s: LLM local pode levar 10–30s

    http_code=$(echo "${response}" | grep '__HTTP_STATUS__' | sed 's/__HTTP_STATUS__//')
    body=$(echo "${response}" | grep -v '__HTTP_STATUS__')

    if [[ "${http_code}" == "200" ]]; then
        log_ok "HTTP ${http_code} — webhook processado"
        # Exibe resumo da análise no terminal
        echo "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    analyses = data.get('analyses', [])
    if analyses:
        print('\n  Análise do agente:')
        text = analyses[0].get('analysis', '')
        for line in text.split('\n')[:6]:
            print(f'  {line}')
        if len(text) > 400:
            print('  ...')
    else:
        print('  (alerta filtrado — nenhuma análise gerada)')
except Exception:
    pass
" 2>/dev/null || true
    else
        log_error "HTTP ${http_code} — erro no webhook"
        echo "${body}"
        exit 1
    fi
}

# ── Listagem de cenários ──────────────────────────────────────────────────────

list_scenarios() {
    echo ""
    echo -e "${BOLD}Cenários disponíveis:${RESET}"
    echo ""
    echo "  zeebe        ZeebeMemoryPredictedHigh        (warning)  — heap JVM crescendo"
    echo "  namespace    CamundaNamespaceMemoryPressure  (warning)  — namespace > 6 GB"
    echo "  backpressure ZeebeBackpressureGrowing        (critical) — gateway saturado"
    echo "  resolved     ZeebeMemoryPredictedHigh        (resolved) — alerta encerrado"
    echo ""
    echo "  all          Todos os cenários acima em sequência (padrão)"
    echo ""
}

# ── Parsing de argumentos ─────────────────────────────────────────────────────

SCENARIO="all"
DRY_RUN="false"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --scenario)     SCENARIO="$2";     shift 2 ;;
        --dry-run)      DRY_RUN="true";    shift   ;;
        --list)         list_scenarios;    exit 0  ;;
        --delay)        DELAY_BETWEEN="$2"; shift 2 ;;
        --webhook-url)  WEBHOOK_URL="$2";  shift 2 ;;
        -h|--help)
            echo "Uso: $0 [--scenario <nome>] [--dry-run] [--list] [--delay <s>]"
            list_scenarios
            exit 0
            ;;
        *)
            log_error "Argumento desconhecido: $1"
            echo "  Use --help para ver as opções disponíveis."
            exit 1
            ;;
    esac
done

# ── Execução principal ────────────────────────────────────────────────────────

log_banner "camunda-aiops — Demo Mode"
echo -e "  Webhook:  ${WEBHOOK_URL}"
echo -e "  Cenário:  ${SCENARIO}"
[[ "${DRY_RUN}" == "true" ]] && echo -e "  ${YELLOW}Modo:     dry-run (nenhum payload será enviado)${RESET}"

if [[ "${DRY_RUN}" != "true" ]]; then
    log_step "Verificando pré-requisitos"
    check_venv
    check_env_file

    log_step "Ollama (LLM local)"
    ensure_ollama

    log_step "Agente AIOps (porta ${AGENT_PORT})"
    ensure_agent
fi

log_step "Executando cenários"

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
        log_error "Cenário desconhecido: '${SCENARIO}'"
        echo "  Use --list para ver os cenários disponíveis."
        exit 1
        ;;
esac

echo ""
log_banner "Demo concluída"
echo -e "  ${GREEN}Todos os cenários foram processados.${RESET}"
echo -e "  Verifique o Microsoft Teams para os cards gerados."
echo ""
