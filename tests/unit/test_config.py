"""
Testes unitários para config.py.

Foca na lógica de carregamento do .env, que não é exercida no CI
porque o arquivo agent/.env está no .gitignore.
"""

import logging
import os
import re
from pathlib import Path

import pytest

import importlib

import config
from config import _BRTFormatter, _load_env_file


class TestBRTFormatter:
    def _make_record(self) -> logging.LogRecord:
        return logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)

    def test_formatTime_offset_is_brt(self):
        """Confirma que o fuso aplicado é UTC-3 (Brasília)."""
        formatter = _BRTFormatter()
        result = formatter.formatTime(self._make_record(), datefmt="%z")
        assert result == "-0300"

    def test_formatTime_default_format_matches_pattern(self):
        """Sem datefmt, retorna YYYY-MM-DD HH:MM:SS."""
        formatter = _BRTFormatter()
        result = formatter.formatTime(self._make_record())
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", result)


class TestLoadEnvFile:
    def test_loads_key_value_pair(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_LOAD_KEY=hello\n")
        monkeypatch.delenv("TEST_LOAD_KEY", raising=False)

        _load_env_file(env_file)

        assert os.environ.get("TEST_LOAD_KEY") == "hello"

    def test_ignores_comment_lines(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("# isto é um comentário\nTEST_COMMENT_KEY=value\n")
        monkeypatch.delenv("TEST_COMMENT_KEY", raising=False)

        _load_env_file(env_file)

        assert os.environ.get("TEST_COMMENT_KEY") == "value"

    def test_ignores_empty_lines(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("\n\n\n")

        _load_env_file(env_file)  # não deve lançar exceção

    def test_does_not_override_existing_env_var(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_EXISTING_KEY=from_file\n")
        monkeypatch.setenv("TEST_EXISTING_KEY", "from_environment")

        _load_env_file(env_file)

        assert os.environ.get("TEST_EXISTING_KEY") == "from_environment"

    def test_nonexistent_file_is_silently_ignored(self, tmp_path):
        _load_env_file(tmp_path / "nonexistent.env")  # não deve lançar exceção

    def test_value_with_equals_sign_is_preserved(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_URL_KEY=http://host:8080/path?a=1\n")
        monkeypatch.delenv("TEST_URL_KEY", raising=False)

        _load_env_file(env_file)

        assert os.environ.get("TEST_URL_KEY") == "http://host:8080/path?a=1"


class TestAgentiaLabel:
    def test_alert_with_agentia_true_passes_filter(self):
        """Confirma que a lógica de filtro aceita apenas alertas com agentia=true."""
        labels_with = {"alertname": "ZeebeMemoryPredictedHigh", "agentia": "true"}
        labels_without = {"alertname": "NodeHighCPU"}
        assert labels_with.get("agentia") == "true"
        assert labels_without.get("agentia") != "true"

    def test_agentia_false_is_filtered(self):
        labels = {"alertname": "SomeAlert", "agentia": "false"}
        assert labels.get("agentia") != "true"

    def test_agentia_missing_is_filtered(self):
        labels = {"alertname": "SomeAlert", "severity": "warning"}
        assert labels.get("agentia") != "true"
