# Changelog

Todas as mudanças notáveis deste projeto são documentadas aqui.
O formato segue [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versões seguem [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Added (deploy Kubernetes + persistência PVC)
- `Dockerfile` — build do agente: base `python:3.11-slim`, usuário não-root `aiops`, curated examples baked na imagem, `WORKDIR /app/agent`, healthcheck via `/health`, expõe porta 5001
- `.dockerignore` — exclui testes, docs, scripts, dashboards, alertas, `.venv`, runbooks gerados em runtime e secrets
- `deploy/pvc.yaml` — PersistentVolumeClaim `camunda-aiops-data` (1 Gi, `storageClassName: standard` para Kind; EKS: `gp2`/`gp3`)
- `deploy/deployment.yaml` — Deployment com volumeMount em `/app/data/knowledge/runbooks` (apenas runbooks gerados no PVC, exemplos curados ficam na imagem); `imagePullPolicy: Never` para Kind; probes readiness/liveness em `/health`; resources definidos; comentário para `hostAliases` (Ollama no host WSL2)
- `deploy/service.yaml` — NodePort 30501 para acesso externo ao Kind sem Ingress (EKS: migrar para ClusterIP + ALB Ingress)
- `deploy/cronjob.yaml` — CronJob semanal (domingo 02h) que remove runbooks com mais de 30 dias do PVC; `busybox:1.36`, `concurrencyPolicy: Forbid`
- `deploy/secret.yaml` — template comentado com todas as variáveis sensíveis; não contém valores reais
- `deploy/kustomization.yaml` — `kubectl apply -k deploy/` aplica PVC, Deployment, Service e CronJob em uma operação
- Makefile: targets `build`, `kind-load`, `k8s-apply`, `k8s-delete`, `k8s-logs`, `k8s-status`; variáveis `IMAGE_NAME`, `IMAGE_TAG`, `KIND_CLUSTER`

### Added
- `agent/webhook_receiver.py`: `_notify_direct()` — path de notificação direta para alertas sem `agentia=true`; monta card Teams com as informações da própria regra (labels/annotations) sem chamar LLM, runbook ou RAG
- `agent/metrics.py`: contador `aiops_alerts_direct_total` — rastreia notificações diretas (sem LLM) separadamente das analisadas pelo agente

### Changed
- Filtro de alertas migrado de `ALERT_FILTER_KEYWORDS` (heurística por nome) para label `agentia: "true"` nas PrometheusRules — controle explícito e por alerta de quais serão processados pelo agente; remover a label de um alerta específico desabilita o processamento sem alterar código ou variáveis de ambiente
- `agent/config.py`: remove `ALERT_FILTER_KEYWORDS` — configuração não é mais necessária
- `agent/webhook_receiver.py`: loop do webhook reestruturado — dedup aplicado a todos os alertas antes da branch; `agentia=true` → `_process_alert` (LLM); `agentia!=true` → `_notify_direct` (sem LLM); todos os alertas são notificados no Teams
- `agent/tools.py`: `get_alert_rules()` filtra regras por `labels.agentia == "true"` em vez de keyword no nome
- `.env.example`: remove seção `ALERT_FILTER_KEYWORDS`
- `scripts/demo.sh`: remove `check_filter_keywords()` e todas as referências à variável removida
- `alerting/*.yaml`: `agentia: "true"` adicionado em todos os 23 alertas (camunda-forecasting, camunda-latency, camunda-storage, elasticsearch, kubernetes-camunda-ns, kubernetes-node, kubernetes-pod)
- `tests/fixtures/*.json`: todos os 24 fixtures atualizados com `agentia: "true"` nos labels
- `tests/unit/test_webhook_receiver.py`: payloads atualizados; `test_non_camunda_alert_is_filtered` renomeado para `test_alert_without_agentia_label_is_filtered`
- `tests/unit/test_config.py`: `TestAlertFilterKeywords` substituído por `TestAgentiaLabel`
- `tests/unit/test_tools.py`: `TestGetAlertRules` atualizado para usar `agentia: "true"` nas regras esperadas
- 223 testes, 100% cobertura (636 statements)

### Fixed (pós 0.14.0 — correções demo e dashboard)
- `scripts/demo.sh`: `ensure_agent()` reutilizava agente antigo sem reiniciar — alertas `Kube*` e `Elasticsearch*` continuavam filtrados porque o processo rodava com código pré-fix; demo agora sempre reinicia o agente para garantir código e configuração atuais
- `scripts/demo.sh`: verificação `http_code == "200"` não aceitava `202` — todos os cenários retornavam "erro no webhook" com o agente atualizado; corrigido para aceitar qualquer `2xx`
- `scripts/demo.sh`: parsing da resposta lia campo `analyses` (formato síncrono antigo) — novo formato usa `queued`; todos os alertas exibiam "(alerta filtrado)" mesmo quando processados; reestruturado para extrair `queued`/`message` com chamadas Python simples, eliminando mix perigoso de `${var_bash}` dentro de f-strings Python que causava `syntax error: operand expected`
- `dashboards/camunda-aiops-agent.json`: painéis "Notificações com Falha" e "Alertas Filtrados" exibiam "No data" quando não havia eventos — adicionado `or vector(0)` para mostrar `0` no estado saudável

### Added (pós 0.14.0)
- `docs/analise-llm-local-desempenho.md` — análise do gargalo de processamento identificado em demo com 23 alertas (~35 min); decomposição das 3 chamadas LLM por alerta; tabela de modelos locais gratuitos candidatos (`qwen2.5:3b`, `phi4-mini`, `llama3.2:3b`, `gemma3:4b`, `mistral:7b`); template de resultado para testes comparativos; critérios objetivos de qualidade; levers de otimização futuros (paralelismo Ollama, Celery, redução de chamadas)
- `docs/comparativo-solucoes-aiops-comunidade.md` — análise comparativa entre camunda-aiops e as principais soluções AIOps da comunidade (HolmesGPT CNCF, K8sGPT, Robusta, Grafana LLM App); tabela de capacidades por ferramenta; diagrama de camadas complementares; cenário de coexistência com `kube-prometheus-stack`; caminho recomendado de adoção; explica o nicho único do camunda-aiops (forecasting Camunda 8 + Ollama nativo + RAG time)
- `docs/melhorias-pos-demo.md` — consolidação dos pontos de melhoria levantados pelo time após a demo: (1) persistência de dados com PVC/SQLite/S3 e política de retenção; (2) acurácia do forecasting preditivo vs. alerta real; (3) filtro por label `agentia: true` em vez de keywords; (4) ampliação das métricas internas (timeouts, queries Prometheus, projeções); tabela de priorização com complexidade e impacto por item
- Remove `docs/persistencia-dados-agente.md` — conteúdo absorvido pelo `melhorias-pos-demo.md`

---

## [0.14.0] — 2026-05-26

### Added (Etapa 13 — Fixtures dinâmicos, deduplicação e webhook assíncrono)

**Geração automática de fixtures**
- `scripts/generate-fixtures.py` — lê todos os `alerting/*.yaml` e gera `tests/fixtures/<kebab>-alert.json` para cada alerta; idempotente por nome de arquivo; resolve expressões Go template (`{{ $labels.xxx }}`, `{{ $value | humanizePercentage }}`) com valores padrão por componente; extrai labels referenciados nas annotations e os injeta no payload gerado
- `Makefile`: target `generate-fixtures` — `python scripts/generate-fixtures.py`
- `pyproject.toml`: dependência de dev `pyyaml>=6.0.0` para leitura dos YAMLs do Alertmanager
- 20 novos fixtures gerados automaticamente para todos os alertas Kubernetes e Elasticsearch

**Deduplicação por fingerprint**
- `agent/webhook_receiver.py`: `_dedup_cache: dict[str, datetime]` — cache module-level de fingerprints processados; `_make_fingerprint(alert)` usa campo nativo do Alertmanager ou MD5(alertname+labels); `_is_duplicate(fingerprint, status)` — janela TTL configurável, alertas `resolved` sempre passam (nunca deduplicados); entradas expiradas removidas a cada chamada (sem vazamento de memória)
- `agent/config.py`: `DEDUP_TTL_SECONDS: int` — padrão `300` (5 min), configurável via env var
- `agent/metrics.py`: `ALERTS_DEDUPLICATED` — novo Counter `aiops_alerts_deduplicated_total` para observabilidade da deduplicação
- `tests/unit/test_webhook_receiver.py`: classe `TestDeduplication` com 7 novos testes cobrindo TTL, bypass em resolved, expiração de entradas, fingerprint nativo vs derivado

**Webhook assíncrono (202 Accepted)**
- `agent/webhook_receiver.py`: extrai lógica de análise para `_process_alert(alert, alert_id)` — chamado via `BackgroundTasks`; endpoint retorna `202 Accepted` com `{"queued": N}` imediatamente após filtro + dedup; Alertmanager nunca bloqueia aguardando o LLM
- Contrato de resposta: `{"message": "N alerta(s) enfileirado(s)", "queued": N}` com status `202`

### Changed (Etapa 13)

**Fixtures**
- `tests/fixtures/zeebe-memory-alert.json` → `zeebe-memory-predicted-high-alert.json` (convenção kebab-case do alertname)
- `tests/fixtures/zeebe-backpressure-alert.json` → `zeebe-backpressure-growing-alert.json`
- `tests/fixtures/namespace-memory-alert.json` → `camunda-namespace-memory-pressure-alert.json`
- `tests/fixtures/zeebe-resolved.json` → `zeebe-memory-predicted-high-resolved.json`
- `tests/unit/test_alert_fixtures.py`: `ALERT_FIXTURES` agora dinâmico — `glob("*.json")` em vez de lista hardcoded
- `scripts/run-cycle-test.sh`: referências atualizadas para novos nomes de fixture
- `scripts/demo.sh`: `ensure_fixtures()` invoca `generate-fixtures.py` antes da demo; modo `all` descobre fixtures dinamicamente via `find ... -name "*-alert.json" | sort`

**Filtro de alertas**
- `agent/config.py`: `ALERT_FILTER_KEYWORDS` default `"Zeebe,Camunda"` → `"Zeebe,Camunda,Kube,Elasticsearch"` — alertas Kubernetes e Elasticsearch agora processados sem alteração de configuração

**Testes**
- `tests/unit/test_webhook_receiver.py`: status `200` → `202` em todos os testes de webhook; campo `analyses` → `queued`; fixture `client` inclui `patch.dict("webhook_receiver._dedup_cache", {}, clear=True)` para isolamento entre testes
- `tests/e2e/test_alert_cycle.py`: status `200` → `202`; campo `analyses` → `queued`
- `tests/e2e/conftest.py`: `e2e_client` fixture envolve yield em `patch.dict("webhook_receiver._dedup_cache", {}, clear=True)` — evita deduplicação cruzada entre testes E2E
- `pyproject.toml`: versão `0.13.0` → `0.14.0`
- `CHANGELOG.md`: `[Unreleased]` convertido em `[0.14.0]`

### Fixed (Etapa 13)
- Alertas Kubernetes e Elasticsearch eram silenciosamente filtrados porque `ALERT_FILTER_KEYWORDS` não incluía `Kube` nem `Elasticsearch` no default
- Expressões Go template (`{{ $labels.persistentvolumeclaim }}`) geradas literalmente nos fixtures — `generate-fixtures.py` agora resolve antes de gravar
- Cache de deduplicação `_dedup_cache` persistia entre testes unitários e E2E na mesma sessão pytest, causando `IndexError` no terceiro teste E2E — corrigido com `patch.dict(..., clear=True)` nas fixtures de teste

---

## [0.13.0] — 2026-05-25

### Added (Revisão G — Documentação final e consistência)
- `docs/revisao-G-documentacao-final.md` — laudo desta revisão

### Changed (Revisão G)
- `README.md`: árvore `alerting/` expandida (3 → 7 arquivos); `dashboards/` com `camunda-aiops-agent.json`; seção "Alertas preditivos" expandida para cobrir todos os 7 arquivos; contagem de testes `218` → `219`; per-file counts corrigidos (`test_webhook_receiver` 36→37, `test_teams_notifier_unit` 32→34); tabela de suítes `159` → `219`
- `CLAUDE.md`: contagem de testes `88` → `219`; seção de arquitetura reflete `alerting/` e segundo dashboard
- `pyproject.toml`: versão `0.12.0` → `0.13.0`
- `CHANGELOG.md`: `[Unreleased]` convertido em `[0.13.0]`

### Fixed (Revisão G)
- `agent/webhook_receiver.py`: loop de startup extraído para `_reload_runbooks_from_kb()` — corpo do loop era letra morta em CI (ambiente limpo, sem runbooks em disco); cobertura volta a 100% (219 testes, 605 statements)
- `alerting/*.yaml`: `namespace=~"jorn.*"` → `namespace=~"camunda.*|jorn.*"` nos 4 arquivos migrados do Grafana — alertas agora capuram pods do Kind local (`namespace=camunda`) e do ambiente de hml dos colegas

---

### Added (Revisão F — Migração de alertas Grafana para PrometheusRule IaC)
- `alerting/elasticsearch-rules.yaml` — 3 regras: `ElasticsearchClusterHealthCritical`, `ElasticsearchClusterHealthWarning` (severidade dinâmica dividida em dois alertas), `ElasticsearchUnassignedShards`
- `alerting/kubernetes-pod-rules.yaml` — 10 regras: `KubePodNotReady`, `KubeStatefulSetReplicasMismatch`, `KubeDeploymentReplicasMismatch`, `KubePodHighMemory`/`Critical`, `KubePodCrashLooping`, `KubePodHighCPU`/`Critical`, `KubePodMultipleRestarts`, `KubePodOOMKilled`
- `alerting/kubernetes-camunda-ns-rules.yaml` — 3 regras (todas com `isPaused` no Grafana): `KubePersistentVolumeErrors`, `KubeStatefulSetGenerationMismatch`, `KubeStatefulSetUpdateNotRolledOut`
- `alerting/kubernetes-node-rules.yaml` — 2 regras: `KubeNodeConditionAffectedPods`, `KubeNewNode` (isPaused)
- Todas as 18 regras usam `runbook_url: http://172.18.0.1:5001/runbook/by-alert/{AlertName}` — sem URLs externas (compliance/segurança)

### Changed (Revisão F — Migração Grafana)
- `.env.example`: `ALERT_FILTER_KEYWORDS` expandido para `Zeebe,Camunda,Kube,Elasticsearch` — cobre todos os novos alertas sem exigir alteração de código

### Added (runbook_url production-ready — endpoint by-alert)
- `GET /runbook/by-alert/{alert_name}` — endpoint estático por alertname que sempre serve o runbook mais recente; permite que PrometheusRules usem uma URL fixa sem depender do ID dinâmico de cada ocorrência
- `_latest_runbook_by_name` dict em `webhook_receiver.py` — índice `alertname → alert_id` mantido em sincronia a cada novo runbook gerado e recarregado da KB no startup

### Changed (runbook_url production-ready)
- `alerting/camunda-forecasting-rules.yaml`, `camunda-latency-rules.yaml`, `camunda-storage-rules.yaml`: todos os `runbook_url` migrados de URLs GitHub externas para `http://172.18.0.1:5001/runbook/by-alert/{AlertName}` — sem dependência de URLs externas (compliance/segurança)
- `README.md`: contagem de testes atualizada (213 → 218)

### Added (Revisão F — Alerting strategy e cobertura de PrometheusRules)
- `alerting/camunda-latency-rules.yaml` — novo PrometheusRule: `ZeebeGatewayLatencyHigh` (histogram_quantile p99 > 2s, for 5m, severity warning) — cobre o único ponto de entrada gRPC/REST sem alerta
- `alerting/camunda-storage-rules.yaml` — novo PrometheusRule: `ZeebePVCUsagePredictedFull` (predict_linear sobre kubelet_volume_stats, horizonte 1h, for 10m, severity critical) — cobre disco RocksDB que causa parada imediata de processamento BPMN se cheio
- `docs/revisao-F-alerting.md` — laudo completo desta revisão

### Changed (Revisão F)
- `alerting/camunda-forecasting-rules.yaml`: label `component` adicionada em todos os alertas (`zeebe`, `zeebe-gateway`, `camunda`); `runbook_url` atualizado por alerta (ZeebeMemoryPredictedHigh e ZeebeBackpressureGrowing apontam para exemplos KB curados)
- `docs/README.md`: entrada da Revisão F adicionada à tabela de revisões

### Added (Revisão E — AIOps best practices)
- `agent/metrics.py`: `LLM_ROUNDS_USED` — novo Histogram `aiops_llm_rounds_used` (buckets 1–6) para instrumentar quantas rodadas de tool use cada análise consome
- `agent/knowledge_base.py`: método público `get_runbooks()` — retorna apenas documentos gerados (`source="generated"`), usado para recarregar o store de runbooks no startup
- `docs/revisao-E-aiops-best-practices.md` — laudo completo desta revisão (diagnóstico + decisões de descarte)

### Changed (Revisão E)
- `agent/reactive_agent.py`: parâmetro `alert_id: str = ""` em `run_agent` — propagado em todas as linhas de log do ciclo de análise; `LLM_ROUNDS_USED.observe(round_n + 1)` registrado ao concluir
- `agent/webhook_receiver.py`: correlation ID gerado por alerta (`uuid.uuid4().hex[:8]`) e propagado nos logs; runbooks recarregados da KB no startup; `/health` retorna `knowledge_base.documents`
- `README.md`: contagem de testes unitários atualizada (198 → 213) com detalhes por arquivo
- `docs/README.md`: entrada da Revisão E adicionada à tabela de revisões

### Fixed (Revisão E)
- `webhook_receiver.py`: runbooks gerados em ciclos anteriores agora são recarregados no startup a partir da KB — links "📖 Runbook" no Teams não retornam mais 404 após restart do agente

### Added (Revisão D — CONTRIBUTING.md e padrões do projeto)
- `CONTRIBUTING.md` — guia centralizado de padrões: fluxo de contribuição, Conventional Commits, regras de código (ruff), requisitos de teste (100% cobertura), checklist para nova etapa, ADR format, tabela do CI e o que nunca commitar
- `docs/revisao-D-contributing.md` — laudo completo desta revisão

### Changed (Revisão D)
- `docs/README.md` — entrada da Revisão D adicionada à tabela de revisões de qualidade

### Added (Revisão C — Organização e estrutura do repositório)
- `docs/README.md` — índice de navegação da pasta docs/ (etapas, revisões, fixes, ADR log)
- `data/knowledge/examples/README.md` — instruções para adicionar exemplos few-shot
- `docs/revisao-C-organizacao-estrutura.md` — laudo completo desta revisão
- `pyproject.toml`: campos PEP 621 — `readme`, `authors`, `[project.urls]`, `keywords`; versão `0.1.0` → `0.12.0`
- `pyproject.toml`: `[tool.ruff.lint]` com `select = ["E","W","F","I","UP"]`

### Changed (Revisão C)
- `.github/workflows/ci.yml` — actions revertidas para `@v6` após mudança incorreta para `@v4`/`@v5`
- `scripts/check-metrics.sh` — header atualizado: nome e comandos de uso corrigidos (ainda referenciava `01-check-metrics.sh`)
- `prompts/GUIDELINES.md` — estrutura da pasta atualizada: v1 depreciado, v2 listado como versão em uso
- `agent/config.py`, `agent/tools.py`, `agent/runbook_generator.py`, `agent/webhook_receiver.py` — 9 violações lint auto-corrigidas pelo ruff (`I001` import order, `UP017` `datetime.UTC`)

### Removed (Revisão C)
- `data/knowledge/runbooks/zeebe-memory-predicted-high-aabbccdd.md` — placeholder de runtime removido novamente (recriado por execução de demo anterior)

### Added (Revisão B — Hardcoded e configurabilidade)
- `config.py`: `ALERT_FILTER_KEYWORDS` — nova variável de ambiente (padrão `Zeebe,Camunda`); define quais alertas o agente processa sem exigir edição de código
- `.env.example`: entrada `ALERT_FILTER_KEYWORDS` com documentação e exemplo de uso
- `docs/revisao-B-hardcoded-configurabilidade.md` — laudo completo com classificação de todos os valores hardcoded e justificativa de cada decisão
- `tests/unit/test_config.py`: 4 novos testes para `ALERT_FILTER_KEYWORDS` (default, custom, espaços, vazio)

### Changed (Revisão B)
- `agent/webhook_receiver.py` — filtro de alertas usa `ALERT_FILTER_KEYWORDS` (era `("Zeebe", "Camunda")` hardcoded)
- `agent/tools.py` — filtro de `get_alert_rules` usa `ALERT_FILTER_KEYWORDS` (era hardcoded)
- `agent/runbook_generator.py` — fallback de runbook usa `GRAFANA_URL` de `config.py` (era `http://localhost:3000` hardcoded)
- `Makefile`: target `run` deriva a porta de `AGENT_PUBLIC_URL` (era porta `5001` hardcoded)

### Added (Revisão A — Limpeza e organização do repositório)
- `docs/revisao-A-limpeza-repositorio.md` — documento desta revisão: o que foi feito e por quê
- `docs/etapa-6-ciclo-completo.md` — documentação da Etapa 6 (`run-cycle-test.sh`), faltava desde a implementação
- `docs/etapa-12-rag-conhecimento.md` — documentação da Etapa 12 (RAG + few-shot), faltava desde a implementação
- `tests/smoke/` — novo subdiretório para smoke tests; `tests/smoke/__init__.py` criado
- `Makefile`: target `check-pod-metrics` → `scripts/test-port-metrics.sh` (script existia sem target)

### Changed (Revisão A)
- `tests/smoke/test_teams_notifier.py` — movido de `tests/test_teams_notifier.py` para alinhar com estrutura `unit/` / `integration/` / `e2e/`
- `scripts/smoke.sh` — caminho do smoke test atualizado para `tests/smoke/test_teams_notifier.py`
- `docs/etapa-7-qualidade-ci.md` — renomeado de `etapa-5-github-actions.md` (numeração estava errada: CI é Etapa 7, não 5)
- `docs/etapa-3-agente-reativo-claude-api.md` — nota histórica adicionada: agente migrado para Ollama na Etapa 4
- `docs/projeto-evolucao.md` — cabeçalho clarificando papel de ADR log vs CHANGELOG
- `prompts/system-prompt-v1.md` — notice de deprecação adicionado; direciona para v2
- `Makefile`: descrição de `check-metrics` atualizada para distinguir de `check-pod-metrics`
- `README.md` — árvore de diretórios atualizada: `tests/smoke/`, contagem de testes (198), `system-prompt-v2.md` listado, `demo.sh` e `smoke.sh` incluídos em `scripts/`

### Removed (Revisão A)
- `data/knowledge/runbooks/zeebe-memory-predicted-high-aabbccdd.md` — artefato de teste manual com conteúdo placeholder removido

### Added (Etapa 12 — Few-shot + RAG)
- `agent/knowledge_base.py` — `KnowledgeBase` com `add_document`, `search(alert_name, k)`, persistência de runbooks em `data/knowledge/runbooks/` e carregamento de exemplos curados de `data/knowledge/examples/`; scoring por match exato de alertname (+10) e sobreposição de tokens; sem dependência externa
- `data/knowledge/examples/zeebe-backpressure-growing.md` — exemplo curado de análise ideal para alerta critical de backpressure (few-shot)
- `data/knowledge/examples/zeebe-memory-predicted-high.md` — exemplo curado de análise ideal para alerta warning de heap JVM (few-shot)
- `.gitignore`: `data/knowledge/runbooks/` ignorado (populado em runtime)

### Changed (Etapa 12)
- `agent/prompts.py` — `build_user_message` aceita `context_docs: list[Document] | None`; injeta seção "Contexto relevante — histórico do time" antes do alerta quando documentos são encontrados
- `agent/reactive_agent.py` — `run_agent` aceita `context_docs: list | None` e repassa para `build_user_message`
- `agent/webhook_receiver.py` — inicializa `_kb = KnowledgeBase()` na startup; busca contexto (`_kb.search`) antes de `run_agent`; persiste runbook no KB após geração via `_kb.add_document`
- `tests/unit/test_reactive_agent.py` — 7 testes novos: `build_user_message` com e sem `context_docs` (curated/generated, vazio, None, doc sem alert_name)
- `tests/unit/test_knowledge_base.py` — novo arquivo: 33 testes cobrindo init, load, add, search, scoring, persistência e reload

### Added (Etapa 11 — Runbook Generation)
- `agent/runbook_generator.py` — módulo de geração de runbooks: `generate_runbook()` (segunda chamada LLM sem tool use), `_make_alert_id()` (slug URL-safe + MD5[:8]), `_infer_component()`, `_fallback_runbook()` (gerado localmente se LLM falhar), `_markdown_to_html()` (renderer Markdown→HTML sem dependência externa), `render_runbook_html()` (página HTML completa estilizada)
- `GET /runbook/{alert_id}` em `webhook_receiver.py` — serve runbook em HTML; `alert_id` retornado no campo `runbook_id` da resposta do `/webhook`
- `_runbooks: dict[str, tuple[str, str]]` — store em memória (`alert_id → (alert_name, runbook_md)`)
- Botão "📖 Runbook" no card Teams agora aponta para URL do agente (`{AGENT_PUBLIC_URL}/runbook/{alert_id}`) gerada automaticamente para alertas `firing`
- `tests/unit/test_runbook_generator.py` — 42 testes: `_make_alert_id`, `_infer_component`, `_fallback_runbook`, `generate_runbook` (sucesso, falha LLM, conteúdo vazio), `_markdown_to_html` (h1/h2/h3, bold, inline code, fenced code, ul, ol, parágrafos, escape HTML), `render_runbook_html`

### Changed (Etapa 11)
- `agent/webhook_receiver.py` — integra `generate_runbook` após `run_agent` (apenas alertas `firing`); armazena runbook no store; passa `runbook_url` para `send_alert_to_teams`; resposta do `/webhook` inclui campo `runbook_id`; importa `AGENT_PUBLIC_URL` de config
- `agent/teams_notifier.py` — `send_alert_to_teams` recebe novo parâmetro `runbook_url: str = ""`; URL gerada tem prioridade sobre `runbook_url` das annotations
- `tests/unit/test_webhook_receiver.py` — fixture atualizada com `mock_runbook`; 6 testes novos: `/runbook/{alert_id}` (found/404/HTML/alert_name), `generate_runbook` chamado para firing e não chamado para resolved, `runbook_id` na resposta

### Added
- `agent/metrics.py` — ponto único de definição de métricas Prometheus: `aiops_webhooks_total`, `aiops_alerts_processed_total`, `aiops_alerts_filtered_total`, `aiops_analysis_duration_seconds`, `aiops_llm_tool_calls_total`, `aiops_teams_notifications_total`
- `GET /metrics` em `webhook_receiver.py` — endpoint Prometheus text/plain via `generate_latest()`
- `dashboards/camunda-aiops-agent.json` — dashboard Grafana com 3 seções: Webhooks & Alertas, Desempenho da Análise (p50/p90/p99), Notificações Teams
- `tests/unit/test_metrics.py` — 9 testes de definição e registro das métricas
- `docs/etapa-10-observabilidade-agente.md` — documentação da etapa: problema, solução, decisões técnicas, instruções de import do dashboard
- `pyproject.toml` — dependência `prometheus-client>=0.20.0,<1.0.0`

### Changed
- `agent/webhook_receiver.py` — instrumentado com `WEBHOOKS_RECEIVED`, `ALERTS_FILTERED`, `ALERTS_PROCESSED`, `ANALYSIS_DURATION.time()`, `TEAMS_NOTIFICATIONS`; adicionado endpoint `GET /metrics`
- `agent/reactive_agent.py` — instrumentado com `LLM_TOOL_CALLS` por nome de ferramenta
- `tests/unit/test_webhook_receiver.py` — adicionados 4 testes: `/metrics` (status, content-type, métricas presentes) e branch `success=false` de notificação

### Added
- `prompts/system-prompt-v2.md` — adiciona campo URGÊNCIA (Imediata/Alta/Moderada) ao formato firing; formato dedicado para `resolved` (RESOLUÇÃO/CONFIRMAÇÃO/PRÓXIMO_PASSO); contexto dos 6 componentes Camunda 8; dois exemplos de output (critical + resolved)
- `docs/etapa-9-system-prompt-v2.md` — documentação da etapa: problema, decisões, comparação v1 vs v2, rollback

### Changed
- `agent/config.py` — `_BRTFormatter` força logs em horário de Brasília (UTC-3); `setup_logging` usa handler com formatter explícito em vez de `basicConfig` com `format=`
- `tests/unit/test_config.py` — 2 testes para `_BRTFormatter`: offset UTC-3 e formato padrão `YYYY-MM-DD HH:MM:SS`
- `agent/prompts.py` — aponta para `system-prompt-v2.md` (era v1)
- `prompts/GUIDELINES.md` — atualiza comando de teste para `make demo-backpressure` e `make demo-resolved`; registra v2 no histórico de versões
- `scripts/demo.sh` — injeta timestamp atual (UTC) no payload antes de enviar — corrige horário exibido no card Teams (antes mostrava hora estática do fixture convertida para BRT): inicia Ollama e o agente automaticamente se necessário, injeta os 4 cenários, encerra tudo via `trap`; suporta `--scenario`, `--dry-run`, `--list`, `--delay`, `--webhook-url`
- `tests/fixtures/zeebe-backpressure-alert.json` — payload `ZeebeBackpressureGrowing` (critical) para ciclo de demo
- `tests/fixtures/zeebe-resolved.json` — payload `ZeebeMemoryPredictedHigh` (resolved) para demonstrar lifecycle completo
- `Makefile` targets `demo` e `demo-%` (demo-zeebe, demo-namespace, demo-backpressure, demo-resolved)
- `docs/etapa-8-demo-mode.md` — documentação da etapa: problema, solução, decisões técnicas e roteiro de uso
- `CLAUDE.md` — regra de documentação obrigatória ao concluir etapas; roadmap numerado; roteiro da demo ao time
- `README.md` — nota explicando a diferença entre `demo.sh` (valida o agente, sem Kind) e `run-cycle-test.sh` (valida a pipeline K8s, requer Kind)
- `tests/e2e/test_alert_cycle.py` — 3 testes E2E do ciclo completo: webhook → agente → Prometheus real → LLM mock HTTP → Teams mock HTTP
- `tests/e2e/conftest.py` — fixtures E2E: Prometheus (Testcontainers) + servidor HTTP mock unificado (pytest-httpserver)
- `tests/integration/test_tools_integration.py` — 7 testes de integração de `tools.py` contra Prometheus real (Testcontainers)
- `tests/integration/conftest.py` — fixture Prometheus com espera pelo primeiro self-scrape
- `tests/test_webhook_receiver.py` — 22 testes unitários para `/health`, `/webhook`, `/silence` (FastAPI TestClient)
- `tests/test_reactive_agent.py` — 12 testes do loop agentic com tool use (mock OpenAI client)
- `tests/test_tools.py` — 15 testes de queries ao Prometheus (mock httpx)
- `tests/test_teams_notifier_unit.py` — 19 testes de helpers puros e montagem do Adaptive Card
- `scripts/run-cycle-test.sh` — ciclo completo automatizado: port-forwards → agente → carga → alerta → cleanup
- `Makefile` targets `cycle-test`, `cycle-test-fast`, `test-integration`, `test-e2e`
- `.github/workflows/ci.yml` jobs `integration` (needs: python) e `e2e` (needs: integration)
- `.github/workflows/ci.yml` job `shell-lint` — ShellCheck com `severity=warning` via `ludeeus/action-shellcheck@2.0.0`
- `.gitignore` entradas `.coverage` e `htmlcov/`
- `pyproject.toml` — dependências `pytest-cov>=5.0.0`, `testcontainers>=4.7.0`, `pytest-httpserver>=1.0.0`; `fail_under = 100`; markers `integration` e `e2e`
- `agent/config.py` — ponto único de configuração; carrega `.env` e expõe constantes tipadas
- `agent/__init__.py` — torna `agent/` um pacote Python formal
- `tests/fixtures/` — fixtures de payload do Alertmanager (movidas de `agent/test-fixtures/`)
- `tests/test_teams_notifier.py` — smoke test de notificações Teams (movido de `agent/`)
- `pyproject.toml` — substitui `requirements.txt`; define metadados, deps e config do pytest
- `Makefile` — task runner com targets `run`, `test`, `smoke`, `lint`
- `.env.example` — template público de variáveis de ambiente
- `CHANGELOG.md` — este arquivo
- `docs/projeto-evolucao.md` — diário de decisões técnicas do projeto
- `prompts/GUIDELINES.md` — diretrizes de versionamento de prompts
- `prompts/system-prompt-v1.md` — system prompt base do agente AIOps

### Changed
- `Makefile` — `.DEFAULT_GOAL := help`; `make` sem argumentos exibe targets disponíveis
- `.github/workflows/ci.yml` — step `pytest` atualizado para `pytest --cov --cov-report=term-missing`
- `agent/tools.py` — adicionada `_resolve_ts()`: converte `now`, `now-30m`, `now-1h` para Unix timestamp antes de chamar `/api/v1/query_range` (bug: Prometheus rejeita timestamps relativos neste endpoint)
- `agent/webhook_receiver.py` — `datetime.utcnow()` substituído por `datetime.now(timezone.utc)` (deprecation fix)
- `scripts/run-cycle-test.sh` — `DEFAULT_KIND_CONTEXT="kind-camunda-platform-local"` hardcoded; falha explícita com diagnóstico se o contexto não existir
- `scripts/load-generator.sh` — removidas variáveis não utilizadas (`ZEEBE_REST_URL`, `HTTP_PID_1/2`, `SCALE_PID`)
- `scripts/check-metrics.sh` — variável `description` usada na saída de log (SC2034)
- `scripts/test-port-metrics.sh` — adicionado shebang `#!/usr/bin/env bash` (SC2148)
- `agent/tools.py` — `PROMETHEUS_URL` agora vem de `config.py` (era hardcoded)
- `agent/reactive_agent.py` — carregamento de `.env` centralizado em `config.py`; logging estruturado
- `agent/teams_notifier.py` — variáveis de ambiente via `config.py`; logging estruturado
- `agent/webhook_receiver.py` — `ALERTMANAGER_URL` via `config.py`; logging estruturado
- `agent/prompts.py` — loader limpo sem lógica de configuração
- Scripts renomeados: `01-check-metrics.sh` → `check-metrics.sh`, `02-load-generator.sh` → `load-generator.sh`, `03-import-dashboard.sh` → `import-dashboard.sh`

### Removed
- `requirements.txt` — substituído por `pyproject.toml`
- `agent/test-fixtures/` — movido para `tests/fixtures/`
- `agent/test/` — screenshots movidos para `tests/fixtures/`
- `agent/test-teams-notification.py` — renomeado para `tests/test_teams_notifier.py`

---

## [0.4.0] — 2026-05-22

### Added
- Notificação Microsoft Teams via Adaptive Card v1.2
- Botões de ação no card: "Ver análise", "Dashboard", "Runbook", "Silence 1h"
- Endpoint `GET /silence` no webhook receiver para criar silences via Alertmanager API
- Suporte a 4 severidades com cores e emojis distintos: critical 🚨, warning ⚠️, info ℹ️, resolved ✅

## [0.3.0] — 2026-05-22

### Changed
- Migração do LLM de Anthropic Cloud para Ollama local (`qwen2.5:7b`)
- Zero dependência externa — ciclo AIOps 100% air-gapped
- SDK migrado: `anthropic` → `openai` (compat Ollama)

## [0.2.0] — 2026-05-21

### Added
- Agente reativo com Claude API + webhook Alertmanager (Etapa 3)
- Grafana MCP Server conectado ao Claude Code (Etapa 2)
- Fix sustentável do Alertmanager via `helm upgrade` (IP: `172.18.0.1`)

## [0.1.0] — 2026-05-20

### Added
- PrometheusRules preditivas para Zeebe/Camunda (Etapa 1)
- Dashboard de forecasting com 11 painéis (PromQL: `predict_linear`, `deriv`, `avg_over_time`)
- Scripts de setup: `check-metrics`, `load-generator`, `import-dashboard`
- Publicação no GitHub (repositório privado)
