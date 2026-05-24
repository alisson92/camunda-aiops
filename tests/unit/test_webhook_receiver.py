"""
Testes unitários para webhook_receiver.py.

Cobre os endpoints /health, /webhook e /silence usando FastAPI TestClient.
Dependências externas (run_agent, send_alert_to_teams, httpx) são mockadas
para que os testes rodem sem Prometheus, Ollama ou Alertmanager disponíveis.
"""

from datetime import timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Cria o TestClient isolando chamadas externas do agente."""
    with (
        patch("webhook_receiver.run_agent", return_value="análise mockada") as mock_agent,
        patch("webhook_receiver.send_alert_to_teams", return_value=True) as mock_teams,
    ):
        from webhook_receiver import app

        yield TestClient(app), mock_agent, mock_teams


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_returns_200(self, client):
        tc, *_ = client
        resp = tc.get("/health")
        assert resp.status_code == 200

    def test_body_has_status_ok(self, client):
        tc, *_ = client
        body = tc.get("/health").json()
        assert body["status"] == "ok"
        assert "timestamp" in body


# ---------------------------------------------------------------------------
# /webhook
# ---------------------------------------------------------------------------


class TestWebhookEndpoint:
    def test_invalid_json_returns_400(self, client):
        tc, *_ = client
        resp = tc.post("/webhook", content=b"nao-e-json", headers={"content-type": "application/json"})
        assert resp.status_code == 400

    def test_empty_alerts_list_returns_zero_processed(self, client):
        tc, *_ = client
        resp = tc.post("/webhook", json={"alerts": []})
        assert resp.status_code == 200
        assert resp.json()["processed"] == 0

    def test_missing_alerts_key_returns_zero_processed(self, client):
        tc, *_ = client
        resp = tc.post("/webhook", json={})
        assert resp.status_code == 200
        assert resp.json()["processed"] == 0

    def test_non_camunda_alert_is_filtered(self, client):
        tc, mock_agent, _ = client
        payload = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "NodeHighCPU", "severity": "warning"},
                    "annotations": {},
                    "startsAt": "2026-05-24T10:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                }
            ]
        }
        resp = tc.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert len(resp.json()["analyses"]) == 0
        mock_agent.assert_not_called()

    def test_zeebe_alert_triggers_agent_and_teams(self, client):
        tc, mock_agent, mock_teams = client
        payload = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "ZeebeMemoryPredictedHigh",
                        "namespace": "camunda",
                        "severity": "critical",
                    },
                    "annotations": {"summary": "Zeebe heap alto"},
                    "startsAt": "2026-05-24T10:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                }
            ]
        }
        resp = tc.post("/webhook", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["analyses"]) == 1
        assert body["analyses"][0]["alertname"] == "ZeebeMemoryPredictedHigh"
        mock_agent.assert_called_once()
        mock_teams.assert_called_once()

    def test_camunda_alert_triggers_agent(self, client):
        tc, mock_agent, _ = client
        payload = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "CamundaNamespaceMemoryPressure", "severity": "info"},
                    "annotations": {},
                    "startsAt": "2026-05-24T10:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                }
            ]
        }
        resp = tc.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert len(resp.json()["analyses"]) == 1
        mock_agent.assert_called_once()

    def test_multiple_alerts_processes_only_camunda(self, client):
        tc, mock_agent, _ = client
        payload = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "ZeebeBackpressureGrowing", "severity": "warning"},
                    "annotations": {},
                    "startsAt": "2026-05-24T10:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                },
                {
                    "status": "firing",
                    "labels": {"alertname": "NodeDiskPressure", "severity": "warning"},
                    "annotations": {},
                    "startsAt": "2026-05-24T10:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                },
            ]
        }
        resp = tc.post("/webhook", json=payload)
        assert resp.status_code == 200
        assert len(resp.json()["analyses"]) == 1
        assert mock_agent.call_count == 1

    def test_response_includes_analysis_text(self, client):
        tc, *_ = client
        payload = {
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "ZeebeMemoryPredictedHigh", "severity": "critical"},
                    "annotations": {},
                    "startsAt": "2026-05-24T10:00:00Z",
                    "endsAt": "0001-01-01T00:00:00Z",
                }
            ]
        }
        resp = tc.post("/webhook", json=payload)
        assert resp.json()["analyses"][0]["analysis"] == "análise mockada"


# ---------------------------------------------------------------------------
# /silence
# ---------------------------------------------------------------------------


class TestSilenceEndpoint:
    def _make_client(self):
        """TestClient sem fixture para testes que precisam mockar httpx."""
        from webhook_receiver import app

        return TestClient(app)

    def test_invalid_duration_value_returns_400(self):
        with patch("httpx.post"):
            tc = self._make_client()
            resp = tc.get("/silence?alert=ZeebeMemory&duration=xh")
            assert resp.status_code == 400

    def test_unsupported_duration_unit_returns_400(self):
        with patch("httpx.post"):
            tc = self._make_client()
            resp = tc.get("/silence?alert=ZeebeMemory&duration=1d")
            assert resp.status_code == 400

    def test_valid_hour_duration_calls_alertmanager(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"silenceID": "abc-123"}
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            tc = self._make_client()
            resp = tc.get("/silence?alert=ZeebeMemoryPredictedHigh&duration=1h")

        assert resp.status_code == 200
        assert "ZeebeMemoryPredictedHigh" in resp.text
        assert "abc-123" in resp.text
        mock_post.assert_called_once()

    def test_valid_minute_duration_calls_alertmanager(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"silenceID": "xyz-456"}
        mock_resp.raise_for_status.return_value = None

        with patch("httpx.post", return_value=mock_resp):
            tc = self._make_client()
            resp = tc.get("/silence?alert=ZeebeMemoryPredictedHigh&duration=30m")

        assert resp.status_code == 200
        assert "30m" in resp.text

    def test_alertmanager_failure_returns_502(self):
        import httpx as httpx_lib

        with patch("httpx.post", side_effect=httpx_lib.HTTPError("timeout")):
            tc = self._make_client()
            resp = tc.get("/silence?alert=ZeebeMemory&duration=1h")

        assert resp.status_code == 502

    def test_missing_alert_param_returns_422(self):
        with patch("httpx.post"):
            tc = self._make_client()
            resp = tc.get("/silence?duration=1h")
        assert resp.status_code == 422
