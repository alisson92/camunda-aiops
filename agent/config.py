"""
Ponto único de configuração do agente.

Carrega variáveis de ambiente a partir de agent/.env (desenvolvimento local)
e as expõe como constantes tipadas para todos os módulos do pacote.

Twelve-Factor App — Factor III (Config):
  https://12factor.net/config
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_env_file(env_path: Path) -> None:
    """Carrega variáveis de um arquivo .env sem sobrescrever o ambiente existente."""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


_load_env_file(Path(__file__).parent / ".env")

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

# Palavras-chave que determinam quais alertas o agente processa.
# Alertas cujo alertname não contiver nenhuma dessas palavras são ignorados.
# Separadas por vírgula: ALERT_FILTER_KEYWORDS=Zeebe,Camunda,Operate
_raw_keywords = os.environ.get("ALERT_FILTER_KEYWORDS", "Zeebe,Camunda,Kube,Elasticsearch")
ALERT_FILTER_KEYWORDS: list[str] = [kw.strip() for kw in _raw_keywords.split(",") if kw.strip()]

# --- Logging ---
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


class _BRTFormatter(logging.Formatter):
    """Formata timestamps dos logs no fuso de Brasília (UTC-3, sem horário de verão)."""
    _tz = timezone(timedelta(hours=-3))

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        ct = datetime.fromtimestamp(record.created, tz=self._tz)
        return ct.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def setup_logging() -> None:
    """Configura o logging da aplicação. Chamar apenas nos entry points."""
    handler = logging.StreamHandler()
    handler.setFormatter(_BRTFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        handlers=[handler],
    )
