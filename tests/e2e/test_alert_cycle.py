"""
Testes E2E do ciclo completo de alerta.

Valida o fluxo real: Alertmanager webhook → agente Python → Prometheus (real)
→ LLM (mock HTTP) → Teams (mock HTTP). Zero mocks em nível de função Python.

Executar: pytest -m e2e -v
          make test-e2e
"""

import json

import pytest

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Fixtures de payload (reutiliza fixtures existentes do projeto)
# ---------------------------------------------------------------------------

ZEEBE_ALERT_PAYLOAD = {
    "receiver": "camunda-aiops-webhook",
    "status": "firing",
    "alerts": [{
        "status": "firing",
        "labels": {
            "alertname": "ZeebeMemoryPredictedHigh",
            "namespace": "camunda",
            "severity": "critical",
            "pod": "camunda-zeebe-0",
        },
        "annotations": {
            "summary": "Zeebe heap projetado acima de 85% em 15min",
            "description": "O heap G1 Old Gen do Zeebe está crescendo e deve ultrapassar 85% do Xmx.",
        },
        "startsAt": "2026-05-24T10:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://localhost:9090/graph",
    }],
    "groupLabels": {"alertname": "ZeebeMemoryPredictedHigh"},
    "commonLabels": {"alertname": "ZeebeMemoryPredictedHigh", "severity": "critical"},
    "commonAnnotations": {"summary": "Zeebe heap projetado acima de 85% em 15min"},
    "version": "4",
}

NON_CAMUNDA_ALERT_PAYLOAD = {
    "receiver": "camunda-aiops-webhook",
    "status": "firing",
    "alerts": [{
        "status": "firing",
        "labels": {"alertname": "NodeHighCPU", "severity": "warning"},
        "annotations": {"summary": "Node CPU alto"},
        "startsAt": "2026-05-24T10:00:00Z",
        "endsAt": "0001-01-01T00:00:00Z",
        "generatorURL": "http://localhost:9090/graph",
    }],
    "groupLabels": {},
    "commonLabels": {"alertname": "NodeHighCPU"},
    "commonAnnotations": {},
    "version": "4",
}


# ---------------------------------------------------------------------------
# Testes E2E
# ---------------------------------------------------------------------------

class TestAlertCycleE2E:
    # httpserver.log entries são tuplas (request, response)
    def _llm_requests(self, httpserver):
        return [req for req, _ in httpserver.log if req.path == "/v1/chat/completions"]

    def _teams_requests(self, httpserver):
        return [req for req, _ in httpserver.log if req.path == "/teams"]

    def test_zeebe_alert_executes_full_cycle(self, e2e_client):
        """
        Ciclo completo: webhook Zeebe → agente → Prometheus real → LLM mock → Teams mock.
        Valida que todos os elos da cadeia foram acionados.
        """
        client, httpserver = e2e_client

        response = client.post("/webhook", json=ZEEBE_ALERT_PAYLOAD)

        # 1. Webhook processado com sucesso — analyses contém 1 entrada
        assert response.status_code == 200
        assert len(response.json()["analyses"]) == 1

        # 2. LLM foi chamado duas vezes (tool_call + stop)
        llm_reqs = self._llm_requests(httpserver)
        assert len(llm_reqs) == 2

        # 3. Primeira chamada ao LLM contém o nome do alerta no contexto
        first_body = json.loads(llm_reqs[0].data)
        assert "ZeebeMemoryPredictedHigh" in json.dumps(first_body["messages"])

        # 4. Segunda chamada ao LLM contém o resultado da tool (resposta do Prometheus)
        second_body = json.loads(llm_reqs[1].data)
        assert "tool" in json.dumps(second_body["messages"])

        # 5. Teams foi notificado exatamente uma vez
        teams_reqs = self._teams_requests(httpserver)
        assert len(teams_reqs) == 1

        # 6. Card enviado ao Teams contém o nome do alerta
        teams_payload = json.loads(teams_reqs[0].data)
        assert "ZeebeMemoryPredictedHigh" in json.dumps(teams_payload)

    def test_non_camunda_alert_is_filtered_before_agent(self, e2e_client):
        """
        Alerta não-Camunda deve ser filtrado pelo webhook receiver:
        nem o LLM nem o Teams devem ser acionados.
        """
        client, httpserver = e2e_client

        response = client.post("/webhook", json=NON_CAMUNDA_ALERT_PAYLOAD)

        assert response.status_code == 200
        assert response.json()["analyses"] == []
        assert len(self._llm_requests(httpserver)) == 0
        assert len(self._teams_requests(httpserver)) == 0

    def test_analysis_text_reaches_teams_card(self, e2e_client):
        """
        O texto de análise retornado pelo LLM deve aparecer no card enviado ao Teams.
        """
        client, httpserver = e2e_client

        client.post("/webhook", json=ZEEBE_ALERT_PAYLOAD)

        teams_payload_str = self._teams_requests(httpserver)[0].data.decode()
        # A análise do LLM mock contém "pressão de memória" — deve chegar ao card
        assert "pressão de memória" in teams_payload_str.lower() or \
               "análise" in teams_payload_str.lower()
