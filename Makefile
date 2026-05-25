# Makefile — camunda-aiops
# Documentação executável das operações mais comuns do projeto.
# Uso: make <target>
#
# Ambiente: todas as ferramentas Python são executadas via .venv local.

# Garante que `make` sem argumentos exibe o help em vez de executar o primeiro target
.DEFAULT_GOAL := help
# Crie o venv com: python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"

PYTHON := .venv/bin/python
PYTEST  := .venv/bin/pytest
RUFF    := .venv/bin/ruff

.PHONY: run test test-integration test-e2e smoke demo lint \
        port-forward check-metrics check-pod-metrics import-dashboard load \
        cycle-test cycle-test-fast help

# ── Agente ─────────────────────────────────────────────────────────────────────

run: ## Inicia o agente (webhook receiver) em modo desenvolvimento
	cd agent && ../.venv/bin/uvicorn webhook_receiver:app --host 0.0.0.0 \
		--port $$(python3 -c "import urllib.parse,os; u=os.environ.get('AGENT_PUBLIC_URL','http://localhost:5001'); print(urllib.parse.urlparse(u).port or 5001)") \
		--reload

# ── Testes ─────────────────────────────────────────────────────────────────────

test: ## Roda testes unitários com cobertura (exclui integração e e2e)
	$(PYTEST) --cov --cov-report=term-missing -m "not integration and not e2e"

test-integration: ## Roda testes de integração contra containers Docker reais
	$(PYTEST) -m integration -v

test-e2e: ## Roda testes E2E do ciclo completo (Docker + mock HTTP)
	$(PYTEST) -m e2e -v

smoke: ## Envia os 3 alertas de teste para o Teams; inicia port-forwards se Kind estiver ativo
	./scripts/smoke.sh

smoke-%: ## Envia um cenário específico: make smoke-critical | smoke-warning | smoke-info | smoke-resolved
	./scripts/smoke.sh $*

demo: ## Demo completa: autossuficiente — inicia Ollama + agente, injeta 4 cenários, encerra tudo
	./scripts/demo.sh

demo-%: ## Demo de um cenário específico: make demo-zeebe | demo-namespace | demo-backpressure | demo-resolved
	./scripts/demo.sh --scenario $*

# ── Qualidade ──────────────────────────────────────────────────────────────────

lint: ## Valida sintaxe e estilo dos módulos Python (requer ruff)
	$(RUFF) check agent/

# ── Kubernetes / Observabilidade ───────────────────────────────────────────────

port-forward: ## Abre port-forwards para Prometheus e Grafana (Kind local)
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80 &

check-metrics: ## Inspeciona métricas disponíveis no Prometheus (via API)
	./scripts/check-metrics.sh

check-pod-metrics: ## Verifica se os pods expõem /actuator/prometheus diretamente (kubectl exec)
	./scripts/test-port-metrics.sh

import-dashboard: ## Importa o dashboard de forecasting no Grafana
	./scripts/import-dashboard.sh

load: ## Gera carga sintética no Kind (medium, 30min) — use DURATION e INTENSITY para customizar
	./scripts/load-generator.sh --duration $(or $(DURATION),30) --intensity $(or $(INTENSITY),medium)

cycle-test: ## Ciclo completo: PrometheusRule + port-forwards + agente + fast check + load
	./scripts/run-cycle-test.sh \
	  $(if $(CONTEXT),--context $(CONTEXT),) \
	  --intensity $(or $(INTENSITY),medium) \
	  --duration $(or $(DURATION),20)

cycle-test-fast: ## Ciclo sem load-generator (só fast check — útil quando já há histórico)
	./scripts/run-cycle-test.sh $(if $(CONTEXT),--context $(CONTEXT),) --skip-load

# ── Ajuda ──────────────────────────────────────────────────────────────────────

help: ## Lista todos os targets disponíveis
	@grep -E '^[a-zA-Z0-9_%/-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
