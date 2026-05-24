#!/usr/bin/env bash
# =============================================================================
# 01-check-metrics.sh
#
# Finalidade: inspecionar quais métricas do Camunda/K8s já estão sendo
# coletadas pelo Prometheus. Roda queries direto na API do Prometheus via
# port-forward — não precisa de Grafana aberto.
#
# Uso:
#   chmod +x 01-check-metrics.sh
#   ./01-check-metrics.sh
#
# Pré-requisito: port-forward ativo em background ou em outro terminal:
#   kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
# =============================================================================

set -euo pipefail

PROMETHEUS_URL="${PROMETHEUS_URL:-http://localhost:9090}"

# Cor para output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

log_section() { echo -e "\n${CYAN}══════════════════════════════════════════${NC}"; echo -e "${CYAN}  $1${NC}"; echo -e "${CYAN}══════════════════════════════════════════${NC}"; }
log_ok()      { echo -e "  ${GREEN}✓${NC} $1"; }
log_warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
log_info()    { echo -e "  ${CYAN}→${NC} $1"; }

# Função: lista métricas filtradas por prefixo
list_metrics() {
  local prefix="$1"
  local description="$2"
  log_info "Buscando métricas — ${description} (prefixo: ${prefix})"
  local result
  result=$(curl -sf "${PROMETHEUS_URL}/api/v1/label/__name__/values" \
    | python3 -c "
import json, sys
data = json.load(sys.stdin)
metrics = [m for m in data.get('data', []) if m.startswith('${prefix}')]
print(f'  Encontradas: {len(metrics)}')
for m in sorted(metrics):
    print(f'    - {m}')
" 2>/dev/null || echo "  (erro ao consultar Prometheus)")
  echo "$result"
}

# Função: verifica se uma métrica tem dados recentes (últimos 5min)
check_recent() {
  local metric="$1"
  local result
  result=$(curl -sf \
    "${PROMETHEUS_URL}/api/v1/query?query=${metric}" \
    | python3 -c "
import json, sys
data = json.load(sys.stdin)
results = data.get('data', {}).get('result', [])
if results:
    print(f'OK ({len(results)} série(s))')
else:
    print('SEM DADOS')
" 2>/dev/null || echo "ERRO")
  echo "$result"
}

# =============================================================================
# INÍCIO
# =============================================================================

log_section "Verificando conectividade com Prometheus"
if curl -sf "${PROMETHEUS_URL}/-/healthy" > /dev/null; then
  log_ok "Prometheus acessível em ${PROMETHEUS_URL}"
else
  echo -e "${RED}ERRO: Não foi possível acessar ${PROMETHEUS_URL}${NC}"
  echo "Execute primeiro:"
  echo "  kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &"
  exit 1
fi

# =============================================================================
log_section "Métricas do Zeebe (motor BPMN)"
# zeebe_* — métricas expostas pelo Zeebe via ServiceMonitor
list_metrics "zeebe_" "Zeebe engine"

log_section "Métricas do Operate"
list_metrics "operate_" "Operate UI"

log_section "Métricas do Tasklist"
list_metrics "tasklist_" "Tasklist UI"

log_section "Métricas Java/JVM (pods Camunda)"
# jvm_* — expostas pelo actuator Spring Boot em cada componente
list_metrics "jvm_" "JVM heap, GC, threads"

log_section "Métricas HTTP (Actuator/Micrometer)"
# http_server_requests_* — latência e contagem de requests HTTP
list_metrics "http_server_requests" "HTTP requests Spring"

log_section "Métricas dos nodes K8s (node-exporter)"
echo ""
for metric in \
  "node_cpu_seconds_total" \
  "node_memory_MemAvailable_bytes" \
  "node_filesystem_avail_bytes" \
  "node_load1"; do
  status=$(check_recent "$metric")
  log_info "${metric}: ${status}"
done

log_section "Métricas dos pods K8s (kube-state-metrics)"
echo ""
for metric in \
  "kube_pod_container_resource_requests" \
  "kube_pod_container_resource_limits" \
  "kube_pod_status_phase" \
  "kube_deployment_status_replicas_ready"; do
  status=$(check_recent "$metric")
  log_info "${metric}: ${status}"
done

log_section "Métricas de containers (cadvisor)"
echo ""
for metric in \
  "container_cpu_usage_seconds_total" \
  "container_memory_working_set_bytes" \
  "container_network_receive_bytes_total"; do
  status=$(check_recent "$metric")
  log_info "${metric}: ${status}"
done

log_section "Métricas do Elasticsearch"
list_metrics "elasticsearch_" "Elasticsearch"

# =============================================================================
log_section "Resumo — PromQL úteis para forecasting"
cat <<'EOF'

  # CPU de todos os pods do namespace camunda (média 5min)
  avg by (pod) (
    rate(container_cpu_usage_seconds_total{namespace="camunda"}[5m])
  )

  # Memória working set dos pods Camunda
  container_memory_working_set_bytes{namespace="camunda"}

  # Zeebe: jobs ativados por segundo (se a métrica existir)
  rate(zeebe_job_activated_total[5m])

  # Zeebe: processos completados
  rate(zeebe_process_instance_events_total{action="completed"}[5m])

  # JVM heap usado (componentes Java)
  jvm_memory_used_bytes{area="heap", namespace="camunda"}

  # Requests HTTP por segundo nos pods Camunda
  rate(http_server_requests_seconds_count{namespace="camunda"}[5m])

  # Latência p99 dos requests HTTP
  histogram_quantile(0.99,
    rate(http_server_requests_seconds_bucket{namespace="camunda"}[5m])
  )

EOF

echo -e "${GREEN}✓ Verificação concluída${NC}"
