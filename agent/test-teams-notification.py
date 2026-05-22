"""
Script de teste rápido para validar a notificação Teams.
Usa o fixture do alerta de memória do Zeebe para simular uma análise real.

Uso:
  TEAMS_WEBHOOK_URL=https://... python3 test-teams-notification.py
  # ou coloque a URL no .env e rode diretamente:
  python3 test-teams-notification.py
"""

import os
from pathlib import Path

# Carrega .env manualmente (mesma lógica do reactive_agent)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

from teams_notifier import send_alert_to_teams

ANALYSIS_SAMPLE = """### Diagnóstico

**Causa raiz identificada:**
A métrica `jvm_memory_used_bytes` para a G1 Old Gen do pod `camunda-zeebe-0` está em **93.7 MB**
e a projeção linear indica que ultrapassará o threshold de 600 MB em ~30 minutos se a tendência
de crescimento se mantiver.

### Evidências

- `jvm_memory_used_bytes{id="G1 Old Gen", pod="camunda-zeebe-0"}` = 93.7 MB (atual)
- Threshold configurado no alerta: 629.145 KB (600 MB)
- Xmx efetivo da JVM: 750 MB

### Remediação sugerida

1. Verificar logs do Zeebe em busca de GC pressure:
   `kubectl logs -n camunda camunda-zeebe-0 --tail=200 | grep -i "gc\\|memory\\|heap"`

2. Inspecionar carga de processos BPMN ativos:
   `kubectl top pod -n camunda`

3. Se o heap continuar crescendo, considerar restart controlado:
   `kubectl rollout restart statefulset/camunda-zeebe -n camunda`

### Próximo monitoramento

Observar `jvm_memory_used_bytes{id="G1 Old Gen"}` nos próximos 10 minutos.
Se a derivada seguir positiva, ação de remediação necessária.
"""

if __name__ == "__main__":
    print("Enviando card de teste para o Teams...")
    success = send_alert_to_teams(
        alert_name="ZeebeMemoryPredictedHigh",
        alert_labels={
            "alertname": "ZeebeMemoryPredictedHigh",
            "namespace": "camunda",
            "pod": "camunda-zeebe-0",
            "severity": "warning",
        },
        alert_annotations={
            "summary": "Zeebe heap (G1 Old Gen) projetado acima de 600 MB em 30min",
            "description": "Alerta preditivo — análise gerada pelo agente AIOps local.",
        },
        status="firing",
        analysis=ANALYSIS_SAMPLE,
    )
    if success:
        print("✅ Card enviado. Verifique o canal do Teams.")
    else:
        print("❌ Falha no envio. Verifique TEAMS_WEBHOOK_URL no .env e a conectividade.")
