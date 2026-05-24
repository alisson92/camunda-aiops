# Makefile — grafana-ml-lab
# Documentação executável das operações mais comuns do projeto.
# Uso: make <target>

.PHONY: run test smoke lint help

# ── Agente ─────────────────────────────────────────────────────────────────────

run: ## Inicia o agente (webhook receiver) em modo desenvolvimento
	cd agent && uvicorn webhook_receiver:app --host 0.0.0.0 --port 5001 --reload

# ── Testes ─────────────────────────────────────────────────────────────────────

test: ## Roda a suíte de testes automatizados com pytest
	pytest

smoke: ## Envia os 3 alertas de teste para o Teams (critical, warning, info)
	PYTHONPATH=agent python3 tests/test_teams_notifier.py

smoke-%: ## Envia um cenário específico: make smoke-critical | smoke-warning | smoke-info | smoke-resolved
	PYTHONPATH=agent python3 tests/test_teams_notifier.py $*

# ── Qualidade ──────────────────────────────────────────────────────────────────

lint: ## Valida sintaxe e estilo dos módulos Python (requer ruff)
	ruff check agent/

# ── Kubernetes / Observabilidade ───────────────────────────────────────────────

port-forward: ## Abre port-forwards para Prometheus e Grafana (Kind local)
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &

check-metrics: ## Inspeciona métricas disponíveis no Prometheus
	./scripts/check-metrics.sh

import-dashboard: ## Importa o dashboard de forecasting no Grafana
	./scripts/import-dashboard.sh

# ── Ajuda ──────────────────────────────────────────────────────────────────────

help: ## Lista todos os targets disponíveis
	@grep -E '^[a-zA-Z_%-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
