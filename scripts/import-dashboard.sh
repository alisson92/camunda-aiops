#!/usr/bin/env bash
# =============================================================================
# import-dashboard.sh
#
# Finalidade: importar todos os dashboards de dashboards/ via API do Grafana.
# Idempotente — pula dashboards que já existem (mesmo uid), importa apenas
# os ausentes. Novos arquivos em dashboards/*.json são importados automaticamente
# sem precisar alterar este script.
#
# Uso:
#   ./scripts/import-dashboard.sh
#   GRAFANA_PASS=<senha> ./scripts/import-dashboard.sh
#
# Pré-requisito:
#   kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
# =============================================================================

set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
# Sem default de senha — deve ser passada via variável de ambiente ou flag
# para não criar falsa sensação de segurança com valor hardcoded.
GRAFANA_PASS="${GRAFANA_PASS:-}"

DASHBOARDS_DIR="$(dirname "$0")/../dashboards"

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

# =============================================================================
# Importar todos os arquivos *.json em dashboards/ — idempotente por uid.
# Consulta a API antes de importar: pula se o uid já existir, importa se não.
# Novos dashboards adicionados à pasta são importados automaticamente.
# =============================================================================
IMPORTED=0
SKIPPED=0

for DASHBOARD_FILE in "${DASHBOARDS_DIR}"/*.json; do
  TITLE=$(python3 -c "import json; d=json.load(open('${DASHBOARD_FILE}')); print(d.get('title','?'))" 2>/dev/null)
  UID=$(python3 -c "import json; d=json.load(open('${DASHBOARD_FILE}')); print(d.get('uid',''))" 2>/dev/null)

  # Verificar se uid já existe no Grafana antes de importar
  if [[ -n "$UID" ]]; then
    HTTP_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
      -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
      "${GRAFANA_URL}/api/dashboards/uid/${UID}")
    if [[ "$HTTP_CHECK" == "200" ]]; then
      echo -e "  ${YELLOW}→ já existe:${NC} ${TITLE} (uid: ${UID})"
      SKIPPED=$((SKIPPED + 1))
      continue
    fi
  fi

  echo -e "${CYAN}→${NC} Importando: ${TITLE}..."

  PAYLOAD=$(python3 -c "
import json
with open('${DASHBOARD_FILE}') as f:
    dashboard = json.load(f)
dashboard.pop('id', None)
payload = {
    'dashboard': dashboard,
    'overwrite': True,
    'folderId': 0,
    'message': 'Importado via import-dashboard.sh'
}
print(json.dumps(payload))
")

  BODY_FILE=$(mktemp)
  HTTP_IMPORT=$(curl -s -o "${BODY_FILE}" -w "%{http_code}" \
    -X POST "${GRAFANA_URL}/api/dashboards/db" \
    -H "Content-Type: application/json" \
    -u "${GRAFANA_USER}:${GRAFANA_PASS}" \
    -d "${PAYLOAD}")
  RESPONSE=$(cat "${BODY_FILE}")
  rm -f "${BODY_FILE}"

  if [[ "$HTTP_IMPORT" != "200" ]]; then
    echo -e "  ${RED}ERRO ao importar ${TITLE} (HTTP ${HTTP_IMPORT})${NC}"
    echo "$RESPONSE" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print('  message:', d.get('message', '?'))
except:
    print(sys.stdin.read())
" 2>/dev/null || echo "$RESPONSE"
    continue
  fi

  URL=$(echo "$RESPONSE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('url',''))" 2>/dev/null || echo "")
  echo -e "  ${GREEN}✓${NC} ${TITLE}"
  [[ -n "$URL" ]] && echo -e "     ${GRAFANA_URL}${URL}"
  IMPORTED=$((IMPORTED + 1))
done

echo ""
echo -e "${GREEN}Concluído:${NC} ${IMPORTED} importado(s), ${SKIPPED} já existia(m)."

if [[ $IMPORTED -gt 0 ]]; then
  echo ""
  echo -e "${CYAN}Próximos passos:${NC}"
  echo "  1. Abra os dashboards no Grafana: ${GRAFANA_URL}"
  echo "  2. Aguarde pelo menos 5min de dados coletados"
  echo "  3. Execute make load para gerar variação nas métricas"
fi
