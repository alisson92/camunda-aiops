#!/usr/bin/env bash
# =============================================================================
# 02-load-generator.sh
#
# Finalidade: gerar carga sintética variada no cluster Kind para criar
# padrões de série temporal com sazonalidade — tornando o forecasting
# no Grafana mais interessante e visível.
#
# O que este script faz:
#   - Cria um namespace "load-test" isolado
#   - Sobe um Pod gerador de carga CPU/memória com padrão oscilatório
#   - Faz requests HTTP repetidos no Operate e Tasklist (port-forward)
#   - Cria múltiplos Zeebe process instances via Zeebe REST API
#   - Varia a intensidade em ondas (simula pico de manhã + vale à tarde)
#
# Uso:
#   chmod +x 02-load-generator.sh
#   ./02-load-generator.sh [--duration 30] [--intensity low|medium|high]
#
# Flags:
#   --duration   Duração total em minutos (default: 20)
#   --intensity  Intensidade da carga (default: medium)
#   --dry-run    Mostra o que faria sem executar
#
# Para parar a qualquer momento: Ctrl+C (o trap limpa os recursos)
# =============================================================================

set -euo pipefail

# =============================================================================
# Defaults e parsing de argumentos
# =============================================================================
DURATION_MIN=20
INTENSITY="medium"
DRY_RUN=false
NAMESPACE_LOAD="load-test"

# Portas dos serviços (requer port-forward ativo)
OPERATE_URL="http://localhost:8081"
TASKLIST_URL="http://localhost:8082"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

while [[ $# -gt 0 ]]; do
  case $1 in
    --duration)  DURATION_MIN="$2"; shift 2 ;;
    --intensity) INTENSITY="$2";    shift 2 ;;
    --dry-run)   DRY_RUN=true;      shift   ;;
    *) echo "Flag desconhecida: $1"; exit 1 ;;
  esac
done

# Configurações por intensidade
case "$INTENSITY" in
  low)    WORKERS=1; HTTP_INTERVAL=5;  CPU_LOAD="10m"; MEM_LOAD="64Mi"  ;;
  medium) WORKERS=2; HTTP_INTERVAL=2;  CPU_LOAD="50m"; MEM_LOAD="128Mi" ;;
  high)   WORKERS=4; HTTP_INTERVAL=1;  CPU_LOAD="200m"; MEM_LOAD="256Mi" ;;
  *) echo "${RED}Intensidade inválida: ${INTENSITY}${NC}"; exit 1 ;;
esac

DURATION_SEC=$((DURATION_MIN * 60))

log_info() { echo -e "${CYAN}→${NC} $1"; }
log_ok()   { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }

# =============================================================================
# Trap: limpar recursos ao sair (Ctrl+C ou fim do script)
# =============================================================================
cleanup() {
  echo ""
  log_warn "Encerrando e limpando recursos de carga..."
  kubectl delete namespace "${NAMESPACE_LOAD}" --ignore-not-found=true 2>/dev/null || true
  # Encerrar processos de background deste script
  jobs -p | xargs -r kill 2>/dev/null || true
  log_ok "Cleanup concluído"
}
trap cleanup EXIT INT TERM

# =============================================================================
# Dry-run
# =============================================================================
if [ "$DRY_RUN" = true ]; then
  echo -e "\n${YELLOW}[DRY-RUN] O que seria executado:${NC}"
  echo "  Duração:    ${DURATION_MIN} minutos"
  echo "  Intensidade: ${INTENSITY}"
  echo "  Workers:    ${WORKERS} pods de carga"
  echo "  CPU por pod: ${CPU_LOAD}"
  echo "  Memória:    ${MEM_LOAD}"
  echo "  HTTP interval: ${HTTP_INTERVAL}s"
  echo ""
  echo "  Recursos criados:"
  echo "    namespace/${NAMESPACE_LOAD}"
  echo "    deployment/cpu-burner (${WORKERS} réplicas)"
  echo "  Serviços chamados:"
  echo "    GET ${OPERATE_URL}/actuator/health (a cada ${HTTP_INTERVAL}s)"
  echo "    GET ${TASKLIST_URL}/actuator/health (a cada ${HTTP_INTERVAL}s)"
  exit 0
fi

# =============================================================================
# Verificar contexto — não executa em produção/EKS
# =============================================================================
CURRENT_CONTEXT=$(kubectl config current-context)
if [[ "$CURRENT_CONTEXT" != *"kind"* ]]; then
  echo -e "${RED}ATENÇÃO: contexto atual é '${CURRENT_CONTEXT}' (não é Kind!)${NC}"
  echo "Este script só deve rodar em ambiente local. Abortando."
  exit 1
fi
log_ok "Contexto Kind confirmado: ${CURRENT_CONTEXT}"

# =============================================================================
# Fase 1: Namespace de carga
# =============================================================================
log_info "Criando namespace de carga isolado: ${NAMESPACE_LOAD}"
kubectl create namespace "${NAMESPACE_LOAD}" --dry-run=client -o yaml | kubectl apply -f -

# =============================================================================
# Fase 2: Pod gerador de CPU/memória com padrão oscilatório
# O stress-ng vai variar entre idle e load conforme onda senoidal simulada
# =============================================================================
log_info "Subindo ${WORKERS} workers de carga CPU/memória (${CPU_LOAD} cada)..."

cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cpu-burner
  namespace: ${NAMESPACE_LOAD}
  labels:
    app: cpu-burner
    purpose: load-test
spec:
  replicas: ${WORKERS}
  selector:
    matchLabels:
      app: cpu-burner
  template:
    metadata:
      labels:
        app: cpu-burner
        purpose: load-test
    spec:
      # Sem afinidade — distribui entre workers
      containers:
      - name: stress
        # Imagem leve com stress-ng disponível
        image: containerstack/alpine-stress:latest
        command:
        - /bin/sh
        - -c
        - |
          echo "Worker iniciado em \$(hostname)"
          # Loop com variação de intensidade para criar sazonalidade
          CYCLE=0
          while true; do
            CYCLE=\$((CYCLE + 1))
            # Fase "pico": 30s de stress
            echo "Ciclo \${CYCLE}: fase pico (30s)"
            stress-ng --cpu 1 --timeout 30s --quiet 2>/dev/null || sleep 30
            # Fase "vale": 15s idle
            echo "Ciclo \${CYCLE}: fase idle (15s)"
            sleep 15
            # A cada 3 ciclos: pico duplo (simula batch noturno)
            if [ \$((CYCLE % 3)) -eq 0 ]; then
              echo "Ciclo \${CYCLE}: batch extra (60s)"
              stress-ng --cpu 1 --vm 1 --vm-bytes 64M --timeout 60s --quiet 2>/dev/null || sleep 60
            fi
          done
        resources:
          requests:
            cpu: "${CPU_LOAD}"
            memory: "${MEM_LOAD}"
          limits:
            cpu: "$(echo ${CPU_LOAD} | sed 's/m//' | awk '{print int($1*2)"m"}')"
            memory: "$(echo ${MEM_LOAD} | sed 's/Mi//' | awk '{print int($1*2)"Mi"}')"
      restartPolicy: Always
      terminationGracePeriodSeconds: 5
EOF

log_ok "Deployment cpu-burner criado. Aguardando pods ficarem Running..."
kubectl wait --for=condition=ready pod -l app=cpu-burner -n "${NAMESPACE_LOAD}" \
  --timeout=90s 2>/dev/null || log_warn "Pods ainda iniciando (normal para imagem nova)"

# =============================================================================
# Fase 3: Loop de requests HTTP para gerar métricas http_server_requests_*
# Isso vai aparecer como série temporal no Prometheus via actuator
# =============================================================================
log_info "Iniciando loop de requests HTTP (intervalo: ${HTTP_INTERVAL}s)..."

http_loop() {
  local url="$1"
  local label="$2"
  local interval="$3"
  local end_time=$(($(date +%s) + DURATION_SEC))

  while [ "$(date +%s)" -lt "$end_time" ]; do
    log_info "[${label}] request cycle"
    curl -sf "${url}/actuator/health"   -o /dev/null 2>/dev/null || true
    curl -sf "${url}/actuator/prometheus" -o /dev/null 2>/dev/null || true
    curl -sf "${url}/api/v1/process-instances?pageSize=10" -o /dev/null 2>/dev/null || true
    sleep "${interval}"
  done
}

# Roda em background — os PIDs serão encerrados pelo trap ao final do script
http_loop "${OPERATE_URL}"  "operate"  "${HTTP_INTERVAL}" &
http_loop "${TASKLIST_URL}" "tasklist" "${HTTP_INTERVAL}" &

# =============================================================================
# Fase 4: Variação de pods (scale up/down) para gerar métricas kube_*
# Isso cria padrões interessantes em kube_deployment_status_replicas_ready
# =============================================================================
log_info "Iniciando ciclo de scale up/down do cpu-burner..."

scale_cycle() {
  local end_time=$(($(date +%s) + DURATION_SEC))
  local step=0
  # Padrão: 1 → 3 → 1 → 2 → 1 → ...
  local replicas_seq=(1 2 3 2 1 3 1 2)
  local seq_len=${#replicas_seq[@]}

  while [ "$(date +%s)" -lt "$end_time" ]; do
    local target=${replicas_seq[$((step % seq_len))]}
    kubectl scale deployment cpu-burner -n "${NAMESPACE_LOAD}" \
      --replicas="${target}" 2>/dev/null || true
    step=$((step + 1))
    # Aguarda ~90s entre cada mudança de escala
    sleep 90
  done
}
scale_cycle &

# =============================================================================
# Fase 5: Monitor de progresso
# =============================================================================
echo ""
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Carga ativa por ${DURATION_MIN} minutos${NC}"
echo -e "${GREEN}  Intensidade: ${INTENSITY}${NC}"
echo -e "${GREEN}  Ctrl+C para parar e limpar${NC}"
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo ""
echo -e "${CYAN}Port-forwards recomendados (em outros terminais):${NC}"
echo "  kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090"
echo "  kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80"
echo ""
echo -e "${CYAN}PromQL para ver o efeito em tempo real:${NC}"
echo "  # CPU do namespace load-test"
echo "  rate(container_cpu_usage_seconds_total{namespace=\"${NAMESPACE_LOAD}\"}[2m])"
echo "  # Pods running"
echo "  kube_pod_status_phase{namespace=\"${NAMESPACE_LOAD}\", phase=\"Running\"}"
echo ""

# Countdown
START_TIME=$(date +%s)
while true; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START_TIME))
  REMAINING=$((DURATION_SEC - ELAPSED))

  if [ "$REMAINING" -le 0 ]; then
    break
  fi

  ELAPSED_MIN=$((ELAPSED / 60))
  ELAPSED_SEC=$((ELAPSED % 60))
  REMAIN_MIN=$((REMAINING / 60))
  REMAIN_SEC=$((REMAINING % 60))

  printf "\r  Decorrido: %02d:%02d | Restante: %02d:%02d  " \
    "$ELAPSED_MIN" "$ELAPSED_SEC" "$REMAIN_MIN" "$REMAIN_SEC"
  sleep 5
done

echo ""
log_ok "Duração de ${DURATION_MIN}min concluída. Limpando recursos..."
