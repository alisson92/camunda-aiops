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


_MOCK_RUNBOOK_ID = "zeebe-memory-predicted-high-aabbccdd"
_MOCK_RUNBOOK_MD = "# Runbook: ZeebeMemoryPredictedHigh\n\nconteúdo"


@pytest.fixture()
def client():
    """Cria o TestClient isolando chamadas externas do agente."""
    with (
        patch("webhook_receiver.run_agent", return_value="análise mockada") as mock_agent,
        patch("webhook_receiver.send_alert_to_teams", return_value=True) as mock_teams,
        patch(
            "webhook_receiver.generate_runbook",
            return_value=(_MOCK_RUNBOOK_ID, _MOCK_RUNBOOK_MD),
        ) as mock_runbook,
    ):
        from webhook_receiver import app

        yield TestClient(app), mock_agent, mock_teams, mock_runbook


# ---------------------------------------------------------------------------
# _reload_runbooks_from_kb — startup reload path
# ---------------------------------------------------------------------------


class TestStartupReload:
    def test_reload_populates_both_dicts(self):
        """Cobre o corpo do loop de reload — executado apenas quando KB tem runbooks em disco."""
        from unittest.mock import patch

        from knowledge_base import Document
        from webhook_receiver import _kb, _latest_runbook_by_name, _reload_runbooks_from_kb, _runbooks

        mock_doc = Document(
            doc_id="reload-test-00000000",
            title="Runbook: ReloadTestAlert",
            content="# Runbook content",
            alert_name="ReloadTestAlert",
            source="generated",
        )
        with patch.object(_kb, "get_runbooks", return_value={"reload-test-00000000": mock_doc}):
            _reload_runbooks_from_kb()

        try:
            assert "reload-test-00000000" in _runbooks
            assert _runbooks["reload-test-00000000"] == ("ReloadTestAlert", "# Runbook content")
            assert _latest_runbook_by_name.get("ReloadTestAlert") == "reload-test-00000000"
        finally:
            _runbooks.pop("reload-test-00000000", None)
            _latest_runbook_by_name.pop("ReloadTestAlert", None)


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

    def test_body_includes_knowledge_base_info(self, client):
        tc, *_ = client
        body = tc.get("/health").json()
        assert "knowledge_base" in body
        assert "documents" in body["knowledge_base"]
        assert isinstance(body["knowledge_base"]["documents"], int)


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
        tc, mock_agent, *_ = client
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
        tc, mock_agent, mock_teams, _ = client
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

    def test_run_agent_called_with_alert_id(self, client):
        tc, mock_agent, *_ = client
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
        tc.post("/webhook", json=payload)
        call_kwargs = mock_agent.call_args[1]
        assert "alert_id" in call_kwargs
        assert len(call_kwargs["alert_id"]) == 8

    def test_camunda_alert_triggers_agent(self, client):
        tc, mock_agent, *_ = client
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
        tc, mock_agent, *_ = client
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

    def test_response_includes_runbook_id(self, client):
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
        assert "runbook_id" in resp.json()["analyses"][0]

    def test_generate_runbook_called_for_firing(self, client):
        tc, _, _, mock_runbook = client
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
        tc.post("/webhook", json=payload)
        mock_runbook.assert_called_once()

    def test_generate_runbook_not_called_for_resolved(self, client):
        tc, _, _, mock_runbook = client
        payload = {
            "alerts": [
                {
                    "status": "resolved",
                    "labels": {"alertname": "ZeebeMemoryPredictedHigh", "severity": "critical"},
                    "annotations": {},
                    "startsAt": "2026-05-24T10:00:00Z",
                    "endsAt": "2026-05-24T10:30:00Z",
                }
            ]
        }
        tc.post("/webhook", json=payload)
        mock_runbook.assert_not_called()

    def test_teams_notification_failure_is_tracked(self):
        """Cobre o branch TEAMS_NOTIFICATIONS success=false."""
        with (
            patch("webhook_receiver.run_agent", return_value="análise"),
            patch("webhook_receiver.send_alert_to_teams", return_value=False),
            patch(
                "webhook_receiver.generate_runbook",
                return_value=(_MOCK_RUNBOOK_ID, _MOCK_RUNBOOK_MD),
            ),
        ):
            from webhook_receiver import app

            tc = TestClient(app)
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
        assert resp.status_code == 200
        assert len(resp.json()["analyses"]) == 1


# ---------------------------------------------------------------------------
# /runbook/{alert_id}
# ---------------------------------------------------------------------------


class TestRunbookEndpoint:
    _FIRING_PAYLOAD = {
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

    def test_runbook_found_after_webhook(self, client):
        tc, *_ = client
        tc.post("/webhook", json=self._FIRING_PAYLOAD)
        resp = tc.get(f"/runbook/{_MOCK_RUNBOOK_ID}")
        assert resp.status_code == 200

    def test_runbook_response_is_html(self, client):
        tc, *_ = client
        tc.post("/webhook", json=self._FIRING_PAYLOAD)
        resp = tc.get(f"/runbook/{_MOCK_RUNBOOK_ID}")
        assert "text/html" in resp.headers["content-type"]

    def test_runbook_html_contains_alert_name(self, client):
        tc, *_ = client
        tc.post("/webhook", json=self._FIRING_PAYLOAD)
        resp = tc.get(f"/runbook/{_MOCK_RUNBOOK_ID}")
        assert "ZeebeMemoryPredictedHigh" in resp.text

    def test_runbook_not_found_returns_404(self, client):
        tc, *_ = client
        resp = tc.get("/runbook/alert-inexistente-00000000")
        assert resp.status_code == 404

    def test_runbook_served_from_pre_existing_store(self):
        """Simula runbook recarregado da KB após restart — acessível sem /webhook prévio."""
        from webhook_receiver import _runbooks, app

        pre_id = "pre-existing-00000000"
        _runbooks[pre_id] = ("TestAlert", "# Runbook: TestAlert\n\nconteúdo")
        try:
            tc = TestClient(app)
            resp = tc.get(f"/runbook/{pre_id}")
            assert resp.status_code == 200
            assert "TestAlert" in resp.text
        finally:
            _runbooks.pop(pre_id, None)

    def test_resolved_alert_has_no_runbook(self, client):
        tc, *_ = client
        resolved_payload = {
            "alerts": [
                {
                    "status": "resolved",
                    "labels": {"alertname": "ZeebeMemoryPredictedHigh", "severity": "critical"},
                    "annotations": {},
                    "startsAt": "2026-05-24T10:00:00Z",
                    "endsAt": "2026-05-24T10:30:00Z",
                }
            ]
        }
        post_resp = tc.post("/webhook", json=resolved_payload)
        runbook_id = post_resp.json()["analyses"][0]["runbook_id"]
        assert runbook_id == ""


# ---------------------------------------------------------------------------
# /runbook/by-alert/{alert_name}
# ---------------------------------------------------------------------------


class TestRunbookByAlertEndpoint:
    _FIRING_PAYLOAD = {
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

    def test_returns_200_after_webhook(self, client):
        tc, *_ = client
        tc.post("/webhook", json=self._FIRING_PAYLOAD)
        resp = tc.get("/runbook/by-alert/ZeebeMemoryPredictedHigh")
        assert resp.status_code == 200

    def test_response_is_html(self, client):
        tc, *_ = client
        tc.post("/webhook", json=self._FIRING_PAYLOAD)
        resp = tc.get("/runbook/by-alert/ZeebeMemoryPredictedHigh")
        assert "text/html" in resp.headers["content-type"]

    def test_html_contains_alert_name(self, client):
        tc, *_ = client
        tc.post("/webhook", json=self._FIRING_PAYLOAD)
        resp = tc.get("/runbook/by-alert/ZeebeMemoryPredictedHigh")
        assert "ZeebeMemoryPredictedHigh" in resp.text

    def test_unknown_alert_name_returns_404(self, client):
        tc, *_ = client
        resp = tc.get("/runbook/by-alert/AlertInexistente")
        assert resp.status_code == 404

    def test_serves_pre_existing_runbook_by_name(self):
        """Simula runbook recarregado da KB — acessível via alertname sem /webhook prévio."""
        from webhook_receiver import _latest_runbook_by_name, _runbooks, app

        pre_id = "by-name-test-00000000"
        alert_name = "TestAlertByName"
        _runbooks[pre_id] = (alert_name, "# Runbook: TestAlertByName\n\nconteúdo")
        _latest_runbook_by_name[alert_name] = pre_id
        try:
            tc = TestClient(app)
            resp = tc.get(f"/runbook/by-alert/{alert_name}")
            assert resp.status_code == 200
            assert alert_name in resp.text
        finally:
            _runbooks.pop(pre_id, None)
            _latest_runbook_by_name.pop(alert_name, None)


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


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_returns_200(self, client):
        tc, *_ = client
        resp = tc.get("/metrics")
        assert resp.status_code == 200

    def test_content_type_is_prometheus(self, client):
        tc, *_ = client
        resp = tc.get("/metrics")
        assert "text/plain" in resp.headers["content-type"]

    def test_aiops_metrics_present(self, client):
        tc, *_ = client
        resp = tc.get("/metrics")
        assert "aiops_webhooks_total" in resp.text
        assert "aiops_alerts_processed_total" in resp.text
        assert "aiops_analysis_duration_seconds" in resp.text
