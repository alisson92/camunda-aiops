# Makefile — camunda-aiops
# Documentação executável das operações mais comuns do projeto.
# Uso: make <target>   |   make help
#
# Convenções de comentário para o help:
#   ##@ Grupo     → cabeçalho de seção
#   ## Descrição  → aparece no help ao lado do target
#   ##  ↳ ...     → linha de exemplo (indentada, dimmed)

.DEFAULT_GOAL := help

PYTHON     := .venv/bin/python
PYTEST     := .venv/bin/pytest
RUFF       := .venv/bin/ruff
SHELLCHECK := .venv/bin/shellcheck
YAMLLINT   := $(shell command -v yamllint 2>/dev/null || echo "yamllint")

IMAGE_NAME   := camunda-aiops-agent
IMAGE_TAG    := latest
KIND_CLUSTER := camunda-platform-local

.PHONY: run test test-unit test-integration test-e2e lint generate-fixtures \
        demo deploy deploy-fast \
        k8s-logs k8s-status k8s-delete port-forward \
        build kind-load k8s-apply alertmanager-config \
        smoke smoke-% cycle-test cycle-test-fast load \
        import-dashboard check-metrics check-pod-metrics \
        help

##@ Desenvolvimento

run: ## Inicia o agente (porta 5001) com reload automático
	cd agent && ../.venv/bin/uvicorn webhook_receiver:app --host 0.0.0.0 \
		--port $$(python3 -c "import urllib.parse,os; u=os.environ.get('AGENT_PUBLIC_URL','http://localhost:5001'); print(urllib.parse.urlparse(u).port or 5001)") \
		--reload

test: ## Todos os testes com cobertura (Docker necessário para integration e e2e)
##  ↳ make test       — completo (unit → integration → e2e)
##  ↳ make test-unit  — rápido, sem Docker
	$(PYTEST) --cov --cov-report=term-missing -m "not integration and not e2e"
	$(PYTEST) -m integration -v
	$(PYTEST) -m e2e -v

test-unit: ## Unitários rápidos — sem Docker, para dev loop
	$(PYTEST) --cov --cov-report=term-missing -m "not integration and not e2e"

lint: ## Python (ruff) + Shell (shellcheck) + YAML (yamllint) — igual ao CI
##  ↳ make lint
	@echo "── Python — ruff ──────────────────────────────────────────────────"
	$(RUFF) check agent/
	@echo "── Shell — shellcheck (severity: warning) ─────────────────────────"
	$(SHELLCHECK) --severity=warning scripts/*.sh
	@echo "── YAML — yamllint (alerting/) ────────────────────────────────────"
	$(YAMLLINT) -c .yamllint.yml alerting/
	@echo ""
	@echo "  ✔  Lint OK"

generate-fixtures: ## Gera fixtures a partir de alerting/*.yaml (idempotente)
	$(PYTHON) scripts/generate-fixtures.py

##@ Demo local

demo: ## Itera todos os alertas com Ollama + agente locais
##  ↳ make demo  |  make demo DELAY=5
	./scripts/demo.sh

demo-%: ## Cenário específico
##  ↳ make demo-zeebe  |  make demo-backpressure  |  make demo-namespace  |  make demo-resolved
	./scripts/demo.sh --scenario $*

##@ Cluster Kind

deploy: ## Deploy + cycle-test completo (load real → alertas orgânicos)
##  ↳ make deploy  |  make deploy INTENSITY=high DURATION=30
	IMAGE_NAME=$(IMAGE_NAME) IMAGE_TAG=$(IMAGE_TAG) KIND_CLUSTER=$(KIND_CLUSTER) \
	  ./scripts/deploy.sh
	$(MAKE) cycle-test

deploy-fast: ## Deploy + validação do ciclo completo (sem load-generator)
##  ↳ make deploy-fast
	IMAGE_NAME=$(IMAGE_NAME) IMAGE_TAG=$(IMAGE_TAG) KIND_CLUSTER=$(KIND_CLUSTER) \
	  ./scripts/deploy.sh

##@ Operações K8s

k8s-logs: ## Acompanha os logs do agente em tempo real
	kubectl logs -n camunda -l app=camunda-aiops-agent -f --tail=100

k8s-status: ## Exibe status de pod, svc, pvc e cronjob
	kubectl get pod,svc,pvc,cronjob -n camunda -l app=camunda-aiops-agent

k8s-delete: ## Remove deployment/svc/cronjob  ⚠ PVC e Secret são mantidos
	kubectl delete deployment camunda-aiops-agent -n camunda --ignore-not-found
	kubectl delete service    camunda-aiops-agent -n camunda --ignore-not-found
	kubectl delete cronjob    camunda-aiops-data-cleanup    -n camunda --ignore-not-found

port-forward: ## Abre port-forwards para Prometheus:9090 e Grafana:3000
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
	kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana    3000:80   &

# ── Plumbing — chamáveis diretamente, mas não listados no help ────────────────

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

kind-load:
	kind load docker-image $(IMAGE_NAME):$(IMAGE_TAG) --name $(KIND_CLUSTER)

k8s-apply:
	kubectl apply -k deploy/

alertmanager-config:
	helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
	  -n monitoring --reuse-values -f deploy/alertmanager-values.yaml

smoke:
	./scripts/smoke.sh

smoke-%:
	./scripts/smoke.sh $*

cycle-test:
	./scripts/run-cycle-test.sh \
	  $(if $(CONTEXT),--context $(CONTEXT),) \
	  --intensity $(or $(INTENSITY),medium) \
	  --duration $(or $(DURATION),20)

cycle-test-fast:
	./scripts/run-cycle-test.sh $(if $(CONTEXT),--context $(CONTEXT),) --skip-load

load:
	./scripts/load-generator.sh --duration $(or $(DURATION),30) --intensity $(or $(INTENSITY),medium)

import-dashboard:
	./scripts/import-dashboard.sh

check-metrics:
	./scripts/check-metrics.sh

check-pod-metrics:
	./scripts/test-port-metrics.sh

test-integration:
	$(PYTEST) -m integration -v

test-e2e:
	$(PYTEST) -m e2e -v

# ── Ajuda ─────────────────────────────────────────────────────────────────────

help:
	@awk ' \
	  BEGIN { FS = ":.*##"; printf "\nUso: make \033[36m<target>\033[0m\n" } \
	  /^##@ / { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } \
	  /^[a-zA-Z0-9_%\/-]+:.*## / { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } \
	  /^##  / { printf "  %-20s \033[2m%s\033[0m\n", "", substr($$0, 4) } \
	' $(MAKEFILE_LIST)
	@echo ""
