"""
Ponto único de configuração do agente.

Carrega variáveis de ambiente a partir de agent/.env (desenvolvimento local)
e as expõe como constantes tipadas para todos os módulos do pacote.

Twelve-Factor App — Factor III (Config):
  https://12factor.net/config
"""

import logging
import os
from pathlib import Path

# Carrega agent/.env em desenvolvimento — sem dependência de python-dotenv
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

# --- Ollama ---
OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

# --- Prometheus ---
PROMETHEUS_URL: str = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

# --- Alertmanager ---
ALERTMANAGER_URL: str = os.environ.get("ALERTMANAGER_URL", "http://localhost:9093")

# --- Microsoft Teams ---
TEAMS_WEBHOOK_URL: str = os.environ.get("TEAMS_WEBHOOK_URL", "")

# --- Grafana ---
GRAFANA_URL: str = os.environ.get("GRAFANA_URL", "http://localhost:3000").rstrip("/")
GRAFANA_DASHBOARD_UID: str = os.environ.get("GRAFANA_DASHBOARD_UID", "camunda-local-forecasting")

# --- Agente ---
AGENT_PUBLIC_URL: str = os.environ.get("AGENT_PUBLIC_URL", "http://localhost:5001").rstrip("/")

# --- Logging ---
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


def setup_logging() -> None:
    """Configura o logging da aplicação. Chamar apenas nos entry points."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
