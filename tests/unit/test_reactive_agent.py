"""
Testes unitários para reactive_agent.py.

O cliente OpenAI (que aponta para o Ollama local) é mockado integralmente.
Nenhuma chamada de rede é feita durante os testes.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from reactive_agent import MAX_TOOL_ROUNDS, run_agent


def _make_choice(finish_reason: str, content: str = "", tool_calls: list = None) -> MagicMock:
    """Cria um MagicMock que imita openai.types.chat.ChatCompletionChoice."""
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message.content = content
    choice.message.tool_calls = tool_calls or []
    return choice


def _make_completion(choice: MagicMock) -> MagicMock:
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def _make_tool_call(name: str, arguments: dict, call_id: str = "call_001") -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = call_id
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)
    return tool_call


# ---------------------------------------------------------------------------
# Comportamento de stop imediato
# ---------------------------------------------------------------------------


class TestRunAgentStop:
    def test_returns_llm_content_on_immediate_stop(self):
        choice = _make_choice("stop", content="Análise: tudo ok.")
        with patch("reactive_agent.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _make_completion(choice)
            result = run_agent("ZeebeMemoryPredictedHigh", {}, {})

        assert result == "Análise: tudo ok."

    def test_returns_fallback_message_when_content_is_empty(self):
        choice = _make_choice("stop", content="")
        with patch("reactive_agent.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _make_completion(choice)
            result = run_agent("ZeebeMemoryPredictedHigh", {}, {})

        assert "[sem resposta textual]" in result

    def test_returns_unexpected_finish_reason_message(self):
        choice = _make_choice("length", content="")
        with patch("reactive_agent.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _make_completion(choice)
            result = run_agent("ZeebeMemoryPredictedHigh", {}, {})

        assert "finish_reason" in result
        assert "length" in result


# ---------------------------------------------------------------------------
# Tool use loop
# ---------------------------------------------------------------------------


class TestRunAgentToolLoop:
    def test_one_tool_call_round_then_stop(self):
        tool_call = _make_tool_call("query_prometheus_instant", {"expr": "up"})
        tool_choice = _make_choice("tool_calls", tool_calls=[tool_call])
        stop_choice = _make_choice("stop", content="Resultado com base na métrica.")

        mock_tool_fn = MagicMock(return_value={"results": [{"labels": {}, "value": "1"}]})

        create_mock = MagicMock(side_effect=[
            _make_completion(tool_choice),
            _make_completion(stop_choice),
        ])

        with (
            patch("reactive_agent.OpenAI") as MockOpenAI,
            patch.dict("reactive_agent.TOOL_DISPATCH", {"query_prometheus_instant": mock_tool_fn}),
        ):
            MockOpenAI.return_value.chat.completions.create = create_mock
            result = run_agent("ZeebeMemoryPredictedHigh", {}, {})

        assert result == "Resultado com base na métrica."
        mock_tool_fn.assert_called_once_with(expr="up")
        assert create_mock.call_count == 2

    def test_unknown_tool_returns_error_in_tool_message(self):
        tool_call = _make_tool_call("ferramenta_inexistente", {})
        tool_choice = _make_choice("tool_calls", tool_calls=[tool_call])
        stop_choice = _make_choice("stop", content="OK")

        create_mock = MagicMock(side_effect=[
            _make_completion(tool_choice),
            _make_completion(stop_choice),
        ])

        with patch("reactive_agent.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create = create_mock
            result = run_agent("ZeebeMemoryPredictedHigh", {}, {})

        # Verifica que o agente não explodiu e chegou ao final
        assert result == "OK"
        # A mensagem de erro deve ter sido inserida no histórico como role=tool
        all_calls = create_mock.call_args_list
        second_call_messages = all_calls[1][1]["messages"]
        tool_messages = [m for m in second_call_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        assert "desconhecida" in tool_messages[0]["content"]

    def test_tool_exception_returns_error_in_tool_message(self):
        tool_call = _make_tool_call("query_prometheus_instant", {"expr": "up"})
        tool_choice = _make_choice("tool_calls", tool_calls=[tool_call])
        stop_choice = _make_choice("stop", content="OK")

        create_mock = MagicMock(side_effect=[
            _make_completion(tool_choice),
            _make_completion(stop_choice),
        ])

        with (
            patch("reactive_agent.OpenAI") as MockOpenAI,
            patch.dict("reactive_agent.TOOL_DISPATCH", {"query_prometheus_instant": MagicMock(side_effect=RuntimeError("falha"))}),
        ):
            MockOpenAI.return_value.chat.completions.create = create_mock
            result = run_agent("ZeebeMemoryPredictedHigh", {}, {})

        assert result == "OK"
        all_calls = create_mock.call_args_list
        tool_messages = [
            m for m in all_calls[1][1]["messages"] if m.get("role") == "tool"
        ]
        assert "falha" in tool_messages[0]["content"]

    def test_invalid_tool_arguments_json_does_not_crash(self):
        tool_call = _make_tool_call("query_prometheus_instant", {"expr": "up"})
        tool_call.function.arguments = "{ broken json"
        tool_choice = _make_choice("tool_calls", tool_calls=[tool_call])
        stop_choice = _make_choice("stop", content="OK")

        create_mock = MagicMock(side_effect=[
            _make_completion(tool_choice),
            _make_completion(stop_choice),
        ])

        with (
            patch("reactive_agent.OpenAI") as MockOpenAI,
            patch.dict("reactive_agent.TOOL_DISPATCH", {"query_prometheus_instant": MagicMock(return_value={})}),
        ):
            MockOpenAI.return_value.chat.completions.create = create_mock
            # Não deve lançar exceção
            result = run_agent("ZeebeMemoryPredictedHigh", {}, {})

        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Limite de rodadas
# ---------------------------------------------------------------------------


class TestRunAgentRoundLimit:
    def test_returns_limit_message_after_max_rounds(self):
        tool_call = _make_tool_call("query_prometheus_instant", {"expr": "up"})
        always_tool_choice = _make_choice("tool_calls", tool_calls=[tool_call])

        mock_tool_fn = MagicMock(return_value={})
        create_mock = MagicMock(return_value=_make_completion(always_tool_choice))

        with (
            patch("reactive_agent.OpenAI") as MockOpenAI,
            patch.dict("reactive_agent.TOOL_DISPATCH", {"query_prometheus_instant": mock_tool_fn}),
        ):
            MockOpenAI.return_value.chat.completions.create = create_mock
            result = run_agent("ZeebeMemoryPredictedHigh", {}, {})

        assert "Limite" in result or "rodadas" in result
        assert create_mock.call_count == MAX_TOOL_ROUNDS


# ---------------------------------------------------------------------------
# Contexto do alerta passado ao LLM
# ---------------------------------------------------------------------------


class TestRunAgentContext:
    def test_alert_name_and_labels_are_in_user_message(self):
        choice = _make_choice("stop", content="ok")
        with patch("reactive_agent.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _make_completion(choice)
            run_agent(
                "ZeebeMemoryPredictedHigh",
                {"namespace": "camunda", "severity": "critical"},
                {"summary": "Heap alto"},
                status="firing",
            )

        create_call = MockOpenAI.return_value.chat.completions.create.call_args
        messages = create_call[1]["messages"]
        user_msg = next(m for m in messages if m["role"] == "user")
        assert "ZeebeMemoryPredictedHigh" in user_msg["content"]
        assert "camunda" in user_msg["content"]
