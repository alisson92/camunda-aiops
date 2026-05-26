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

IMAGE_NAME   := camunda-aiops-agent
IMAGE_TAG    := latest
KIND_CLUSTER := camunda-platform-local

.PHONY: run test test-integration test-e2e smoke demo lint \
        port-forward check-metrics check-pod-metrics import-dashboard load \
        cycle-test cycle-test-fast generate-fixtures \
        build kind-load k8s-apply k8s-delete k8s-logs k8s-status deploy \
        help

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

demo: ## Demo completa: gera fixtures, itera todos os alertas, encerra tudo
	./scripts/demo.sh

demo-%: ## Demo de um cenário específico: make demo-zeebe | demo-namespace | demo-backpressure | demo-resolved
	./scripts/demo.sh --scenario $*

generate-fixtures: ## Gera fixtures Alertmanager a partir de alerting/*.yaml (idempotente)
	$(PYTHON) scripts/generate-fixtures.py

# ── Docker / Kubernetes ────────────────────────────────────────────────────────

deploy: ## Fluxo completo: build → kind-load → apply → aguarda pod pronto → health check
	@echo "[1/5] Build da imagem $(IMAGE_NAME):$(IMAGE_TAG)..."
	@docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .
	@echo "[2/5] Carregando imagem no Kind ($(KIND_CLUSTER))..."
	@kind load docker-image $(IMAGE_NAME):$(IMAGE_TAG) --name $(KIND_CLUSTER)
	@echo "[3/5] Verificando Secret..."
	@kubectl get secret camunda-aiops-secret -n camunda > /dev/null 2>&1 || \
	  (echo "ERRO: Secret 'camunda-aiops-secret' não encontrado." && \
	   echo "      cp deploy/secret.example.yaml deploy/secret.yaml" && \
	   echo "      # edite deploy/secret.yaml com os valores reais" && \
	   echo "      kubectl apply -f deploy/secret.yaml -n camunda" && exit 1)
	@echo "[3/5] Aplicando manifests (PVC, Deployment, Service, CronJob)..."
	@kubectl apply -k deploy/
	@echo "[4/5] Forçando rollout para garantir nova imagem..."
	@kubectl rollout restart deployment/camunda-aiops-agent -n camunda
	@kubectl rollout status  deployment/camunda-aiops-agent -n camunda --timeout=120s
	@echo "[5/5] Health check no NodePort..."
	@sleep 2
	@NODE_IP=$$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}') && \
	  curl -sf http://$$NODE_IP:30501/health | python3 -m json.tool && \
	  echo "Deploy concluído. Webhook disponível em http://$$NODE_IP:30501/webhook"

build: ## Build da imagem Docker do agente
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

kind-load: ## Carrega a imagem no cluster Kind (sem necessidade de registry externo)
	kind load docker-image $(IMAGE_NAME):$(IMAGE_TAG) --name $(KIND_CLUSTER)

k8s-apply: ## Aplica Deployment, Service, PVC e CronJob no cluster (cria o Secret antes)
	kubectl apply -k deploy/

k8s-delete: ## Remove Deployment, Service e CronJob (PVC e Secret são mantidos)
	kubectl delete deployment camunda-aiops-agent -n camunda --ignore-not-found
	kubectl delete service    camunda-aiops-agent -n camunda --ignore-not-found
	kubectl delete cronjob    camunda-aiops-data-cleanup -n camunda --ignore-not-found

k8s-logs: ## Acompanha os logs do agente em tempo real
	kubectl logs -n camunda -l app=camunda-aiops-agent -f --tail=100

k8s-status: ## Exibe status de Pod, Service, PVC e CronJob do agente
	kubectl get pod,svc,pvc,cronjob -n camunda -l app=camunda-aiops-agent

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
