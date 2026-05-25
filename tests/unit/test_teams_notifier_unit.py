"""
Testes unitários para teams_notifier.py.

Testa helpers puros (sem I/O) e a montagem do card Adaptive Card.
O envio HTTP ao Teams é mockado — nenhuma notificação real é disparada.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from teams_notifier import (
    _build_analysis_blocks,
    _clean_analysis,
    _format_alert_time,
    _format_duration,
    _truncate,
    send_alert_to_teams,
)


# ---------------------------------------------------------------------------
# _format_alert_time
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _format_duration
# ---------------------------------------------------------------------------


class TestFormatDuration:
    def test_minutes_only(self):
        assert _format_duration("2026-05-25T10:00:00Z", "2026-05-25T10:45:00Z") == "45 min"

    def test_exact_one_hour(self):
        assert _format_duration("2026-05-25T10:00:00Z", "2026-05-25T11:00:00Z") == "1h"

    def test_hours_and_minutes(self):
        assert _format_duration("2026-05-25T10:00:00Z", "2026-05-25T11:30:00Z") == "1h 30min"

    def test_zero_minutes_returns_zero(self):
        assert _format_duration("2026-05-25T10:00:00Z", "2026-05-25T10:00:00Z") == "0 min"

    def test_invalid_timestamps_return_empty(self):
        assert _format_duration("invalid", "also-invalid") == ""


class TestFormatAlertTime:
    def test_empty_string_returns_dash(self):
        assert _format_alert_time("") == "—"

    def test_valid_utc_iso_converts_to_brt(self):
        # 13:00 UTC → 10:00 BRT (UTC-3)
        result = _format_alert_time("2026-05-24T13:00:00Z")
        assert "10:00" in result
        assert "24/05/2026" in result

    def test_iso_with_offset_is_handled(self):
        result = _format_alert_time("2026-05-24T10:00:00+00:00")
        assert "07:00" in result

    def test_invalid_string_returns_original(self):
        result = _format_alert_time("not-a-date")
        assert result == "not-a-date"


# ---------------------------------------------------------------------------
# _clean_analysis
# ---------------------------------------------------------------------------


class TestCleanAnalysis:
    def test_headings_become_bold(self):
        result = _clean_analysis("## Causa raiz")
        assert "**Causa raiz**" in result
        assert "##" not in result

    def test_fenced_code_blocks_are_unwrapped(self):
        text = "```bash\nkubectl get pods\n```"
        result = _clean_analysis(text)
        assert "kubectl get pods" in result
        assert "```" not in result

    def test_inline_code_backticks_removed(self):
        result = _clean_analysis("Métrica `jvm_memory_used_bytes` em alta")
        assert "`" not in result
        assert "jvm_memory_used_bytes" in result

    def test_triple_dash_lines_removed(self):
        result = _clean_analysis("Texto\n---\nMais texto")
        assert "---" not in result

    def test_multiple_blank_lines_collapsed(self):
        result = _clean_analysis("Linha 1\n\n\n\nLinha 2")
        assert "\n\n\n" not in result

    def test_strips_leading_trailing_whitespace(self):
        result = _clean_analysis("\n\n  texto  \n\n")
        assert result == "texto"


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------


class TestTruncate:
    def test_short_text_unchanged(self):
        text = "curto"
        assert _truncate(text, limit=100) == text

    def test_long_text_is_truncated(self):
        text = "x" * 5000
        result = _truncate(text, limit=4000)
        assert len(result) < 5000
        assert "truncada" in result

    def test_exact_limit_not_truncated(self):
        text = "x" * 4000
        assert _truncate(text, limit=4000) == text


# ---------------------------------------------------------------------------
# _build_analysis_blocks
# ---------------------------------------------------------------------------


class TestBuildAnalysisBlocks:
    def test_returns_list_of_dicts(self):
        blocks = _build_analysis_blocks("Texto simples")
        assert isinstance(blocks, list)
        assert all(isinstance(b, dict) for b in blocks)

    def test_bold_header_line_gets_bolder_weight(self):
        blocks = _build_analysis_blocks("**Causa raiz:**")
        header_block = next(b for b in blocks if b.get("weight") == "Bolder")
        assert "Causa raiz" in header_block["text"]

    def test_kubectl_command_gets_monospace_style(self):
        blocks = _build_analysis_blocks("kubectl get pods -n camunda")
        mono_block = next(b for b in blocks if b.get("fontType") == "Monospace")
        assert "kubectl" in mono_block["text"]

    def test_empty_text_returns_empty_list(self):
        assert _build_analysis_blocks("") == []

    def test_separator_added_after_first_header(self):
        text = "**Header 1:**\nTexto\n**Header 2:**"
        blocks = _build_analysis_blocks(text)
        headers = [b for b in blocks if b.get("weight") == "Bolder"]
        assert len(headers) == 2
        # Segundo header deve ter separator=True
        assert headers[1].get("separator") is True
        # Primeiro header não deve ter separator
        assert "separator" not in headers[0]


# ---------------------------------------------------------------------------
# send_alert_to_teams
# ---------------------------------------------------------------------------


class TestSendAlertToTeams:
    _BASE_LABELS = {"alertname": "ZeebeMemoryPredictedHigh", "severity": "critical", "namespace": "camunda"}
    _BASE_ANNOTATIONS = {"summary": "Heap alto", "description": "Projeção indica 600 MB"}

    def test_returns_false_when_webhook_url_not_configured(self):
        with patch("teams_notifier.TEAMS_WEBHOOK_URL", ""):
            result = send_alert_to_teams(
                "ZeebeMemory", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "firing", "análise", "2026-05-24T10:00:00Z",
            )
        assert result is False

    def test_returns_true_on_success(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.status_code = 200

        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", return_value=mock_resp),
        ):
            result = send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "firing", "análise aqui", "2026-05-24T10:00:00Z",
            )

        assert result is True

    def test_returns_false_on_http_error(self):
        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", side_effect=httpx.HTTPError("timeout")),
        ):
            result = send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "firing", "análise", "2026-05-24T10:00:00Z",
            )

        assert result is False

    def test_resolved_status_uses_green_color(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", return_value=mock_resp) as mock_post,
        ):
            send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "resolved", "", "2026-05-24T10:00:00Z", "2026-05-24T10:30:00Z",
            )

        card_payload = mock_post.call_args[1]["json"]
        card_body = card_payload["attachments"][0]["content"]["body"]
        title_block = card_body[0]
        assert title_block["color"] == "good"
        assert "RESOLVED" in title_block["text"]

    def test_firing_critical_uses_red_color(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", return_value=mock_resp) as mock_post,
        ):
            send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "firing", "", "2026-05-24T10:00:00Z",
            )

        card_payload = mock_post.call_args[1]["json"]
        title_block = card_payload["attachments"][0]["content"]["body"][0]
        assert title_block["color"] == "attention"

    def test_silence_button_present_in_firing(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", return_value=mock_resp) as mock_post,
        ):
            send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "firing", "", "2026-05-24T10:00:00Z",
            )

        card_payload = mock_post.call_args[1]["json"]
        actions = card_payload["attachments"][0]["content"]["actions"]
        titles = [a["title"] for a in actions]
        assert any("Silence" in t for t in titles)

    def test_silence_button_absent_in_resolved(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", return_value=mock_resp) as mock_post,
        ):
            send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "resolved", "", "2026-05-24T10:00:00Z", "2026-05-24T10:30:00Z",
            )

        card_payload = mock_post.call_args[1]["json"]
        actions = card_payload["attachments"][0]["content"]["actions"]
        titles = [a["title"] for a in actions]
        assert not any("Silence" in t for t in titles)

    def test_runbook_button_present_when_annotation_set(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        annotations = {**self._BASE_ANNOTATIONS, "runbook_url": "https://github.com/org/runbook.md"}

        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", return_value=mock_resp) as mock_post,
        ):
            send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, annotations,
                "firing", "", "2026-05-24T10:00:00Z",
            )

        actions = mock_post.call_args[1]["json"]["attachments"][0]["content"]["actions"]
        titles = [a["title"] for a in actions]
        assert any("Runbook" in t for t in titles)

    def test_analysis_show_card_present_when_analysis_given(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", return_value=mock_resp) as mock_post,
        ):
            send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "firing", "**Causa raiz:** heap crescendo", "2026-05-24T10:00:00Z",
            )

        actions = mock_post.call_args[1]["json"]["attachments"][0]["content"]["actions"]
        show_card_actions = [a for a in actions if a["type"] == "Action.ShowCard"]
        assert len(show_card_actions) == 1

    def test_no_analysis_show_card_when_analysis_empty(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None

        with (
            patch("teams_notifier.TEAMS_WEBHOOK_URL", "https://teams.example/webhook"),
            patch("httpx.post", return_value=mock_resp) as mock_post,
        ):
            send_alert_to_teams(
                "ZeebeMemoryPredictedHigh", self._BASE_LABELS, self._BASE_ANNOTATIONS,
                "firing", "", "2026-05-24T10:00:00Z",
            )

        actions = mock_post.call_args[1]["json"]["attachments"][0]["content"]["actions"]
        show_card_actions = [a for a in actions if a["type"] == "Action.ShowCard"]
        assert len(show_card_actions) == 0
