"""Un workflow con YAML invalido pierde su trigger sin avisar (refrescar-pe
quedo sin correr el 18/10 por un salto de linea literal)."""

import yaml

from core.db import ROOT


def test_workflows_son_yaml_valido_con_trigger():
    for f in (ROOT / ".github" / "workflows").glob("*.yml"):
        w = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert w.get(True) or w.get("on"), f"{f.name} sin 'on:'"  # PyYAML lee on: como True
