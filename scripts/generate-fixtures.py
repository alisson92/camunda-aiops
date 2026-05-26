#!/usr/bin/env python3
"""
generate-fixtures.py — gera fixtures Alertmanager a partir de alerting/*.yaml

Para cada alerta definido nas PrometheusRules que ainda não tem fixture em
tests/fixtures/, cria <kebab-alertname>-alert.json usando a estrutura padrão
do Alertmanager. Idempotente: detecta alertas já cobertos lendo o campo
alertname dentro dos JSONs existentes — independente do nome do arquivo.

Uso:
    python3 scripts/generate-fixtures.py
    python3 scripts/generate-fixtures.py --dry-run
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys


def _require_yaml() -> object:
    try:
        import yaml  # type: ignore[import-untyped]

        return yaml
    except ModuleNotFoundError:
        print("ERRO: pyyaml não instalado. Execute: pip install pyyaml", file=sys.stderr)
        sys.exit(1)


def camel_to_kebab(name: str) -> str:
    """Converte CamelCase para kebab-case. Ex: ZeebePodOOMKilled → zeebe-pod-oom-killed"""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1-\2", s)
    return s.lower()


def load_alerts_from_yamls(alerting_dir: str) -> list[dict]:
    """Extrai todos os alertas dos PrometheusRule YAMLs em alerting/."""
    yaml = _require_yaml()
    alerts: list[dict] = []
    for yaml_file in sorted(glob.glob(os.path.join(alerting_dir, "*.yaml"))):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        for group in data.get("spec", {}).get("groups", []):
            for rule in group.get("rules", []):
                if "alert" not in rule:
                    continue
                alerts.append(
                    {
                        "name": rule["alert"],
                        "labels": rule.get("labels", {}),
                        "annotations": rule.get("annotations", {}),
                    }
                )
    return alerts


def load_covered_alertnames(fixtures_dir: str) -> set[str]:
    """Lê todos os fixtures existentes e retorna o conjunto de alertnames já cobertos."""
    covered: set[str] = set()
    for json_file in glob.glob(os.path.join(fixtures_dir, "*.json")):
        try:
            with open(json_file) as f:
                data = json.load(f)
            for alert in data.get("alerts", []):
                alertname = alert.get("labels", {}).get("alertname")
                if alertname:
                    covered.add(alertname)
        except (json.JSONDecodeError, KeyError, OSError):
            pass
    return covered


def build_fixture(alert: dict) -> dict:
    """Monta o payload Alertmanager a partir dos metadados extraídos do YAML."""
    name: str = alert["name"]
    labels: dict = alert["labels"]
    annotations: dict = alert["annotations"]

    severity = labels.get("severity", "warning")

    alert_labels: dict = {"alertname": name, "namespace": "camunda", "severity": severity}
    for key in ("component", "team"):
        if labels.get(key):
            alert_labels[key] = labels[key]

    alert_annotations: dict = {}
    for key in ("summary", "description", "runbook_url"):
        if annotations.get(key):
            alert_annotations[key] = annotations[key]

    return {
        "receiver": "camunda-aiops-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": alert_labels,
                "annotations": alert_annotations,
                "startsAt": "2026-01-01T00:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": f"http://localhost:9090/graph?g0.expr={name}",
            }
        ],
        "groupLabels": {"alertname": name},
        "commonLabels": {"alertname": name, "severity": severity},
        "commonAnnotations": {"summary": alert_annotations.get("summary", "")},
        "externalURL": "http://localhost:9093",
        "version": "4",
        "groupKey": '{}/{alertname=~".*"}:{alertname="' + name + '"}',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Lista o que seria gerado sem criar arquivos"
    )
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    alerting_dir = os.path.join(project_dir, "alerting")
    fixtures_dir = os.path.join(project_dir, "tests", "fixtures")

    alerts = load_alerts_from_yamls(alerting_dir)
    covered = load_covered_alertnames(fixtures_dir)

    generated = 0
    skipped = 0

    for alert in alerts:
        name = alert["name"]
        if name in covered:
            print(f"  → já coberto: {name}")
            skipped += 1
            continue

        kebab = camel_to_kebab(name)
        filename = f"{kebab}-alert.json"
        filepath = os.path.join(fixtures_dir, filename)

        if args.dry_run:
            print(f"  + geraria: {filename}")
            generated += 1
            continue

        fixture = build_fixture(alert)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(fixture, f, indent=2, ensure_ascii=False)
            f.write("\n")

        print(f"  ✔ gerado:  {filename}")
        generated += 1

    print()
    if args.dry_run:
        print(f"dry-run: {generated} seriam gerados, {skipped} já cobertos.")
    else:
        print(f"Concluído: {generated} gerado(s), {skipped} já coberto(s).")


if __name__ == "__main__":
    main()
