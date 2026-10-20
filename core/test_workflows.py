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


def test_workflow_run_apunta_a_nombres_reales():
    # workflow_run.workflows son patrones (* ? + [ ] ! especiales): el "+" sin
    # escapar de "Actualizar Peru (PLs + snapshot)" nunca coincidio y el cerebro
    # (filtro de clientes) y salud no corrieron tras refrescar-pe del 27/09 al 20/10.
    datos = {f.name: yaml.safe_load(f.read_text(encoding="utf-8")) for f in WORKFLOWS}
    nombres = {w["name"] for w in datos.values()}
    malos = [
        f"{nombre}: {p}"
        for nombre, w in datos.items()
        for p in ((w.get(True) or w.get("on") or {}).get("workflow_run") or {}).get("workflows", [])
        if re.search(r"(?<!\\)[*?+\[\]!]", p) or re.sub(r"\\(.)", r"\1", p) not in nombres
    ]
    assert not malos, "workflow_run que no coincide con ningun workflow:\n" + "\n".join(malos)


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
