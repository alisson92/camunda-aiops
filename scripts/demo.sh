#!/usr/bin/env bash
# demo.sh — ciclo de demo do agente AIOps para apresentação ao time
#
# Totalmente autossuficiente: verifica pré-requisitos, inicia Ollama e o agente
# automaticamente se necessário, gera fixtures faltantes a partir de alerting/*.yaml,
# executa os cenários e encerra tudo ao final.
# Não requer o cluster Kind — apenas Ollama instalado e agent/.env configurado.
#
# Uso:
#   ./scripts/demo.sh                      # itera todos os fixtures *-alert.json
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

AGENT_PORT="5001"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

# Auto-detecta se o agente está deployado no cluster Kind.
# Se sim, usa o NodePort (IP do nó:30501) em vez de localhost.
# Pode ser sobrescrito: WEBHOOK_URL=http://... ./scripts/demo.sh
_detect_webhook_url() {
    if kubectl get pod -n camunda -l app=camunda-aiops-agent --no-headers 2>/dev/null \
       | grep -q "Running"; then
        local node_ip
        node_ip=$(kubectl get nodes \
          -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' \
          2>/dev/null | awk '{print $1}')
        if [ -n "$node_ip" ]; then
            echo "http://${node_ip}:30501/webhook"
            return
        fi
    fi
    echo "http://localhost:${AGENT_PORT}/webhook"
}
WEBHOOK_URL="${WEBHOOK_URL:-$(_detect_webhook_url)}"
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
    # Se o agente estiver deployado no cluster Kind, reutiliza sem iniciar processo local.
    if kubectl get pod -n camunda -l app=camunda-aiops-agent --no-headers 2>/dev/null \
       | grep -q "Running"; then
        local health
        health=$(curl -s "${WEBHOOK_URL%/webhook}/health" 2>/dev/null || echo "{}")
        log_ok "Agente rodando no cluster Kind — ${WEBHOOK_URL}"
        log_ok "Health: ${health}"
        return
    fi

    # Modo local: demo sempre reinicia o agente para garantir código e config atuais.
    if curl -sf "http://localhost:${AGENT_PORT}/health" -o /dev/null 2>/dev/null; then
        log_warn "Agente rodando na porta ${AGENT_PORT} — reiniciando para carregar código e config atuais."
        lsof -ti:"${AGENT_PORT}" | xargs kill -9 2>/dev/null || true
        sleep 1
    fi

    # Verifica se a porta está ocupada por outro processo que não responde ao /health
    if lsof -ti:"${AGENT_PORT}" &>/dev/null; then
        log_warn "Porta ${AGENT_PORT} ainda ocupada. Liberando..."
        lsof -ti:"${AGENT_PORT}" | xargs kill -9 2>/dev/null || true
        sleep 1
    fi

    log_info "Iniciando agente localmente (log: ${AGENT_LOG})..."
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

# ── Port-forwards opcionais (só quando Kind está ativo) ──────────────────────

ensure_port_forwards() {
    local context
    context=$(kubectl config current-context 2>/dev/null || echo "")

    if [[ "$context" != kind-* ]]; then
        log_warn "Cluster Kind não detectado — links de Dashboard e Silence não funcionarão."
        log_info "Para ativá-los, inicie o Kind e execute: make port-forward"
        return
    fi

    log_step "Kind detectado (${context}) — iniciando port-forwards"

    # Grafana
    kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana \
        3000:80 >> "${LOG_DIR}/pf-grafana.log" 2>&1 &
    BG_PIDS+=("$!")
    log_ok "Grafana:      http://localhost:3000"

    # Alertmanager
    kubectl port-forward -n monitoring svc/kube-prometheus-stack-alertmanager \
        9093:9093 >> "${LOG_DIR}/pf-alertmanager.log" 2>&1 &
    BG_PIDS+=("$!")
    log_ok "Alertmanager: http://localhost:9093"

    # Aguarda os tunnels estabelecerem antes de enviar os cenários
    sleep 2
}

ensure_dashboards() {
    local context
    context=$(kubectl config current-context 2>/dev/null || echo "")

    if [[ "$context" != kind-* ]]; then
        log_warn "Kind não detectado — import de dashboards ignorado."
        return
    fi

    # Aguarda o Grafana estar responsivo antes de importar
    local grafana_url="http://localhost:3000"
    local retries=0
    until curl -s -o /dev/null -w "%{http_code}" "${grafana_url}/api/health" | grep -q "200"; do
        retries=$((retries + 1))
        if [[ $retries -ge 10 ]]; then
            log_warn "Grafana não respondeu após 10s — import ignorado."
            return
        fi
        sleep 1
    done

    # Recupera a senha do Grafana diretamente do Secret do Kubernetes
    # Evita exigir GRAFANA_PASS no .env para a demo funcionar sem configuração extra
    local grafana_pass
    grafana_pass=$(kubectl get secret -n monitoring kube-prometheus-stack-grafana \
        -o jsonpath='{.data.admin-password}' 2>/dev/null | base64 -d 2>/dev/null || echo "")

    if [[ -z "$grafana_pass" ]]; then
        log_warn "Não foi possível recuperar a senha do Grafana — import ignorado."
        log_info "Para importar manualmente: GRAFANA_PASS=<senha> ./scripts/import-dashboard.sh"
        return
    fi

    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Delega ao import-dashboard.sh que percorre dashboards/*.json automaticamente
    if GRAFANA_PASS="$grafana_pass" \
        bash "${script_dir}/import-dashboard.sh" >> "${LOG_DIR}/dashboards.log" 2>&1; then
        log_ok "Dashboards importados — ${grafana_url}"
    else
        log_warn "Import de dashboards falhou — veja ${LOG_DIR}/dashboards.log"
    fi
}

# ── Geração de fixtures a partir de alerting/*.yaml ──────────────────────────

ensure_fixtures() {
    local python="${PROJECT_DIR}/.venv/bin/python3"

    if [[ ! -x "$python" ]]; then
        log_warn "venv Python não encontrado — geração de fixtures ignorada."
        return
    fi

    local output new_count
    if output=$("$python" "${SCRIPT_DIR}/generate-fixtures.py" 2>&1); then
        new_count=$(echo "$output" | grep -c "✔ gerado:" || true)
        if [[ "$new_count" -gt 0 ]]; then
            log_ok "Fixtures gerados: ${new_count} novo(s)"
            echo "$output" | grep "✔ gerado:" | while IFS= read -r line; do log_info "$line"; done
        else
            log_ok "Fixtures já sincronizados com alerting/*.yaml"
        fi
    else
        log_warn "Geração de fixtures falhou — usando apenas os existentes."
        echo "$output" | while IFS= read -r line; do log_warn "$line"; done
    fi
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

    # Injeta timestamps atuais no payload — os fixtures têm datas estáticas
    # Para firing:  startsAt = agora,        endsAt = sentinel (alerta ativo)
    # Para resolved: startsAt = agora (disparo), endsAt = agora + 45min (resolução)
    # O card calculará automaticamente a duração a partir de endsAt - startsAt
    local payload
    payload=$(python3 -c "
import json, datetime
data = json.load(open('${FIXTURES_DIR}/${fixture_file}'))
now = datetime.datetime.now(datetime.timezone.utc)
fmt = '%Y-%m-%dT%H:%M:%SZ'
is_resolved = data.get('status') == 'resolved'
started = now.strftime(fmt)
ended   = (now + datetime.timedelta(minutes=45)).strftime(fmt) if is_resolved else '0001-01-01T00:00:00Z'
data['startsAt'] = started
data['endsAt']   = ended
for alert in data.get('alerts', []):
    alert['startsAt'] = started
    alert['endsAt']   = ended
print(json.dumps(data))
")

    local response http_code body
    # Com webhook assíncrono, o agente retorna 202 imediatamente (análise ocorre em background).
    # --max-time reduzido para 15s — a resposta chega em ~1s, não mais 30–90s do LLM.
    response=$(curl -s -w "\n__HTTP_STATUS__%{http_code}" \
        -X POST "${WEBHOOK_URL}" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        --max-time 15)

    http_code=$(echo "${response}" | grep '__HTTP_STATUS__' | sed 's/__HTTP_STATUS__//')
    body=$(echo "${response}" | grep -v '__HTTP_STATUS__')

    # Aceita qualquer 2xx (200 = agente antigo síncrono, 202 = agente assíncrono atual)
    if [[ "${http_code}" =~ ^2 ]]; then
        # Extrai campos individualmente para evitar mistura de variáveis bash e Python f-strings
        local queued analyses_count msg
        queued=$(echo "${body}" | python3 -c \
            "import json,sys; d=json.load(sys.stdin); print(d.get('queued',-1))" 2>/dev/null || echo "-1")
        msg=$(echo "${body}" | python3 -c \
            "import json,sys; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null || echo "")
        analyses_count=$(echo "${body}" | python3 -c \
            "import json,sys; d=json.load(sys.stdin); print(len(d.get('analyses',[])))" 2>/dev/null || echo "0")

        if [[ "${queued}" -gt 0 ]]; then
            # Agente assíncrono (202): alerta aceito e enfileirado
            log_ok "HTTP ${http_code} — ${queued} alerta(s) enfileirado(s) para análise"
            log_info "Processando em background → aguarde o card no Microsoft Teams"
        elif [[ "${queued}" -eq 0 ]]; then
            # Alerta filtrado (sem label agentia=true) ou deduplicado
            log_warn "HTTP ${http_code} — nenhum alerta processado (filtrado ou deduplicado)"
            [[ -n "${msg}" ]] && log_info "${msg}"
            log_info "Verifique se o alerta tem a label agentia=true na PrometheusRule"
        elif [[ "${analyses_count}" -gt 0 ]]; then
            # Backward compat: agente antigo síncrono (campo 'analyses')
            log_ok "HTTP ${http_code} — webhook processado"
            echo "${body}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
analyses = data.get('analyses', [])
if analyses:
    print()
    print('  Análise do agente:')
    text = analyses[0].get('analysis', '')
    for line in text.split('\n')[:6]:
        print(f'  {line}')
    if len(text.split('\n')) > 6:
        print('  ...')
" 2>/dev/null || true
        else
            log_warn "HTTP ${http_code} — resposta sem campo 'queued' nem 'analyses'"
            log_info "Corpo: $(echo "${body}" | cut -c1-150)"
        fi
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
    echo "  Individuais (curados):"
    echo "    zeebe        ZeebeMemoryPredictedHigh       (warning)  — heap JVM crescendo"
    echo "    namespace    CamundaNamespaceMemoryPressure (warning)  — namespace > 6 GB"
    echo "    backpressure ZeebeBackpressureGrowing       (critical) — gateway saturado"
    echo "    resolved     ZeebeMemoryPredictedHigh       (resolved) — alerta encerrado"
    echo ""
    echo "  all — itera todos os fixtures tests/fixtures/*-alert.json (padrão)"
    if compgen -G "${FIXTURES_DIR}/*-alert.json" > /dev/null 2>&1; then
        local count
        count=$(find "${FIXTURES_DIR}" -name "*-alert.json" | wc -l | tr -d ' ')
        echo "        (${count} fixture(s) disponíveis)"
    fi
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

    log_step "Port-forwards (Grafana + Alertmanager)"
    ensure_port_forwards

    log_step "Dashboards Grafana"
    ensure_dashboards

    log_step "Fixtures de alertas"
    ensure_fixtures
fi

log_step "Executando cenários"

case "${SCENARIO}" in
    zeebe)
        send_scenario "ZeebeMemoryPredictedHigh" "zeebe-memory-predicted-high-alert.json" "warning"
        ;;
    namespace)
        send_scenario "CamundaNamespaceMemoryPressure" "camunda-namespace-memory-pressure-alert.json" "warning"
        ;;
    backpressure)
        send_scenario "ZeebeBackpressureGrowing" "zeebe-backpressure-growing-alert.json" "critical"
        ;;
    resolved)
        send_scenario "ZeebeMemoryPredictedHigh (resolved)" "zeebe-memory-predicted-high-resolved.json" "resolved"
        ;;
    all)
        # Itera dinamicamente todos os fixtures *-alert.json em ordem alfabética.
        # Novos alertas adicionados via generate-fixtures.py são incluídos automaticamente.
        while IFS= read -r fixture_path; do
            fixture_file=$(basename "$fixture_path")
            alertname=$(python3 -c "
import json
d = json.load(open('${fixture_path}'))
print(d.get('alerts', [{}])[0].get('labels', {}).get('alertname', 'Unknown'))
" 2>/dev/null || echo "Unknown")
            severity=$(python3 -c "
import json
d = json.load(open('${fixture_path}'))
print(d.get('alerts', [{}])[0].get('labels', {}).get('severity', 'unknown'))
" 2>/dev/null || echo "unknown")
            send_scenario "${alertname}" "${fixture_file}" "${severity}"
            sleep "${DELAY_BETWEEN}"
        done < <(find "${FIXTURES_DIR}" -name "*-alert.json" | sort)
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

if [[ "${DRY_RUN}" != "true" ]]; then
    echo -e "  ${YELLOW}Agente e port-forwards ainda estão ativos.${RESET}"
    echo -e "  Interaja com os cards no Teams e pressione ${BOLD}ENTER${RESET} quando terminar."
    echo ""
    read -r || true
fi
