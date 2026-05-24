"""
Testes unitários para tools.py.

Todas as chamadas HTTP ao Prometheus são mockadas via unittest.mock.patch,
garantindo que os testes rodem sem port-forward ou cluster Kind ativo.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from tools import get_alert_rules, query_prometheus_instant, query_prometheus_range


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Cria um MagicMock que imita httpx.Response."""
    mock = MagicMock()
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    mock.status_code = status_code
    return mock


# ---------------------------------------------------------------------------
# query_prometheus_instant
# ---------------------------------------------------------------------------


class TestQueryPrometheusInstant:
    def test_returns_results_on_success(self):
        payload = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"pod": "zeebe-0"}, "value": [1716547200, "0.42"]},
                ],
            },
        }
        with patch("httpx.get", return_value=_mock_response(payload)):
            result = query_prometheus_instant("up")

        assert result["resultType"] == "vector"
        assert len(result["results"]) == 1
        assert result["results"][0]["labels"] == {"pod": "zeebe-0"}
        assert result["results"][0]["value"] == "0.42"

    def test_returns_empty_hint_when_no_series(self):
        payload = {"status": "success", "data": {"resultType": "vector", "result": []}}
        with patch("httpx.get", return_value=_mock_response(payload)):
            result = query_prometheus_instant("nonexistent_metric")

        assert result["empty"] is True
        assert "hint" in result

    def test_returns_error_on_non_success_status(self):
        payload = {"status": "error", "error": "bad query", "data": {"resultType": "vector", "result": []}}
        with patch("httpx.get", return_value=_mock_response(payload)):
            result = query_prometheus_instant("bad{}")

        assert "error" in result
        assert "error" in result["error"].lower() or "status" in result["error"].lower()

    def test_returns_error_on_http_exception(self):
        with patch("httpx.get", side_effect=httpx.HTTPError("connection refused")):
            result = query_prometheus_instant("up")

        assert "error" in result
        assert "connection refused" in result["error"]

    def test_passes_expr_as_query_param(self):
        payload = {"status": "success", "data": {"resultType": "vector", "result": []}}
        with patch("httpx.get", return_value=_mock_response(payload)) as mock_get:
            query_prometheus_instant("jvm_memory_used_bytes{pod='zeebe-0'}")

        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1]["params"]
        assert "jvm_memory_used_bytes" in str(params)


# ---------------------------------------------------------------------------
# query_prometheus_range
# ---------------------------------------------------------------------------


class TestQueryPrometheusRange:
    def test_returns_last_5_values_per_series(self):
        values = [[i, str(i * 0.1)] for i in range(10)]
        payload = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {"metric": {"pod": "zeebe-0"}, "values": values},
                ],
            },
        }
        with patch("httpx.get", return_value=_mock_response(payload)):
            result = query_prometheus_range("up", "now-30m", "now")

        assert result["resultType"] == "matrix"
        assert len(result["results"][0]["last_5_values"]) == 5
        assert result["results"][0]["last_5_values"] == values[-5:]

    def test_returns_empty_when_no_series(self):
        payload = {"status": "success", "data": {"resultType": "matrix", "result": []}}
        with patch("httpx.get", return_value=_mock_response(payload)):
            result = query_prometheus_range("up", "now-30m", "now")

        assert result["empty"] is True

    def test_returns_error_on_http_exception(self):
        with patch("httpx.get", side_effect=httpx.HTTPError("timeout")):
            result = query_prometheus_range("up", "now-30m", "now")

        assert "error" in result

    def test_default_step_is_60(self):
        payload = {"status": "success", "data": {"resultType": "matrix", "result": []}}
        with patch("httpx.get", return_value=_mock_response(payload)) as mock_get:
            query_prometheus_range("up", "now-30m", "now")

        params = mock_get.call_args[1]["params"]
        assert params["step"] == "60"

    def test_custom_step_is_forwarded(self):
        payload = {"status": "success", "data": {"resultType": "matrix", "result": []}}
        with patch("httpx.get", return_value=_mock_response(payload)) as mock_get:
            query_prometheus_range("up", "now-30m", "now", step="120")

        params = mock_get.call_args[1]["params"]
        assert params["step"] == "120"


# ---------------------------------------------------------------------------
# get_alert_rules
# ---------------------------------------------------------------------------


class TestGetAlertRules:
    def _payload_with_rules(self, rules: list) -> dict:
        return {
            "status": "success",
            "data": {
                "groups": [
                    {"name": "camunda.rules", "rules": rules}
                ]
            },
        }

    def test_returns_only_zeebe_and_camunda_rules(self):
        rules = [
            {"type": "alerting", "name": "ZeebeMemoryPredictedHigh", "state": "firing",
             "health": "ok", "query": "expr", "labels": {}, "annotations": {}},
            {"type": "alerting", "name": "NodeHighCPU", "state": "inactive",
             "health": "ok", "query": "expr", "labels": {}, "annotations": {}},
            {"type": "alerting", "name": "CamundaNamespaceMemoryPressure", "state": "inactive",
             "health": "ok", "query": "expr", "labels": {}, "annotations": {}},
        ]
        with patch("httpx.get", return_value=_mock_response(self._payload_with_rules(rules))):
            result = get_alert_rules()

        names = [r["name"] for r in result["rules"]]
        assert "ZeebeMemoryPredictedHigh" in names
        assert "CamundaNamespaceMemoryPressure" in names
        assert "NodeHighCPU" not in names
        assert result["total"] == 2

    def test_returns_empty_when_no_camunda_rules(self):
        rules = [
            {"type": "alerting", "name": "NodeHighCPU", "state": "inactive",
             "health": "ok", "query": "expr", "labels": {}, "annotations": {}},
        ]
        with patch("httpx.get", return_value=_mock_response(self._payload_with_rules(rules))):
            result = get_alert_rules()

        assert result["rules"] == []
        assert result["total"] == 0

    def test_ignores_recording_rules(self):
        rules = [
            {"type": "recording", "name": "ZeebeMemoryRecording", "state": "inactive",
             "health": "ok", "query": "expr", "labels": {}, "annotations": {}},
        ]
        with patch("httpx.get", return_value=_mock_response(self._payload_with_rules(rules))):
            result = get_alert_rules()

        assert result["total"] == 0

    def test_returns_error_on_http_exception(self):
        with patch("httpx.get", side_effect=httpx.HTTPError("connection refused")):
            result = get_alert_rules()

        assert "error" in result

    def test_rule_fields_are_preserved(self):
        rules = [
            {
                "type": "alerting",
                "name": "ZeebeBackpressureGrowing",
                "state": "firing",
                "health": "ok",
                "query": "deriv(zeebe_backpressure[5m]) > 0",
                "labels": {"severity": "warning"},
                "annotations": {"summary": "Backpressure crescente"},
            }
        ]
        with patch("httpx.get", return_value=_mock_response(self._payload_with_rules(rules))):
            result = get_alert_rules()

        rule = result["rules"][0]
        assert rule["state"] == "firing"
        assert rule["query"] == "deriv(zeebe_backpressure[5m]) > 0"
        assert rule["labels"]["severity"] == "warning"
