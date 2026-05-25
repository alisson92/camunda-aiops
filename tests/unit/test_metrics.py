"""
Testes unitários para metrics.py.

Verifica que todas as métricas estão definidas com os nomes, labels e tipos corretos.
Não testa valores de contador — esses são efeitos colaterais de testes de comportamento.
"""

from prometheus_client import Counter, Histogram
from prometheus_client import REGISTRY

from metrics import (
    ALERTS_FILTERED,
    ALERTS_PROCESSED,
    ANALYSIS_DURATION,
    LLM_ROUNDS_USED,
    LLM_TOOL_CALLS,
    TEAMS_NOTIFICATIONS,
    WEBHOOKS_RECEIVED,
)


class TestMetricsDefinition:
    def test_webhooks_received_is_counter_with_status_label(self):
        assert isinstance(WEBHOOKS_RECEIVED, Counter)
        assert "status" in WEBHOOKS_RECEIVED._labelnames

    def test_alerts_processed_is_counter_with_alertname_severity_labels(self):
        assert isinstance(ALERTS_PROCESSED, Counter)
        assert "alertname" in ALERTS_PROCESSED._labelnames
        assert "severity" in ALERTS_PROCESSED._labelnames

    def test_alerts_filtered_is_counter_without_labels(self):
        assert isinstance(ALERTS_FILTERED, Counter)
        assert len(ALERTS_FILTERED._labelnames) == 0

    def test_analysis_duration_is_histogram(self):
        assert isinstance(ANALYSIS_DURATION, Histogram)

    def test_analysis_duration_has_custom_buckets(self):
        # Verifica que os buckets incluem valores esperados para análise LLM (1s–120s)
        assert 30 in ANALYSIS_DURATION._upper_bounds
        assert 120 in ANALYSIS_DURATION._upper_bounds

    def test_llm_tool_calls_is_counter_with_tool_name_label(self):
        assert isinstance(LLM_TOOL_CALLS, Counter)
        assert "tool_name" in LLM_TOOL_CALLS._labelnames

    def test_teams_notifications_is_counter_with_success_label(self):
        assert isinstance(TEAMS_NOTIFICATIONS, Counter)
        assert "success" in TEAMS_NOTIFICATIONS._labelnames

    def test_llm_rounds_used_is_histogram(self):
        assert isinstance(LLM_ROUNDS_USED, Histogram)

    def test_llm_rounds_used_has_buckets_covering_max_rounds(self):
        # Buckets devem cobrir o intervalo 1–MAX_TOOL_ROUNDS (6)
        assert 3 in LLM_ROUNDS_USED._upper_bounds
        assert 6 in LLM_ROUNDS_USED._upper_bounds

    def test_all_metrics_registered_in_default_registry(self):
        """Garante que todas as métricas estão no REGISTRY padrão."""
        registered_names = set(REGISTRY._names_to_collectors.keys())
        assert "aiops_webhooks_total" in registered_names
        assert "aiops_alerts_processed_total" in registered_names
        assert "aiops_alerts_filtered_total" in registered_names
        assert "aiops_analysis_duration_seconds_count" in registered_names
        assert "aiops_llm_tool_calls_total" in registered_names
        assert "aiops_llm_rounds_used_count" in registered_names
        assert "aiops_teams_notifications_total" in registered_names

    def test_alerts_filtered_starts_at_zero(self):
        """Contador sem labels deve inicializar com 0."""
        from prometheus_client import REGISTRY
        value = REGISTRY.get_sample_value("aiops_alerts_filtered_total")
        assert value is not None  # None = não registrado; 0.0 = registrado e zerado
