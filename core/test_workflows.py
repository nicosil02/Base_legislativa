"""Un workflow con YAML invalido pierde su trigger sin avisar (refrescar-pe
quedo sin correr el 18/10 por un salto de linea literal)."""

import re

import yaml

from core.db import ROOT

WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def test_workflows_son_yaml_valido_con_trigger():
    for f in WORKFLOWS:
        w = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert w.get(True) or w.get("on"), f"{f.name} sin 'on:'"  # PyYAML lee on: como True


def test_pip_install_usa_constraints():
    # Sin -c constraints.txt pip baja la ultima version y un dia algo se rompe
    # (PyAV 19 rompio Whisper de un dia para otro).
    malos = [
        f"{f.name}: {linea.strip()}"
        for f in WORKFLOWS
        for linea in f.read_text(encoding="utf-8").splitlines()
        if re.search(r"\bpip install\b", linea.split("#")[0])
        and "-c constraints.txt" not in linea
    ]
    assert not malos, "pip install sin -c constraints.txt:\n" + "\n".join(malos)
    assert (ROOT / "constraints.txt").exists()
