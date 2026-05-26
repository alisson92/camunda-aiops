#!/usr/bin/env python3
"""
generate-fixtures.py — gera fixtures Alertmanager a partir de alerting/*.yaml

Para cada alerta definido nas PrometheusRules que ainda não tem fixture em
tests/fixtures/, cria <kebab-alertname>-alert.json usando a estrutura padrão
do Alertmanager. Idempotente por filename: pula alertas cujo arquivo já existe.

Expressões Go template presentes nas annotations dos YAMLs ({{ $labels.xxx }},
{{ $value | humanizeXxx }}) são substituídas por valores representativos de demo
antes de escrever o JSON — o LLM recebe contexto legível, não literais de template.

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


# ---------------------------------------------------------------------------
# Resolução de templates Prometheus
# ---------------------------------------------------------------------------

# Valores padrão para {{ $labels.xxx }} — simulam um alerta real de demo
_LABEL_DEFAULTS: dict[str, str] = {
    "pod": "camunda-zeebe-0",
    "container": "zeebe",
    "namespace": "camunda",
    "node": "kind-worker",
    "statefulset": "camunda-zeebe",
    "deployment": "camunda-operate",
    "persistentvolumeclaim": "data-camunda-zeebe-0",
    "persistentvolume": "pvc-data-camunda-zeebe-0",
    "cluster": "camunda-elasticsearch",
    "phase": "Failed",
    "condition": "MemoryPressure",
    "status": "True",
    "created_by_kind": "StatefulSet",
}

# Valores padrão para {{ $value | formatter }}
_VALUE_FORMATTERS: dict[str, str] = {
    "humanizePercentage": "87.3%",
    "humanizeDuration": "2.5s",
    "humanize": "0.87",
    "humanize1024": "1.2Gi",
}

# Overrides por component para labels de instância
_COMPONENT_OVERRIDES: dict[str, dict[str, str]] = {
    "zeebe-gateway": {"pod": "camunda-zeebe-gateway-0", "container": "zeebe-gateway"},
    "elasticsearch": {"pod": "camunda-elasticsearch-0", "container": "elasticsearch",
                      "cluster": "camunda-elasticsearch"},
    "node": {"pod": "camunda-zeebe-0"},
    "storage": {"persistentvolumeclaim": "data-camunda-zeebe-0"},
}


def _label_defaults_for(component: str) -> dict[str, str]:
    for key, overrides in _COMPONENT_OVERRIDES.items():
        if key in component.lower():
            return {**_LABEL_DEFAULTS, **overrides}
    return _LABEL_DEFAULTS


def resolve_templates(text: str, component: str = "") -> str:
    """Substitui {{ $labels.xxx }} e {{ $value | fmt }} por valores de demo."""
    labels = _label_defaults_for(component)

    def replace_label(m: re.Match) -> str:
        return labels.get(m.group(1), f"<{m.group(1)}>")

    def replace_value_fmt(m: re.Match) -> str:
        return _VALUE_FORMATTERS.get(m.group(1).strip(), "N/A")

    text = re.sub(r"\{\{\s*\$labels\.(\w+)\s*\}\}", replace_label, text)
    text = re.sub(r"\{\{\s*\$value\s*\|\s*(\w+)\s*\}\}", replace_value_fmt, text)
    text = re.sub(r"\{\{\s*\$value\s*\}\}", "0.87", text)
    return text


def _extract_referenced_labels(text: str) -> list[str]:
    """Retorna os nomes de label referenciados em {{ $labels.xxx }} no texto."""
    return re.findall(r"\{\{\s*\$labels\.(\w+)\s*\}\}", text)


# ---------------------------------------------------------------------------
# Leitura dos YAMLs e geração dos fixtures
# ---------------------------------------------------------------------------


def camel_to_kebab(name: str) -> str:
    """ZeebePodOOMKilled → zeebe-pod-oom-killed"""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", name)
    s = re.sub(r"([a-z\d])([A-Z])", r"\1-\2", s)
    return s.lower()


def load_alerts_from_yamls(alerting_dir: str) -> list[dict]:
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


def build_fixture(alert: dict) -> dict:
    """Monta o payload Alertmanager com templates resolvidos e labels de instância."""
    name: str = alert["name"]
    labels: dict = alert["labels"]
    annotations: dict = alert["annotations"]

    severity = labels.get("severity", "warning")
    component = labels.get("component", "")
    label_defaults = _label_defaults_for(component)

    # Labels base do alerta
    alert_labels: dict = {"alertname": name, "namespace": "camunda", "severity": severity}
    for key in ("component", "team"):
        if labels.get(key):
            alert_labels[key] = labels[key]

    # Adiciona labels de instância referenciados nas annotations (ex: pod, container, node)
    all_annotation_text = " ".join(annotations.values())
    for label_name in _extract_referenced_labels(all_annotation_text):
        if label_name not in alert_labels and label_name in label_defaults:
            alert_labels[label_name] = label_defaults[label_name]

    # Resolve templates nas annotations
    alert_annotations: dict = {}
    for key in ("summary", "description", "runbook_url"):
        if annotations.get(key):
            alert_annotations[key] = resolve_templates(annotations[key], component)

    summary = alert_annotations.get("summary", "")
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
        "commonAnnotations": {"summary": summary},
        "externalURL": "http://localhost:9093",
        "version": "4",
        "groupKey": '{}/{alertname=~".*"}:{alertname="' + name + '"}',
    }


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------


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

    generated = 0
    skipped = 0

    for alert in alerts:
        name = alert["name"]
        kebab = camel_to_kebab(name)
        filename = f"{kebab}-alert.json"
        filepath = os.path.join(fixtures_dir, filename)

        if os.path.exists(filepath):
            print(f"  → já existe: {filename}")
            skipped += 1
            continue

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
        print(f"dry-run: {generated} seriam gerados, {skipped} já existiam.")
    else:
        print(f"Concluído: {generated} gerado(s), {skipped} já existiam.")


if __name__ == "__main__":
    main()
