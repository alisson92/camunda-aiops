"""
Valida a estrutura dos fixtures de alerta usados nos testes e smoke tests.

Esses arquivos simulam o payload enviado pelo Alertmanager para o webhook
do agente. Se a estrutura mudar, o agente pode quebrar silenciosamente —
esses testes garantem que os fixtures permanecem válidos e consistentes.
"""

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

ALERT_FIXTURES = [
    "zeebe-memory-alert.json",
    "namespace-memory-alert.json",
]

REQUIRED_TOP_LEVEL_KEYS = {"receiver", "status", "alerts", "version"}
REQUIRED_ALERT_KEYS = {"status", "labels", "annotations", "startsAt", "endsAt"}
REQUIRED_LABEL_KEYS = {"alertname", "severity"}


def load_fixture(filename: str) -> dict:
    path = FIXTURES_DIR / filename
    assert path.exists(), f"Fixture não encontrada: {path}"
    return json.loads(path.read_text())


class TestAlertFixtureStructure:
    """Garante que os fixtures mantêm o contrato do payload do Alertmanager v4."""

    def test_all_fixture_files_exist(self):
        for name in ALERT_FIXTURES:
            assert (FIXTURES_DIR / name).exists(), f"Fixture ausente: {name}"

    def test_top_level_keys_present(self):
        for name in ALERT_FIXTURES:
            payload = load_fixture(name)
            missing = REQUIRED_TOP_LEVEL_KEYS - payload.keys()
            assert not missing, f"{name}: chaves ausentes no topo: {missing}"

    def test_alerts_list_is_non_empty(self):
        for name in ALERT_FIXTURES:
            payload = load_fixture(name)
            assert isinstance(payload["alerts"], list), f"{name}: 'alerts' deve ser lista"
            assert len(payload["alerts"]) > 0, f"{name}: 'alerts' não pode ser vazio"

    def test_each_alert_has_required_keys(self):
        for name in ALERT_FIXTURES:
            payload = load_fixture(name)
            for i, alert in enumerate(payload["alerts"]):
                missing = REQUIRED_ALERT_KEYS - alert.keys()
                assert not missing, f"{name}[{i}]: chaves ausentes no alerta: {missing}"

    def test_each_alert_has_required_labels(self):
        for name in ALERT_FIXTURES:
            payload = load_fixture(name)
            for i, alert in enumerate(payload["alerts"]):
                missing = REQUIRED_LABEL_KEYS - alert["labels"].keys()
                assert not missing, f"{name}[{i}]: labels ausentes: {missing}"

    def test_status_values_are_valid(self):
        valid_statuses = {"firing", "resolved"}
        for name in ALERT_FIXTURES:
            payload = load_fixture(name)
            assert payload["status"] in valid_statuses, (
                f"{name}: status inválido no topo: '{payload['status']}'"
            )
            for i, alert in enumerate(payload["alerts"]):
                assert alert["status"] in valid_statuses, (
                    f"{name}[{i}]: status inválido no alerta: '{alert['status']}'"
                )

    def test_alertmanager_version_is_v4(self):
        for name in ALERT_FIXTURES:
            payload = load_fixture(name)
            assert payload["version"] == "4", (
                f"{name}: versão esperada '4', encontrada '{payload['version']}'"
            )
