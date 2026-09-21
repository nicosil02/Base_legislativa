"""Almacenamiento de decisiones humanas sobre sugerencias de reclasificacion -
mismo backend (GitHub Contents API) y mismo patron que
alerts/borradores_store.py.

Por que existe: pages/1_Peru.py abre proyectos.db en modo READ-ONLY/immutable
(no puede escribir), y aunque pudiera, ese archivo local en Streamlit Cloud es
efimero (se reconstruye del snapshot .gz en cada redeploy) y no tiene nada
que ver con el proyectos.db real que usa refrescar-pe.yml en GitHub Actions -
escribir ahi se perderia sin dejar rastro. En cambio: la UI solo REGISTRA la
decision (aceptar/rechazar) en este JSON chico, y `clasificador.cli
aplicar-decisiones` (corrido por refrescar-pe.yml, que SI tiene el
proyectos.db real y permiso de commit) es quien de verdad actualiza
proyectos.tema y clasificacion_sugerencias.estado, y limpia las decisiones
ya aplicadas de este archivo.

`data/clasificador_decisiones.json` es la fuente de verdad mientras una
decision esta pendiente de aplicar - una vez aplicada, se saca de aca (no
hace falta guardar historial doble, clasificacion_sugerencias.decided_at/
decided_by ya lo registra permanentemente).
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DECISIONES_PATH = "data/clasificador_decisiones.json"
CACHE_TTL_SECONDS = 30
_cache = {"decisiones": None, "fetched_at": 0}


def _local_path() -> Path:
    return Path(__file__).resolve().parent.parent / DECISIONES_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_config() -> dict:
    return {
        "token": os.environ.get("GH_TOKEN"),
        "repo": os.environ.get("GH_REPO"),
        "branch": os.environ.get("GH_BRANCH", "main"),
    }


def _fetch_remote() -> dict | None:
    cfg = _gh_config()
    if not cfg["token"] or not cfg["repo"]:
        return None
    url = (
        "https://api.github.com/repos/" + cfg["repo"]
        + "/contents/" + DECISIONES_PATH
        + "?ref=" + cfg["branch"]
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + cfg["token"],
            "Accept": "application/vnd.github+json",
            "User-Agent": "ValiIntelligence/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        body = base64.b64decode(data.get("content", "")).decode("utf-8")
        return {"decisiones": json.loads(body), "sha": data.get("sha")}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"decisiones": [], "sha": None}
        return None
    except Exception:
        return None


def _read_local() -> dict:
    p = _local_path()
    if not p.exists():
        return {"decisiones": [], "sha": None}
    try:
        return {"decisiones": json.loads(p.read_text(encoding="utf-8")), "sha": None}
    except Exception:
        return {"decisiones": [], "sha": None}


def list_decisiones_pendientes() -> list[dict]:
    """Decisiones registradas desde la UI que `aplicar-decisiones` todavia
    no proceso. Cache corto (30s) para no golpear la API de GitHub en cada
    rerun de Streamlit."""
    now = time.time()
    if _cache["decisiones"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        state = _cache["decisiones"]
    else:
        state = _fetch_remote() or _read_local()
        _cache["decisiones"] = state
        _cache["fetched_at"] = now
    return state["decisiones"]


def registrar_decision(*, sugerencia_id: int, decision: str, decided_by: str | None = None) -> bool:
    """decision: 'aceptar' o 'rechazar'. Upsert por sugerencia_id - si
    Nicolas cambia de opinion antes de que se aplique, la ultima decision
    gana."""
    assert decision in ("aceptar", "rechazar"), decision
    cfg = _gh_config()
    usar_gh = bool(cfg["token"] and cfg["repo"])
    remote = _fetch_remote() if usar_gh else None
    state = remote or _read_local()
    decisiones = state["decisiones"]
    now = _now_iso()

    existente = next((d for d in decisiones if d.get("sugerencia_id") == sugerencia_id), None)
    if existente:
        existente["decision"] = decision
        existente["decided_at"] = now
        existente["decided_by"] = decided_by
    else:
        decisiones.append({
            "sugerencia_id": sugerencia_id, "decision": decision,
            "decided_at": now, "decided_by": decided_by,
        })

    new_content = json.dumps(decisiones, ensure_ascii=False, indent=2)

    if not usar_gh:
        p = _local_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_content, encoding="utf-8")
        _cache["decisiones"] = {"decisiones": decisiones, "sha": None}
        _cache["fetched_at"] = time.time()
        return True

    body = {
        "message": f"clasificador: {decision} sugerencia {sugerencia_id}",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": cfg["branch"],
    }
    if state.get("sha"):
        body["sha"] = state["sha"]
    url = "https://api.github.com/repos/" + cfg["repo"] + "/contents/" + DECISIONES_PATH
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="PUT",
        headers={
            "Authorization": "Bearer " + cfg["token"],
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ValiIntelligence/1.0",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError("GitHub PUT failed: " + str(e.code) + " " + err_body[:300]) from None
    _cache["decisiones"] = None
    _cache["fetched_at"] = 0
    return True


def limpiar_decisiones_aplicadas(sugerencia_ids: list[int]) -> None:
    """Saca del JSON local las decisiones ya aplicadas a proyectos.db -
    llamado SOLO por `clasificador.cli aplicar-decisiones` (corre en
    GitHub Actions, escritura local directa + su propio git commit, no via
    API de GitHub)."""
    if not sugerencia_ids:
        return
    p = _local_path()
    state = _read_local()
    quedan = [d for d in state["decisiones"] if d.get("sugerencia_id") not in set(sugerencia_ids)]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(quedan, ensure_ascii=False, indent=2), encoding="utf-8")
    _cache["decisiones"] = None
    _cache["fetched_at"] = 0


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    import tempfile

    global _local_path
    old_token = os.environ.pop("GH_TOKEN", None)
    old_local_path = _local_path
    tmpdir = tempfile.mkdtemp()
    fake_path = Path(tmpdir) / "data" / "clasificador_decisiones.json"
    _local_path = lambda: fake_path  # noqa: E731

    try:
        _cache["decisiones"] = None
        _cache["fetched_at"] = 0

        assert registrar_decision(sugerencia_id=1, decision="aceptar", decided_by="nico")
        pendientes = list_decisiones_pendientes()
        assert len(pendientes) == 1
        assert pendientes[0]["decision"] == "aceptar"
        print("OK registrar_decision: crea una decision nueva")

        # Cambiar de opinion antes de que se aplique - upsert, no duplica.
        registrar_decision(sugerencia_id=1, decision="rechazar", decided_by="nico")
        pendientes = list_decisiones_pendientes()
        assert len(pendientes) == 1, "no debe duplicar, debe actualizar la misma sugerencia_id"
        assert pendientes[0]["decision"] == "rechazar"
        print("OK registrar_decision: upsert por sugerencia_id (cambiar de opinion no duplica)")

        registrar_decision(sugerencia_id=2, decision="aceptar")
        assert len(list_decisiones_pendientes()) == 2

        limpiar_decisiones_aplicadas([1])
        pendientes = list_decisiones_pendientes()
        assert len(pendientes) == 1 and pendientes[0]["sugerencia_id"] == 2, (
            "limpiar_decisiones_aplicadas debe sacar solo la id procesada")
        print("OK limpiar_decisiones_aplicadas: saca solo las ids procesadas")
    finally:
        _local_path = old_local_path
        if old_token is not None:
            os.environ["GH_TOKEN"] = old_token


if __name__ == "__main__":
    _demo()
