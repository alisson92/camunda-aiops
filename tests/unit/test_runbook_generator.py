"""
Testes unitários para runbook_generator.py.

Cobre geração via LLM (mockada), fallback local, inferência de componente,
geração de alert_id e renderização Markdown→HTML.
"""

import hashlib
import re
from unittest.mock import MagicMock, patch

import pytest

from runbook_generator import (
    _fallback_runbook,
    _infer_component,
    _make_alert_id,
    _markdown_to_html,
    generate_runbook,
    render_runbook_html,
)


# ---------------------------------------------------------------------------
# _make_alert_id
# ---------------------------------------------------------------------------


class TestMakeAlertId:
    def test_slug_is_url_safe(self):
        alert_id = _make_alert_id("ZeebeMemoryPredictedHigh", "2026-05-24T10:00:00Z")
        assert re.match(r"^[a-z0-9-]+$", alert_id), f"ID não URL-safe: {alert_id}"

    def test_slug_contains_alert_name(self):
        alert_id = _make_alert_id("ZeebeMemoryPredictedHigh", "2026-05-24T10:00:00Z")
        assert "zeebe" in alert_id
        assert "memory" in alert_id

    def test_different_starts_at_gives_different_ids(self):
        id1 = _make_alert_id("ZeebeMemoryPredictedHigh", "2026-05-24T10:00:00Z")
        id2 = _make_alert_id("ZeebeMemoryPredictedHigh", "2026-05-24T11:00:00Z")
        assert id1 != id2

    def test_same_inputs_are_deterministic(self):
        id1 = _make_alert_id("ZeebeBackpressureGrowing", "2026-05-24T10:00:00Z")
        id2 = _make_alert_id("ZeebeBackpressureGrowing", "2026-05-24T10:00:00Z")
        assert id1 == id2

    def test_suffix_is_8_hex_chars(self):
        alert_id = _make_alert_id("ZeebeMemoryPredictedHigh", "2026-05-24T10:00:00Z")
        suffix = alert_id.split("-")[-1]
        assert len(suffix) == 8
        assert re.match(r"^[0-9a-f]+$", suffix)

    def test_expected_suffix_from_known_input(self):
        starts_at = "2026-05-24T10:00:00Z"
        expected_suffix = hashlib.md5(starts_at.encode("utf-8")).hexdigest()[:8]
        alert_id = _make_alert_id("ZeebeMemoryPredictedHigh", starts_at)
        assert alert_id.endswith(expected_suffix)


# ---------------------------------------------------------------------------
# _infer_component
# ---------------------------------------------------------------------------


class TestInferComponent:
    def test_zeebe_memory_alert_returns_broker(self):
        assert _infer_component("ZeebeMemoryPredictedHigh", {}) == "zeebe-broker"

    def test_zeebe_backpressure_returns_gateway(self):
        assert _infer_component("ZeebeBackpressureGrowing", {}) == "zeebe-gateway"

    def test_zeebe_gateway_explicit_returns_gateway(self):
        assert _infer_component("ZeebeGatewayLatencyHigh", {}) == "zeebe-gateway"

    def test_camunda_namespace_alert_returns_namespace_label(self):
        result = _infer_component("CamundaNamespaceMemoryPressure", {"namespace": "camunda"})
        assert result == "camunda"

    def test_camunda_alert_without_namespace_label(self):
        result = _infer_component("CamundaMemoryHigh", {})
        assert result == "camunda"

    def test_unknown_alert_returns_service_label(self):
        result = _infer_component("NodeDiskPressure", {"service": "my-svc"})
        assert result == "my-svc"

    def test_unknown_alert_without_labels_returns_unknown(self):
        result = _infer_component("NodeDiskPressure", {})
        assert result == "unknown"


# ---------------------------------------------------------------------------
# _fallback_runbook
# ---------------------------------------------------------------------------


class TestFallbackRunbook:
    def test_contains_alert_name(self):
        rb = _fallback_runbook("ZeebeMemoryPredictedHigh", "critical", "zeebe-broker", "25/05/2026 10:00", "análise")
        assert "ZeebeMemoryPredictedHigh" in rb

    def test_contains_severity(self):
        rb = _fallback_runbook("ZeebeMemoryPredictedHigh", "critical", "zeebe-broker", "25/05/2026 10:00", "análise")
        assert "critical" in rb

    def test_contains_analysis_text(self):
        rb = _fallback_runbook("ZeebeMemoryPredictedHigh", "warning", "zeebe-broker", "25/05/2026 10:00", "causa raiz: heap alto")
        assert "causa raiz: heap alto" in rb

    def test_is_valid_markdown(self):
        rb = _fallback_runbook("Alert", "info", "comp", "now", "análise")
        assert rb.startswith("# Runbook:")


# ---------------------------------------------------------------------------
# generate_runbook
# ---------------------------------------------------------------------------


def _make_llm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


class TestGenerateRunbook:
    def test_returns_alert_id_and_markdown(self):
        llm_response = _make_llm_response("# Runbook: ZeebeMemory\n\nconteúdo")
        with patch("runbook_generator.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = llm_response
            alert_id, runbook = generate_runbook(
                alert_name="ZeebeMemoryPredictedHigh",
                alert_labels={"severity": "critical", "namespace": "camunda"},
                analysis="CAUSA_RAIZ: heap alto",
                starts_at="2026-05-24T10:00:00Z",
            )
        assert isinstance(alert_id, str)
        assert len(alert_id) > 0
        assert "# Runbook" in runbook

    def test_alert_id_is_url_safe(self):
        with patch("runbook_generator.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _make_llm_response("# Runbook")
            alert_id, _ = generate_runbook("ZeebeMemoryPredictedHigh", {}, "análise", "2026-05-24T10:00:00Z")
        assert re.match(r"^[a-z0-9-]+$", alert_id)

    def test_empty_starts_at_still_produces_valid_id(self):
        with patch("runbook_generator.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _make_llm_response("# Runbook")
            alert_id, _ = generate_runbook("ZeebeMemoryPredictedHigh", {}, "análise")
        # starts_at omitido → usa "unknown" como salt do MD5 — ID ainda deve ser URL-safe
        assert re.match(r"^[a-z0-9-]+$", alert_id)
        assert len(alert_id) > 0

    def test_llm_failure_returns_fallback(self):
        with patch("runbook_generator.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.side_effect = RuntimeError("timeout")
            alert_id, runbook = generate_runbook(
                alert_name="ZeebeMemoryPredictedHigh",
                alert_labels={"severity": "critical"},
                analysis="causa raiz: heap alto",
                starts_at="2026-05-24T10:00:00Z",
            )
        assert isinstance(alert_id, str)
        assert "ZeebeMemoryPredictedHigh" in runbook
        assert "causa raiz: heap alto" in runbook

    def test_llm_returns_none_content_uses_fallback(self):
        response = _make_llm_response(None)
        with patch("runbook_generator.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = response
            _, runbook = generate_runbook("ZeebeMemoryPredictedHigh", {}, "análise", "2026-05-24T10:00:00Z")
        # None → .strip() raises AttributeError → fallback
        assert "ZeebeMemoryPredictedHigh" in runbook

    def test_user_message_contains_alert_name(self):
        with patch("runbook_generator.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _make_llm_response("# Runbook")
            generate_runbook("ZeebeMemoryPredictedHigh", {"severity": "warning"}, "análise", "2026-05-24T10:00:00Z")

        call_kwargs = MockOpenAI.return_value.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "ZeebeMemoryPredictedHigh" in user_msg["content"]
        assert "warning" in user_msg["content"]


# ---------------------------------------------------------------------------
# _markdown_to_html
# ---------------------------------------------------------------------------


class TestMarkdownToHtml:
    def test_h1(self):
        html = _markdown_to_html("# Título principal")
        assert "<h1>Título principal</h1>" in html

    def test_h2(self):
        html = _markdown_to_html("## Seção")
        assert "<h2>Seção</h2>" in html

    def test_h3(self):
        html = _markdown_to_html("### Subseção")
        assert "<h3>Subseção</h3>" in html

    def test_bold_inline(self):
        html = _markdown_to_html("Texto com **negrito** aqui")
        assert "<strong>negrito</strong>" in html

    def test_inline_code(self):
        html = _markdown_to_html("Use `kubectl get pods`")
        assert "<code>kubectl get pods</code>" in html

    def test_unordered_list(self):
        html = _markdown_to_html("- item um\n- item dois")
        assert "<ul>" in html
        assert "<li>item um</li>" in html
        assert "<li>item dois</li>" in html
        assert "</ul>" in html

    def test_ordered_list(self):
        html = _markdown_to_html("1. primeiro\n2. segundo")
        assert "<ol>" in html
        assert "<li>primeiro</li>" in html
        assert "<li>segundo</li>" in html
        assert "</ol>" in html

    def test_fenced_code_block(self):
        md = "```bash\nkubectl get pods -n camunda\n```"
        html = _markdown_to_html(md)
        assert "<pre><code>" in html
        assert "kubectl get pods -n camunda" in html
        assert "</code></pre>" in html

    def test_fenced_code_escapes_html(self):
        md = "```\n<script>alert(1)</script>\n```"
        html = _markdown_to_html(md)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_ul_closes_before_ol(self):
        md = "- item\n1. passo"
        html = _markdown_to_html(md)
        assert html.index("</ul>") < html.index("<ol>")

    def test_ol_closes_before_ul(self):
        md = "1. passo\n- item"
        html = _markdown_to_html(md)
        assert html.index("</ol>") < html.index("<ul>")

    def test_paragraph_text(self):
        html = _markdown_to_html("Este é um parágrafo.")
        assert "<p>Este é um parágrafo.</p>" in html

    def test_empty_lines_do_not_generate_elements(self):
        html = _markdown_to_html("\n\n\n")
        assert html.strip() == ""

    def test_bold_in_list_item(self):
        html = _markdown_to_html("- **crítico**: reiniciar pod")
        assert "<strong>crítico</strong>" in html

    def test_multiple_code_blocks(self):
        md = "```\nbloco1\n```\n\n```\nbloco2\n```"
        html = _markdown_to_html(md)
        assert html.count("<pre><code>") == 2
        assert "bloco1" in html
        assert "bloco2" in html


# ---------------------------------------------------------------------------
# render_runbook_html
# ---------------------------------------------------------------------------


class TestRenderRunbookHtml:
    def test_returns_complete_html_document(self):
        html = render_runbook_html("ZeebeMemoryPredictedHigh", "# Runbook\n\nconteúdo")
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_title_contains_alert_name(self):
        html = render_runbook_html("ZeebeMemoryPredictedHigh", "# Runbook")
        assert "ZeebeMemoryPredictedHigh" in html

    def test_body_contains_rendered_markdown(self):
        html = render_runbook_html("Alert", "# Meu Runbook\n\n## Seção")
        assert "<h1>" in html
        assert "<h2>" in html

    def test_has_css_styling(self):
        html = render_runbook_html("Alert", "# Runbook")
        assert "<style>" in html
