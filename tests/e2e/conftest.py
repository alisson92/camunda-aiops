"""
Fixtures para testes E2E do ciclo completo.

Arquitetura:
  - Prometheus real via Testcontainers (queries reais)
  - Ollama mockado em HTTP real via pytest-httpserver (sem modelo local no CI)
  - Teams mockado em HTTP real via pytest-httpserver (sem webhook externo)
  - Código Python 100% real — zero mocks em nível de função
"""

import json
import time

import httpx
import pytest
import reactive_agent as agent_module
import teams_notifier as notifier_module
import tools as tools_module
from starlette.testclient import TestClient
from testcontainers.core.container import DockerContainer

from webhook_receiver import app


# ---------------------------------------------------------------------------
# Prometheus (Testcontainers)
# ---------------------------------------------------------------------------

def _wait_for_first_scrape(url: str, timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{url}/api/v1/query", params={"query": "prometheus_build_info"}, timeout=5)
            if resp.json().get("data", {}).get("result"):
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"Prometheus não realizou o primeiro scrape em {timeout}s")


@pytest.fixture(scope="session")
def prometheus_container():
    with DockerContainer("prom/prometheus:v3.1.0").with_exposed_ports(9090) as container:
        yield container


@pytest.fixture(scope="session")
def prometheus_url(prometheus_container):
    host = prometheus_container.get_container_host_ip()
    port = prometheus_container.get_exposed_port(9090)
    url = f"http://{host}:{port}"
    _wait_for_first_scrape(url)
    return url


# ---------------------------------------------------------------------------
# Respostas mock do LLM (formato OpenAI Chat Completions)
# ---------------------------------------------------------------------------

def _llm_tool_call_response() -> dict:
    """Primeira resposta do LLM: solicita uma tool call ao Prometheus."""
    return {
        "id": "chatcmpl-e2e-1",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "qwen2.5:7b",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_e2e_1",
                    "type": "function",
                    "function": {
                        "name": "query_prometheus_instant",
                        "arguments": json.dumps({"expr": "prometheus_build_info"}),
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
    }


def _llm_stop_response() -> dict:
    """Segunda resposta do LLM: análise final após receber o resultado da tool."""
    return {
        "id": "chatcmpl-e2e-2",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "qwen2.5:7b",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "**Análise:** Pressão de memória detectada no Zeebe. "
                           "A query Prometheus confirma instâncias ativas. "
                           "Recomenda-se monitorar o heap da JVM.",
                "tool_calls": None,
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
    }


# ---------------------------------------------------------------------------
# Cliente TestClient + patches de URLs
# ---------------------------------------------------------------------------

@pytest.fixture()
def e2e_client(prometheus_url, httpserver):
    """
    Monta o ambiente E2E completo num único servidor HTTP mock:
      - LLM mockado em POST /v1/chat/completions (respostas ordenadas)
      - Teams mockado em POST /teams
      - URLs patchadas nos módulos Python

    Retorna (TestClient, httpserver) onde httpserver serve ambos LLM e Teams.
    """
    # Configura LLM: chamada 1 → tool_call, chamada 2 → stop (análise final)
    httpserver.expect_ordered_request("/v1/chat/completions", method="POST") \
        .respond_with_json(_llm_tool_call_response())
    httpserver.expect_ordered_request("/v1/chat/completions", method="POST") \
        .respond_with_json(_llm_stop_response())

    # Configura Teams: aceita qualquer POST em /teams e responde 200
    httpserver.expect_request("/teams", method="POST").respond_with_data("1", status=200)

    # Patcha URLs nos módulos (os valores são lidos no momento da chamada HTTP)
    original_prometheus = tools_module.PROMETHEUS_URL
    original_ollama = agent_module.OLLAMA_BASE_URL
    original_teams = notifier_module.TEAMS_WEBHOOK_URL

    tools_module.PROMETHEUS_URL = prometheus_url
    agent_module.OLLAMA_BASE_URL = httpserver.url_for("/v1").rstrip("/")
    notifier_module.TEAMS_WEBHOOK_URL = httpserver.url_for("/teams")

    yield TestClient(app), httpserver

    # Restaura os valores originais
    tools_module.PROMETHEUS_URL = original_prometheus
    agent_module.OLLAMA_BASE_URL = original_ollama
    notifier_module.TEAMS_WEBHOOK_URL = original_teams
