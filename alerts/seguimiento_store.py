"""Comisiones marcadas como "de interes" por Nicolas - mismo backend que
alerts/borradores_store.py (GitHub Contents API), reusando las mismas env
vars (GH_TOKEN/GH_REPO/GH_BRANCH) ya configuradas para el login.

`data/seguimiento_comisiones.json` es la fuente de verdad: lista simple de
nombres de comision marcados como prioritarios. La pagina de Streamlit lee
la copia local (snapshot del ultimo deploy) y al guardar:
  1. Actualiza la copia local en memoria.
  2. PUT a la GitHub Contents API -> commit del nuevo json.
  3. Streamlit Cloud detecta el commit y redeploya (mismo flujo que
     alerts/borradores_store.py y auth/).

Se usa para (a) resaltar en la Agenda las sesiones de comisiones de interes,
y (b) que el workflow de alertas sepa por cuales mandar WhatsApp.
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

SEGUIMIENTO_PATH = "data/seguimiento_comisiones.json"
CACHE_TTL_SECONDS = 30
_cache = {"comisiones": None, "fetched_at": 0}


def _local_path() -> Path:
    return Path(__file__).resolve().parent.parent / SEGUIMIENTO_PATH


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
        + "/contents/" + SEGUIMIENTO_PATH
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
        return {"data": json.loads(body), "sha": data.get("sha")}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"data": {"comisiones": []}, "sha": None}
        return None
    except Exception:
        return None


def _read_local() -> dict:
    p = _local_path()
    if not p.exists():
        return {"data": {"comisiones": []}, "sha": None}
    try:
        return {"data": json.loads(p.read_text(encoding="utf-8")), "sha": None}
    except Exception:
        return {"data": {"comisiones": []}, "sha": None}


def list_seguidas() -> set[str]:
    """Nombres de comision marcados como de interes. Cache corto (30s)
    para no golpear la API de GitHub en cada rerun de Streamlit."""
    now = time.time()
    if _cache["comisiones"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        state = _cache["comisiones"]
    else:
        state = _fetch_remote() or _read_local()
        _cache["comisiones"] = state
        _cache["fetched_at"] = now
    return set(state["data"].get("comisiones", []))


def set_seguidas(nombres: set[str] | list[str]) -> bool:
    """Reemplaza la lista completa de comisiones seguidas (la UI manda un
    checkbox-state completo de una, no upserts individuales)."""
    cfg = _gh_config()
    usar_gh = bool(cfg["token"] and cfg["repo"])
    remote = _fetch_remote() if usar_gh else None
    state = remote or _read_local()

    nuevo = {"comisiones": sorted(set(nombres)), "updated_at": _now_iso()}
    new_content = json.dumps(nuevo, ensure_ascii=False, indent=2)

    if not usar_gh:
        p = _local_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_content, encoding="utf-8")
        _cache["comisiones"] = {"data": nuevo, "sha": None}
        _cache["fetched_at"] = time.time()
        return True

    body = {
        "message": f"seguimiento: {len(nuevo['comisiones'])} comision(es) marcadas",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": cfg["branch"],
    }
    if state.get("sha"):
        body["sha"] = state["sha"]
    url = "https://api.github.com/repos/" + cfg["repo"] + "/contents/" + SEGUIMIENTO_PATH
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="PUT",
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
    _cache["comisiones"] = None
    _cache["fetched_at"] = 0
    return True


def _demo():
    """Self-check sin red: sin GH_TOKEN, set_seguidas/list_seguidas deben
    funcionar via archivo local (fallback ya usado por borradores_store)."""
    import tempfile
    from unittest.mock import patch

    saved = os.environ.pop("GH_TOKEN", None)
    try:
        with tempfile.TemporaryDirectory() as td:
            fake_path = Path(td) / "data" / "seguimiento_comisiones.json"
            with patch(__name__ + "._local_path", lambda: fake_path):
                global _cache
                _cache = {"comisiones": None, "fetched_at": 0}
                assert list_seguidas() == set()
                set_seguidas({"Comision: Salud", "Comision: Economia"})
                _cache = {"comisiones": None, "fetched_at": 0}
                assert list_seguidas() == {"Comision: Salud", "Comision: Economia"}
    finally:
        if saved is not None:
            os.environ["GH_TOKEN"] = saved
    print("OK seguimiento_store: guarda y lee via fallback local sin GH_TOKEN")


if __name__ == "__main__":
    _demo()
