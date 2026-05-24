#!/usr/bin/env bash
# =============================================================================
# run-cycle-test.sh
#
# Ciclo completo de teste do agente AIOps com auto-recuperação de erros:
#   0. Valida pré-requisitos — auto-alterna contexto Kind se necessário
#   1. Aplica PrometheusRule no cluster
#   2. Inicia port-forwards (Prometheus 9090, Alertmanager 9093, Grafana 3000)
#   3. Verifica Ollama — inicia automaticamente se offline
#   4. Inicia o agente (webhook receiver, porta 5001)
#   5. Fast check — envia fixture real para confirmar agente → Teams
#   6. Load-generator (opcional) para pressão sustentada
#   7. Monitoramento em tempo real (tail de logs)
#
# Uso:
#   ./scripts/run-cycle-test.sh [--context <kubectl-context>] [--skip-load]
#                               [--intensity low|medium|high] [--duration <min>]
#
# Flags:
#   --context      Contexto kubectl a usar (obrigatório se houver >1 cluster kind-*)
#   --skip-load    Pula o load-generator (só fast check + observação)
#   --intensity    Intensidade da carga (default: medium)
#   --duration     Duração do load em minutos (default: 20)
# =============================================================================

# set -e propositalmente ausente: cada passo tem tratativa própria.
# set -u garante que variáveis não declaradas causem erro explícito.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

SKIP_LOAD=false
INTENSITY="medium"
DURATION_MIN=20
TARGET_CONTEXT=""

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

LOG_DIR="/tmp/camunda-aiops-cycle-$$"
AGENT_LOG="$LOG_DIR/agent.log"
PF_LOG="$LOG_DIR/port-forwards.log"
mkdir -p "$LOG_DIR"

declare -a BG_PIDS=()

# Contador de avisos — resumido no final
WARNINGS=0
warn() { log_warn "$1"; WARNINGS=$((WARNINGS + 1)); }

# =============================================================================
# Parsing de argumentos
# =============================================================================
while [[ $# -gt 0 ]]; do
  case $1 in
    --context)    TARGET_CONTEXT="$2"; shift 2 ;;
    --skip-load)  SKIP_LOAD=true;      shift   ;;
    --intensity)  INTENSITY="$2";      shift 2 ;;
    --duration)   DURATION_MIN="$2";   shift 2 ;;
    *) echo -e "${RED}Flag desconhecida: $1${NC}"; exit 1 ;;
  esac
done

# =============================================================================
# Helpers de log
# =============================================================================
log_step() { echo -e "\n${BOLD}${CYAN}━━━ $1 ${NC}"; }
log_ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
log_info() { echo -e "  ${CYAN}→${NC} $1"; }
log_warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; }
log_err()  { echo -e "  ${RED}✗${NC} $1"; }

# =============================================================================
# free_port PORT LABEL
# Verifica se a porta está ocupada e mata o processo responsável.
# Retorna 0 se a porta ficou livre, 1 se não conseguiu liberar.
# =============================================================================
free_port() {
  local port="$1"
  local label="${2:-porta $1}"
  if lsof -ti:"$port" &>/dev/null; then
    local pids
    pids=$(lsof -ti:"$port")
    log_warn "Porta $port ocupada ($label). PIDs: $pids — liberando..."
    lsof -ti:"$port" | xargs kill -9 2>/dev/null || true
    # Aguarda a porta ser liberada (até 5s)
    local i
    for i in $(seq 1 5); do
      if ! lsof -ti:"$port" &>/dev/null; then
        log_ok "Porta $port liberada."
        return 0
      fi
      sleep 1
    done
    log_err "Não foi possível liberar a porta $port após 5s."
    return 1
  fi
  return 0
}

# =============================================================================
# wait_for_port PORT LABEL [MAX_SECONDS]
# Aguarda o serviço na porta responder a uma requisição HTTP.
# Retorna 0 se respondeu, 1 se esgotou o tempo.
# =============================================================================
wait_for_port() {
  local port="$1"
  local label="$2"
  local max="${3:-20}"
  local i
  for i in $(seq 1 "$max"); do
    if curl -sf "http://localhost:${port}/-/ready"           -o /dev/null 2>/dev/null \
    || curl -sf "http://localhost:${port}/api/v1/status/runtimeinfo" -o /dev/null 2>/dev/null \
    || curl -sf "http://localhost:${port}/api/v2/status"     -o /dev/null 2>/dev/null \
    || curl -sf "http://localhost:${port}/api/health"        -o /dev/null 2>/dev/null \
    || curl -sf "http://localhost:${port}"                   -o /dev/null 2>/dev/null; then
      log_ok "$label acessível em localhost:${port}"
      return 0
    fi
    sleep 1
  done
  return 1
}

# =============================================================================
# start_port_forward NS SVC LOCAL_PORT REMOTE_PORT LABEL
# Inicia port-forward com até 3 tentativas. Em cada falha verifica se o
# serviço existe no cluster antes de tentar novamente.
# =============================================================================
start_port_forward() {
  local ns="$1" svc="$2" local_port="$3" remote_port="$4" label="$5"
  local attempt

  free_port "$local_port" "$label" || true

  for attempt in 1 2 3; do
    log_info "[$attempt/3] Port-forward: $label → localhost:${local_port}"

    # Verifica se o serviço existe antes de tentar
    if ! kubectl get svc "$svc" -n "$ns" &>/dev/null; then
      log_err "Serviço $svc não encontrado no namespace $ns."
      log_info "Verifique: kubectl get svc -n $ns"
      return 1
    fi

    kubectl port-forward -n "$ns" "svc/${svc}" "${local_port}:${remote_port}" \
      >> "$PF_LOG" 2>&1 &
    local pf_pid=$!
    BG_PIDS+=($pf_pid)

    if wait_for_port "$local_port" "$label" 10; then
      return 0
    fi

    # O processo já pode ter morrido — remove da lista de PIDs gerenciados
    kill "$pf_pid" 2>/dev/null || true
    BG_PIDS=("${BG_PIDS[@]/$pf_pid/}")

    if [ "$attempt" -lt 3 ]; then
      log_warn "$label não respondeu na tentativa $attempt. Retentando em 3s..."
      sleep 3
    fi
  done

  log_err "$label falhou após 3 tentativas. Últimas linhas do log:"
  tail -5 "$PF_LOG" 2>/dev/null | sed 's/^/    /'
  warn "$label indisponível — algumas verificações podem falhar."
  return 1
}

# =============================================================================
# Cleanup — encerra todos os processos em background ao sair
# =============================================================================
cleanup() {
  echo -e "\n${YELLOW}━━━ Encerrando ciclo de teste ━━━${NC}"
  local pid
  for pid in "${BG_PIDS[@]}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  pkill -f "kubectl port-forward.*kube-prometheus" 2>/dev/null || true
  kubectl delete namespace load-test --ignore-not-found=true 2>/dev/null || true
  echo -e "  ${GREEN}✓${NC} Cleanup concluído. Logs salvos em: ${LOG_DIR}"
}
trap cleanup EXIT INT TERM

# =============================================================================
# PASSO 0 — Validações e auto-correção de contexto
# =============================================================================
log_step "Passo 0 — Validações"

KIND_CONTEXTS=$(kubectl config get-contexts -o name 2>/dev/null | grep "^kind-" || true)
CURRENT_CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")

if [ -n "$TARGET_CONTEXT" ]; then
  # --context foi passado explicitamente: valida e usa
  if ! echo "$TARGET_CONTEXT" | grep -q "^kind-"; then
    log_warn "Contexto '${TARGET_CONTEXT}' não tem prefixo 'kind-'. Certifique-se de que é um cluster local."
  fi
  if ! kubectl config get-contexts "$TARGET_CONTEXT" &>/dev/null; then
    log_err "Contexto '${TARGET_CONTEXT}' não existe no kubeconfig."
    log_info "Contextos disponíveis:"
    kubectl config get-contexts -o name 2>/dev/null | sed 's/^/    /' || true
    exit 1
  fi
  if [ "$CURRENT_CONTEXT" != "$TARGET_CONTEXT" ]; then
    log_info "Alternando para contexto especificado: ${TARGET_CONTEXT}"
    kubectl config use-context "$TARGET_CONTEXT" &>/dev/null
  fi
  CURRENT_CONTEXT="$TARGET_CONTEXT"
  log_ok "Contexto: ${CURRENT_CONTEXT}"

elif [[ "$CURRENT_CONTEXT" == kind-* ]]; then
  # Contexto atual já é Kind — usa diretamente
  log_ok "Contexto Kind ativo: ${CURRENT_CONTEXT}"

else
  # Contexto atual não é Kind e --context não foi passado
  log_warn "Contexto atual '${CURRENT_CONTEXT}' não é Kind."

  if [ -z "$KIND_CONTEXTS" ]; then
    log_err "Nenhum contexto Kind encontrado no kubeconfig."
    log_info "Crie o cluster com: kind create cluster --name camunda-platform-local"
    exit 1
  fi

  KIND_COUNT=$(echo "$KIND_CONTEXTS" | wc -l)

  if [ "$KIND_COUNT" -eq 1 ]; then
    # Só um Kind disponível — alterna automaticamente
    TARGET_CONTEXT=$(echo "$KIND_CONTEXTS" | head -1)
    log_info "Único cluster Kind encontrado. Alternando automaticamente para: ${TARGET_CONTEXT}"
    kubectl config use-context "$TARGET_CONTEXT" &>/dev/null
    CURRENT_CONTEXT="$TARGET_CONTEXT"
    log_ok "Contexto: ${CURRENT_CONTEXT}"
  else
    # Múltiplos Kind — exige escolha explícita para não errar
    log_err "Múltiplos clusters Kind encontrados. Use --context para especificar qual usar:"
    echo "$KIND_CONTEXTS" | sed 's/^/    /'
    log_info "Exemplo:"
    log_info "  ./scripts/run-cycle-test.sh --context $(echo "$KIND_CONTEXTS" | head -1)"
    exit 1
  fi
fi

# Verifica que o cluster está acessível (não só o kubeconfig)
if ! kubectl cluster-info &>/dev/null; then
  log_err "Cluster '${CURRENT_CONTEXT}' não está respondendo."
  log_info "Verifique se o Docker está rodando e o cluster Kind está ativo:"
  log_info "  docker ps | grep kind"
  log_info "  kind get clusters"
  exit 1
fi
log_ok "Cluster acessível."

# Checa namespaces essenciais
for ns in camunda monitoring; do
  if ! kubectl get namespace "$ns" &>/dev/null; then
    log_err "Namespace '$ns' não existe no cluster."
    log_info "O stack Camunda + kube-prometheus-stack deve estar instalado."
    exit 1
  fi
done
log_ok "Namespaces camunda e monitoring presentes."

# =============================================================================
# PASSO 1 — Aplicar PrometheusRule
# =============================================================================
log_step "Passo 1 — PrometheusRule"

RULE_FILE="${PROJECT_DIR}/alerting/camunda-forecasting-rules.yaml"

if [ ! -f "$RULE_FILE" ]; then
  log_err "Arquivo não encontrado: ${RULE_FILE}"
  log_info "Verifique se o repositório está completo."
  exit 1
fi

if kubectl apply -f "$RULE_FILE" 2>/tmp/rule-apply-err; then
  log_ok "PrometheusRule aplicada."
else
  log_warn "kubectl apply retornou erro:"
  cat /tmp/rule-apply-err | sed 's/^/    /'
  log_info "Verificando se a regra já existe no cluster..."
  if kubectl get prometheusrule camunda-forecasting-alerts -n monitoring &>/dev/null; then
    log_ok "PrometheusRule já existia — usando versão atual do cluster."
  else
    log_err "PrometheusRule não existe e não pôde ser aplicada. Continuando sem alertas preditivos."
    warn "PrometheusRule não aplicada — alertas do Prometheus não serão gerados organicamente."
  fi
fi

# Aguarda o Operator confirmar (até 30s, não bloqueia se demorar)
log_info "Aguardando Prometheus Operator recarregar..."
RULE_LOADED=false
for i in $(seq 1 6); do
  RULE_COUNT=$(kubectl get prometheusrule camunda-forecasting-alerts -n monitoring \
    -o jsonpath='{.spec.groups[*].rules}' 2>/dev/null | grep -o '"alert"' | wc -l || echo 0)
  if [ "$RULE_COUNT" -gt 0 ]; then
    log_ok "${RULE_COUNT} regras de alerta detectadas no cluster."
    RULE_LOADED=true
    break
  fi
  sleep 5
done
$RULE_LOADED || warn "Regras não confirmadas pelo Operator em 30s (normal em cluster sobrecarregado)."

# =============================================================================
# PASSO 2 — Port-forwards
# =============================================================================
log_step "Passo 2 — Port-forwards"

start_port_forward monitoring kube-prometheus-stack-prometheus  9090 9090 "Prometheus"  || true
start_port_forward monitoring kube-prometheus-stack-alertmanager 9093 9093 "Alertmanager" || true
start_port_forward monitoring kube-prometheus-stack-grafana      3000 80   "Grafana"      || true

# =============================================================================
# PASSO 3 — Verificar Ollama
# =============================================================================
log_step "Passo 3 — Ollama (LLM local)"

OLLAMA_URL="http://localhost:11434"

if curl -sf "${OLLAMA_URL}/api/tags" -o /dev/null 2>/dev/null; then
  log_ok "Ollama respondendo em ${OLLAMA_URL}."
else
  log_warn "Ollama não está respondendo. Tentando iniciar 'ollama serve'..."

  if ! command -v ollama &>/dev/null; then
    log_err "Comando 'ollama' não encontrado no PATH."
    log_info "Instale em: https://ollama.com/download"
    warn "Ollama indisponível — agente não conseguirá analisar alertas."
  else
    ollama serve >> "$LOG_DIR/ollama.log" 2>&1 &
    BG_PIDS+=($!)
    log_info "Aguardando Ollama iniciar (até 15s)..."

    OLLAMA_OK=false
    for i in $(seq 1 15); do
      if curl -sf "${OLLAMA_URL}/api/tags" -o /dev/null 2>/dev/null; then
        log_ok "Ollama iniciado com sucesso."
        OLLAMA_OK=true
        break
      fi
      sleep 1
    done

    if ! $OLLAMA_OK; then
      log_err "Ollama não respondeu após 15s. Log:"
      tail -5 "$LOG_DIR/ollama.log" 2>/dev/null | sed 's/^/    /'
      warn "Ollama indisponível — agente não conseguirá analisar alertas."
    fi
  fi
fi

# Verifica se o modelo configurado está disponível
MODEL=$(grep -E "^OLLAMA_MODEL=" "${PROJECT_DIR}/agent/.env" 2>/dev/null \
  | cut -d= -f2 | tr -d '"' || echo "qwen2.5:7b")

if curl -sf "${OLLAMA_URL}/api/tags" -o /tmp/ollama-tags.json 2>/dev/null; then
  if ! grep -q "\"${MODEL}\"" /tmp/ollama-tags.json 2>/dev/null; then
    log_warn "Modelo '${MODEL}' não encontrado localmente. Iniciando download..."
    ollama pull "$MODEL" 2>&1 | tail -3 | sed 's/^/    /' || \
      warn "Falha ao baixar modelo '${MODEL}'. O agente pode não conseguir analisar."
  else
    log_ok "Modelo '${MODEL}' disponível."
  fi
fi

# =============================================================================
# PASSO 4 — Iniciar agente
# =============================================================================
log_step "Passo 4 — Agente AIOps (webhook receiver)"

# Libera a porta se necessário
free_port 5001 "agente" || true

# Verifica pré-requisitos do agente
AGENT_OK=true

if [ ! -f "${PROJECT_DIR}/agent/.env" ]; then
  log_warn ".env não encontrado em agent/. O agente usará apenas variáveis de ambiente."
fi

if [ ! -f "${PROJECT_DIR}/.venv/bin/uvicorn" ]; then
  log_err "venv não encontrado. Execute: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
  AGENT_OK=false
fi

if ! $AGENT_OK; then
  log_err "Pré-requisitos do agente ausentes. Abortando."
  exit 1
fi

log_info "Iniciando agente (log: ${AGENT_LOG})"
cd "${PROJECT_DIR}/agent" && \
  ../.venv/bin/uvicorn webhook_receiver:app \
    --host 0.0.0.0 --port 5001 \
    --log-level info \
    >> "$AGENT_LOG" 2>&1 &
AGENT_PID=$!
BG_PIDS+=($AGENT_PID)
cd "$PROJECT_DIR"

log_info "Aguardando agente subir (até 15s)..."
AGENT_UP=false
for i in $(seq 1 15); do
  if curl -sf http://localhost:5001/health -o /dev/null 2>/dev/null; then
    HEALTH=$(curl -s http://localhost:5001/health 2>/dev/null || echo "{}")
    log_ok "Agente respondendo: ${HEALTH}"
    AGENT_UP=true
    break
  fi
  # Verifica se o processo ainda está vivo
  if ! kill -0 "$AGENT_PID" 2>/dev/null; then
    log_err "Processo do agente morreu prematuramente. Últimas linhas do log:"
    tail -10 "$AGENT_LOG" 2>/dev/null | sed 's/^/    /'
    log_info "Diagnóstico possível:"
    log_info "  • Verifique agent/.env (OLLAMA_BASE_URL, TEAMS_WEBHOOK_URL)"
    log_info "  • Teste manualmente: cd agent && ../.venv/bin/python -c 'import webhook_receiver'"
    AGENT_OK=false
    break
  fi
  sleep 1
done

if ! $AGENT_UP && $AGENT_OK; then
  log_err "Agente não respondeu em 15s mas o processo ainda está vivo."
  log_info "Últimas linhas do log do agente:"
  tail -10 "$AGENT_LOG" 2>/dev/null | sed 's/^/    /'
  warn "Agente pode estar com inicialização lenta. Continuando."
fi

# =============================================================================
# PASSO 5 — Fast check
# =============================================================================
log_step "Passo 5 — Fast check: fixture → agente → Teams"

FIXTURE="${PROJECT_DIR}/tests/fixtures/zeebe-memory-alert.json"

if ! $AGENT_UP; then
  log_warn "Agente não está disponível — pulando fast check."
elif [ ! -f "$FIXTURE" ]; then
  log_warn "Fixture não encontrado: ${FIXTURE} — pulando fast check."
else
  log_info "Enviando: $(basename "$FIXTURE")"

  FC_RESPONSE="/tmp/camunda-aiops-fast-check-$$.json"
  HTTP_STATUS=$(curl -s -o "$FC_RESPONSE" -w "%{http_code}" \
    -X POST http://localhost:5001/webhook \
    -H "Content-Type: application/json" \
    -d @"$FIXTURE" 2>/dev/null || echo "000")

  case "$HTTP_STATUS" in
    200)
      MSG=$(python3 -c \
        "import json; d=json.load(open('$FC_RESPONSE')); print(d.get('message','?'))" \
        2>/dev/null || echo "?")
      log_ok "Fast check OK (HTTP 200) — ${MSG}"
      log_info "Aguardando análise do LLM (pode levar alguns segundos)..."
      # Aguarda até 30s pela análise aparecer no log
      for i in $(seq 1 30); do
        if grep -q "Análise concluída" "$AGENT_LOG" 2>/dev/null; then
          break
        fi
        sleep 1
      done
      echo ""
      log_info "Trecho do log do agente:"
      grep -A5 "Análise concluída\|CAUSA_RAIZ\|Notificação enviada" "$AGENT_LOG" 2>/dev/null \
        | head -20 | sed 's/^/    /' || true
      ;;
    000)
      log_err "Falha de conexão com o agente (curl retornou erro de rede)."
      warn "Fast check falhou — verifique se o agente está rodando."
      ;;
    *)
      log_warn "Fast check retornou HTTP ${HTTP_STATUS}. Resposta:"
      python3 -m json.tool "$FC_RESPONSE" 2>/dev/null | sed 's/^/    /' || \
        cat "$FC_RESPONSE" | sed 's/^/    /'
      warn "Fast check com status inesperado (${HTTP_STATUS})."
      ;;
  esac
fi

# =============================================================================
# PASSO 6 — Load generator (opcional)
# =============================================================================
if [ "$SKIP_LOAD" = true ]; then
  log_warn "Load-generator pulado (--skip-load). Agente aguardando alertas reais."
else
  log_step "Passo 6 — Load generator (${INTENSITY}, ${DURATION_MIN}min)"
  log_info "Cria pressão de CPU/memória para alimentar séries temporais."
  log_warn "Alertas predict_linear precisam de 30m+ de histórico para disparar organicamente."
  echo ""

  if [ ! -x "${PROJECT_DIR}/scripts/load-generator.sh" ]; then
    log_err "load-generator.sh não encontrado ou sem permissão de execução."
    warn "Load-generator indisponível."
  else
    "${PROJECT_DIR}/scripts/load-generator.sh" \
      --duration "$DURATION_MIN" \
      --intensity "$INTENSITY" &
    LOAD_PID=$!
    BG_PIDS+=($LOAD_PID)
    log_ok "Load-generator iniciado (PID ${LOAD_PID})."
  fi
fi

# =============================================================================
# PASSO 7 — Monitoramento
# =============================================================================
log_step "Passo 7 — Monitoramento em tempo real"

# Resumo de avisos acumulados
if [ "$WARNINGS" -gt 0 ]; then
  echo -e "  ${YELLOW}Avisos acumulados durante a inicialização: ${WARNINGS}${NC}"
  echo -e "  ${YELLOW}Verifique as mensagens ⚠ acima para serviços degradados.${NC}"
  echo ""
fi

echo -e "  ${BOLD}Endpoints:${NC}"
echo -e "    Agente:       ${CYAN}http://localhost:5001/health${NC}"
echo -e "    Prometheus:   ${CYAN}http://localhost:9090/alerts${NC}"
echo -e "    Alertmanager: ${CYAN}http://localhost:9093${NC}"
echo -e "    Grafana:      ${CYAN}http://localhost:3000${NC}"
echo ""
echo -e "  ${BOLD}Enviar alerta manualmente:${NC}"
echo -e "    ${CYAN}curl -X POST http://localhost:5001/webhook \\"
echo -e "      -H 'Content-Type: application/json' \\"
echo -e "      -d @${PROJECT_DIR}/tests/fixtures/zeebe-memory-alert.json${NC}"
echo ""
echo -e "  ${BOLD}Log completo do agente:${NC}"
echo -e "    ${CYAN}tail -f ${AGENT_LOG}${NC}"
echo ""
echo -e "${YELLOW}  Pressione Ctrl+C para encerrar e limpar todos os recursos.${NC}"
echo ""

# Tail em primeiro plano — bloqueia até Ctrl+C
tail -f "$AGENT_LOG"
