# Diagramas — camunda-aiops

Diagramas arquiteturais do projeto em formato [Mermaid](https://mermaid.js.org/).  
Renderizam automaticamente no GitHub, GitLab e na maioria dos visualizadores Markdown.

---

| Diagrama | O que mostra |
|---|---|
| [arquitetura-componentes.md](arquitetura-componentes.md) | Visão geral — todos os componentes e suas conexões |
| [fluxo-alerta-completo.md](fluxo-alerta-completo.md) | Ciclo completo: do `predict_linear` no Prometheus até o card no Teams |
| [react-loop-agente.md](react-loop-agente.md) | Raciocínio interno do agente — como o LLM decide o que consultar e como analisa |
| [fluxo-webhook-assincrono.md](fluxo-webhook-assincrono.md) | Webhook assíncrono — por que o Alertmanager não trava e o que acontece em background |
