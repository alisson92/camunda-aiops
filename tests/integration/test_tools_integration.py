"""
Testes de integração para tools.py contra um Prometheus real (Testcontainers).

Estes testes validam que o código é compatível com respostas reais da Prometheus HTTP API,
não apenas com dados mockados. Requerem Docker disponível no ambiente de execução.

Executar: pytest -m integration -v
         make test-integration
"""

import pytest

from tools import get_alert_rules, query_prometheus_instant, query_prometheus_range

pytestmark = pytest.mark.integration


class TestQueryPrometheusInstantIntegration:
    def test_self_scrape_metric_returns_results(self):
        """Prometheus scraped a si mesmo — prometheus_build_info deve ter pelo menos 1 resultado."""
        result = query_prometheus_instant("prometheus_build_info")

        assert "results" in result, f"esperado 'results', recebido: {result}"
        assert len(result["results"]) > 0

    def test_self_scrape_result_has_expected_shape(self):
        """Cada resultado deve ter 'labels' (dict) e 'value' (string)."""
        result = query_prometheus_instant("prometheus_build_info")

        assert "results" in result
        first = result["results"][0]
        assert isinstance(first["labels"], dict)
        assert isinstance(first["value"], str)

    def test_nonexistent_metric_returns_empty_dict(self):
        """Métrica inexistente deve retornar empty=True sem levantar exceção."""
        result = query_prometheus_instant("nonexistent_metric_camunda_xyz_000")

        assert result.get("empty") is True
        assert "error" not in result

    def test_invalid_promql_returns_error_dict(self):
        """Expressão PromQL inválida: Prometheus retorna 400, função retorna dict de erro."""
        result = query_prometheus_instant("{{{invalid_expr")

        assert "error" in result


class TestQueryPrometheusRangeIntegration:
    def test_range_query_returns_matrix_results(self):
        """Range query de métrica existente deve retornar resultType=matrix."""
        result = query_prometheus_range("prometheus_build_info", "now-5m", "now", step="30")

        assert "results" in result or result.get("empty") is True
        if "results" in result:
            assert result["resultType"] == "matrix"

    def test_invalid_promql_returns_error_dict(self):
        """Expressão inválida em range query não deve levantar exceção."""
        result = query_prometheus_range("{{{invalid", "now-5m", "now")

        assert "error" in result


class TestGetAlertRulesIntegration:
    def test_fresh_prometheus_returns_no_camunda_rules(self):
        """Container sem PrometheusRules do Camunda retorna lista vazia com estrutura correta."""
        result = get_alert_rules()

        assert "rules" in result, f"esperado 'rules', recebido: {result}"
        assert "total" in result
        assert isinstance(result["rules"], list)
        assert result["total"] == 0
