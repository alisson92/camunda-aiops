"""
Fixtures compartilhadas para testes de integração.

O container Prometheus é criado uma única vez por sessão de teste (scope="session")
e destruído automaticamente ao final. A fixture prometheus_url aguarda o primeiro
self-scrape antes de liberar os testes, garantindo que prometheus_build_info
tenha dados disponíveis.
"""

import time

import httpx
import pytest
import tools as tools_module
from testcontainers.core.container import DockerContainer


def _wait_for_first_scrape(url: str, timeout: int = 30) -> None:
    """Aguarda até o Prometheus completar o primeiro scrape de si mesmo."""
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
    """Sobe um container Prometheus real e aguarda estar pronto para receber queries."""
    with DockerContainer("prom/prometheus:v3.1.0").with_exposed_ports(9090) as container:
        yield container


@pytest.fixture(scope="session")
def prometheus_url(prometheus_container):
    host = prometheus_container.get_container_host_ip()
    port = prometheus_container.get_exposed_port(9090)
    url = f"http://{host}:{port}"
    _wait_for_first_scrape(url)
    return url


@pytest.fixture(autouse=True)
def patch_tools_prometheus_url(prometheus_url):
    """Redireciona todas as chamadas HTTP de tools.py para o container local."""
    original = tools_module.PROMETHEUS_URL
    tools_module.PROMETHEUS_URL = prometheus_url
    yield
    tools_module.PROMETHEUS_URL = original
