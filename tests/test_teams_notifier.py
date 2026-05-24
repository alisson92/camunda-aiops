"""
Smoke test — valida a notificação Teams com os 4 cenários de severidade.

Este script envia alertas reais para o canal Teams configurado em agent/.env.
NÃO é executado automaticamente pelo pytest (não há funções test_*).
Use via Makefile:
  make smoke              # envia todos os cenários
  make smoke-critical     # envia só o critical
  make smoke-warning
  make smoke-info
  make smoke-resolved

Ou diretamente:
  PYTHONPATH=agent python3 tests/test_teams_notifier.py [critical|warning|info|resolved]
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

# Garante que agent/ está no path quando executado diretamente
sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

from config import setup_logging
from teams_notifier import send_alert_to_teams

setup_logging()

_ANALYSIS = """**Causa raiz identificada:**
A métrica `jvm_memory_used_bytes` para a G1 Old Gen do pod `camunda-zeebe-0` está em 93.7 MB e a projeção linear indica que ultrapassará o threshold de 600 MB em ~30 minutos se a tendência de crescimento se mantiver.

---

**Evidências:**
• `jvm_memory_used_bytes{id="G1 Old Gen", pod="camunda-zeebe-0"}` = 93.7 MB (atual)
• Threshold configurado no alerta: 629.145 MB (600 MB)
• Xmx efetivo da JVM: 750 MB

---

**Remediação sugerida:**
1. Verificar logs do Zeebe em busca de GC pressure:
   `kubectl logs -n camunda camunda-zeebe-0 --tail=200 | grep -i "gc|memory|heap"`
2. Inspecionar carga de processos BPMN ativos:
   `kubectl top pod -n camunda`
3. Se o heap continuar crescendo, considerar restart controlado:
   `kubectl rollout restart statefulset/camunda-zeebe -n camunda`

---

**Próximo monitoramento:**
Observar `jvm_memory_used_bytes{id="G1 Old Gen"}` nos próximos 10 minutos.
"""

_SCENARIOS: dict[str, dict] = {
    "critical": {
        "alert_name": "ZeebeMemoryPredictedHigh",
        "alert_labels": {
            "alertname": "ZeebeMemoryPredictedHigh",
            "namespace": "camunda",
            "pod":       "camunda-zeebe-0",
            "severity":  "critical",
        },
        "alert_annotations": {
            "summary":     "Zeebe heap (G1 Old Gen) projetado acima de 600 MB em 30min",
            "description": "Alerta preditivo — análise gerada pelo agente AIOps local.",
            "runbook_url": "https://github.com/alisson92/camunda-aiops/blob/main/docs/etapa-1-prometheus-rules.md",
        },
        "status":   "firing",
        "analysis": _ANALYSIS,
    },
    "warning": {
        "alert_name": "ZeebeBackpressureGrowing",
        "alert_labels": {
            "alertname": "ZeebeBackpressureGrowing",
            "namespace": "camunda",
            "pod":       "camunda-zeebe-0",
            "severity":  "warning",
        },
        "alert_annotations": {
            "summary":     "Zeebe: backpressure crescente detectado — derivada positiva nas últimas 5m",
            "description": "Alerta preditivo — tendência de aumento de carga no broker.",
        },
        "status":   "firing",
        "analysis": _ANALYSIS,
    },
    "info": {
        "alert_name": "CamundaNamespaceMemoryPressure",
        "alert_labels": {
            "alertname": "CamundaNamespaceMemoryPressure",
            "namespace": "camunda",
            "severity":  "info",
        },
        "alert_annotations": {
            "summary":     "Namespace camunda usando 62% da memória total disponível",
            "description": "Monitoramento informativo — sem ação imediata necessária.",
        },
        "status":   "firing",
        "analysis": "",
    },
    "resolved": {
        "alert_name": "ZeebeMemoryPredictedHigh",
        "alert_labels": {
            "alertname": "ZeebeMemoryPredictedHigh",
            "namespace": "camunda",
            "pod":       "camunda-zeebe-0",
            "severity":  "critical",
        },
        "alert_annotations": {
            "summary":     "Zeebe heap (G1 Old Gen) projetado acima de 600 MB em 30min",
            "description": "Alerta resolvido — heap voltou ao nível normal após restart.",
            "runbook_url": "https://github.com/alisson92/camunda-aiops/blob/main/docs/etapa-1-prometheus-rules.md",
        },
        "status":   "resolved",
        "analysis": "",
    },
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(scenario_key: str) -> None:
    now   = _now_utc()
    extra = {"starts_at": now}
    if _SCENARIOS[scenario_key]["status"] == "resolved":
        extra["ends_at"] = now
    s     = {**_SCENARIOS[scenario_key], **extra}
    label = "RESOLVED" if s["status"] == "resolved" else s["alert_labels"]["severity"].upper()

    print(f"\n{'='*50}")
    print(f"  Enviando: {label} — {s['alert_name']}")
    print(f"{'='*50}")

    ok = send_alert_to_teams(**s)
    if ok:
        print(f"✅ Card [{label}] enviado. Verifique o canal do Teams.")
    else:
        print(f"❌ Falha no envio [{label}]. Verifique TEAMS_WEBHOOK_URL em agent/.env.")


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else list(_SCENARIOS.keys())
    invalid = [t for t in targets if t not in _SCENARIOS]
    if invalid:
        print(f"Cenários inválidos: {invalid}. Opções: {list(_SCENARIOS.keys())}")
        sys.exit(1)
    for key in targets:
        run(key)
