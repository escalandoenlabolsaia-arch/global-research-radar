"""Carga del config — TODO el radar se controla desde config/sources.yaml."""
import yaml


def load(path: str = "config/sources.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
