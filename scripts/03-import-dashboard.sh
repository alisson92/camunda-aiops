#!/usr/bin/env bash
# =============================================================================
# 03-import-dashboard.sh
#
# Finalidade: importar o dashboard de forecasting direto via API do Grafana
# (sem precisar clicar em import na UI)
#
# Uso:
#   chmod +x 03-import-dashboard.sh
#   ./03-import-dashboard.sh
#
# Pré-requisito:
#   kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
# =============================================================================

set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
# Sem default de senha — deve ser passada via variável de ambiente ou flag
# para não criar falsa sensação de segurança com valor hardcoded.
# Exemplo: GRAFANA_PASS=grafana-secret ./03-import-dashboard.sh
GRAFANA_PASS="${GRAFANA_PASS:-}"

DASHBOARD_FILE="$(dirname "$0")/../dashboards/camunda-forecasting.json"

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; NC='\033[0m'

# =============================================================================
# Resolver senha: variável de ambiente, flag --password, ou perguntar
# =============================================================================
while [[ $# -gt 0 ]]; do
  case $1 in
    --password|-p) GRAFANA_PASS="$2"; shift 2 ;;
    --url)         GRAFANA_URL="$2";  shift 2 ;;
    --user)        GRAFANA_USER="$2"; shift 2 ;;
    *) echo -e "${RED}Flag desconhecida: $1${NC}"; exit 1 ;;
  esac
done

if [[ -z "$GRAFANA_PASS" ]]; then
  echo -e "${YELLOW}⚠  GRAFANA_PASS não definida.${NC}"
  echo -e "   Dica: verifique a senha real com:"
  echo -e "   kubectl get secret -n monitoring kube-prometheus-stack-grafana \\"
  echo -e "     -o jsonpath='{.data.admin-password}' | base64 -d && echo"
  echo ""
  read -rsp "   Senha do Grafana (usuário: ${GRAFANA_USER}): " GRAFANA_PASS
  echo ""
fi

# =============================================================================
# Verificação 1: Grafana está no ar?
# /api/health retorna 200 sem autenticação — serve apenas para checar
# conectividade, não credenciais.
# =============================================================================
echo -e "${CYAN}→${NC} Verificando conectividade com Grafana em ${GRAFANA_URL}..."
HTTP_HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${GRAFANA_URL}/api/health")
if [[ "$HTTP_HEALTH" != "200" ]]; then
  echo -e "${RED}ERRO: Grafana não acessível (HTTP ${HTTP_HEALTH})${NC}"
  echo "  Verifique o port-forward:"
  echo "  kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80"
  exit 1
fi
echo -e "${GREEN}✓${NC} Grafana acessível"

# =============================================================================
# Verificação 2: credenciais válidas?
# /api/org requer autenticação — retorna 401 com credenciais erradas.
# =============================================================================
echo -e "${CYAN}→${NC} Validando credenciais..."
HTTP_AUTH=$(curl -s -o /dev/null -w "%{http_code}" \
  -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
  "${GRAFANA_URL}/api/org")

if [[ "$HTTP_AUTH" == "401" ]]; then
  echo -e "${RED}ERRO: Credenciais inválidas (HTTP 401)${NC}"
  echo "  Usuário: ${GRAFANA_USER}"
  echo "  Verifique a senha real com:"
  echo "  kubectl get secret -n monitoring kube-prometheus-stack-grafana \\"
  echo "    -o jsonpath='{.data.admin-password}' | base64 -d && echo"
  exit 1
elif [[ "$HTTP_AUTH" != "200" ]]; then
  echo -e "${RED}ERRO: Resposta inesperada ao validar credenciais (HTTP ${HTTP_AUTH})${NC}"
  exit 1
fi
echo -e "${GREEN}✓${NC} Credenciais válidas"

echo -e "${CYAN}→${NC} Importando dashboard no Grafana..."

# Montar payload — a API do Grafana espera o JSON dentro de um wrapper "dashboard"
PAYLOAD=$(python3 -c "
import json, sys
with open('${DASHBOARD_FILE}') as f:
    dashboard = json.load(f)
# Remover id para forçar criação (não update)
dashboard.pop('id', None)
payload = {
    'dashboard': dashboard,
    'overwrite': True,
    'folderId': 0,
    'message': 'Importado via 03-import-dashboard.sh'
}
print(json.dumps(payload))
")

# =============================================================================
# Import: captura HTTP status e body separadamente para diagnóstico preciso
# -s silencia progresso, -w captura status, -o captura body
# =============================================================================
BODY_FILE=$(mktemp)
HTTP_IMPORT=$(curl -s -o "${BODY_FILE}" -w "%{http_code}" \
  -X POST "${GRAFANA_URL}/api/dashboards/db" \
  -H "Content-Type: application/json" \
  -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
  -d "${PAYLOAD}")
RESPONSE=$(cat "${BODY_FILE}")
rm -f "${BODY_FILE}"

if [[ "$HTTP_IMPORT" != "200" ]]; then
  echo -e "${RED}ERRO: Import falhou (HTTP ${HTTP_IMPORT})${NC}"
  echo "  Resposta da API:"
  echo "$RESPONSE" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('  message:', d.get('message', '?'))
except:
    print(sys.stdin.read())
" 2>/dev/null || echo "$RESPONSE"
  exit 1
fi

URL=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('url', '?'))" 2>/dev/null || echo "?")

echo -e "${GREEN}✓ Dashboard importado com sucesso!${NC}"
echo -e "  Acesse: ${GRAFANA_URL}${URL}"
echo ""
echo -e "${CYAN}Próximos passos:${NC}"
echo "  1. Abra o dashboard no Grafana"
echo "  2. Aguarde pelo menos 5min de dados coletados"
echo "  3. Execute ./02-load-generator.sh para gerar variação nas métricas"
echo "  4. Observe os painéis de predict_linear e deriv() mudando em tempo real"
