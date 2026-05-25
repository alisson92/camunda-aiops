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


class TestAlertFilterKeywords:
    def test_default_contains_zeebe_and_camunda(self, monkeypatch):
        monkeypatch.delenv("ALERT_FILTER_KEYWORDS", raising=False)
        importlib.reload(config)
        assert "Zeebe" in config.ALERT_FILTER_KEYWORDS
        assert "Camunda" in config.ALERT_FILTER_KEYWORDS

    def test_custom_keywords_parsed_correctly(self, monkeypatch):
        monkeypatch.setenv("ALERT_FILTER_KEYWORDS", "Operate,Identity,Zeebe")
        importlib.reload(config)
        assert config.ALERT_FILTER_KEYWORDS == ["Operate", "Identity", "Zeebe"]

    def test_keywords_with_spaces_are_stripped(self, monkeypatch):
        monkeypatch.setenv("ALERT_FILTER_KEYWORDS", " Zeebe , Camunda ")
        importlib.reload(config)
        assert config.ALERT_FILTER_KEYWORDS == ["Zeebe", "Camunda"]

    def test_empty_value_produces_empty_list(self, monkeypatch):
        monkeypatch.setenv("ALERT_FILTER_KEYWORDS", "")
        importlib.reload(config)
        assert config.ALERT_FILTER_KEYWORDS == []
