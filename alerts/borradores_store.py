"""Almacenamiento de borradores de alertas — mismo backend que auth/store.py
(GitHub Contents API), reusando las mismas env vars (GH_TOKEN/GH_REPO/GH_BRANCH)
que ya estan configuradas como secret para el login.

`data/alertas_borradores.json` es la fuente de verdad. La pagina de Streamlit
lee la copia local (snapshot del ultimo deploy), y al guardar:
  1. Actualiza la copia local en memoria.
  2. PUT a la GitHub Contents API -> commit del nuevo json.
  3. Streamlit Cloud detecta el commit y redeploya (mismo flujo que auth/).

OJO (decision explicita de Nicolas, 2026-09-12): este repo es publico, y este
archivo SI queda en el historial de git (a diferencia de clientes/, que esta
gitignoreado) - Nicolas confirmo que por ahora no hay problema con eso.
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


BORRADORES_PATH = "data/alertas_borradores.json"
CACHE_TTL_SECONDS = 30
_cache = {"borradores": None, "fetched_at": 0}


def _local_path():
    return Path(__file__).resolve().parent.parent / BORRADORES_PATH


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_config():
    return {
        "token": os.environ.get("GH_TOKEN"),
        "repo": os.environ.get("GH_REPO"),
        "branch": os.environ.get("GH_BRANCH", "main"),
    }


def _fetch_remote():
    cfg = _gh_config()
    if not cfg["token"] or not cfg["repo"]:
        return None
    url = (
        "https://api.github.com/repos/" + cfg["repo"]
        + "/contents/" + BORRADORES_PATH
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
        content_b64 = data.get("content", "")
        sha = data.get("sha")
        body = base64.b64decode(content_b64).decode("utf-8")
        return {"borradores": json.loads(body), "sha": sha}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"borradores": [], "sha": None}
        return None
    except Exception:
        return None


def _read_local():
    p = _local_path()
    if not p.exists():
        return {"borradores": [], "sha": None}
    try:
        return {"borradores": json.loads(p.read_text(encoding="utf-8")), "sha": None}
    except Exception:
        return {"borradores": [], "sha": None}


def list_borradores(cliente: str | None = None) -> list[dict]:
    """Devuelve los borradores guardados, mas nuevos primero. Cache corto
    (30s) para no golpear la API de GitHub en cada rerun de Streamlit."""
    now = time.time()
    if _cache["borradores"] is not None and (now - _cache["fetched_at"]) < CACHE_TTL_SECONDS:
        state = _cache["borradores"]
    else:
        state = _fetch_remote() or _read_local()
        _cache["borradores"] = state
        _cache["fetched_at"] = now
    items = state["borradores"]
    if cliente:
        items = [b for b in items if b.get("cliente") == cliente]
    return sorted(items, key=lambda b: b.get("updated_at", ""), reverse=True)


def guardar_borrador(*, cliente: str, item_id: str, item_tipo: str, pais: str,
                     item_titulo: str, item_url: str | None, texto: str) -> bool:
    """Guarda (crea o actualiza) el borrador de un item para un cliente.
    Clave logica: (cliente, item_id). Devuelve True si commiteo/guardo ok."""
    cfg = _gh_config()
    usar_gh = bool(cfg["token"] and cfg["repo"])
    remote = _fetch_remote() if usar_gh else None
    state = remote or _read_local()
    borradores = state["borradores"]
    now = _now_iso()

    existente = next(
        (b for b in borradores if b.get("cliente") == cliente and b.get("item_id") == item_id),
        None,
    )
    if existente:
        existente["texto"] = texto
        existente["updated_at"] = now
    else:
        borradores.append({
            "cliente": cliente, "item_id": item_id, "item_tipo": item_tipo,
            "pais": pais, "item_titulo": item_titulo, "item_url": item_url,
            "texto": texto, "created_at": now, "updated_at": now,
        })

    new_content = json.dumps(borradores, ensure_ascii=False, indent=2)

    if not usar_gh:
        p = _local_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_content, encoding="utf-8")
        _cache["borradores"] = {"borradores": borradores, "sha": None}
        _cache["fetched_at"] = time.time()
        return True

    body = {
        "message": f"alertas: borrador {cliente}/{item_id}",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
        "branch": cfg["branch"],
    }
    if state.get("sha"):
        body["sha"] = state["sha"]
    url = "https://api.github.com/repos/" + cfg["repo"] + "/contents/" + BORRADORES_PATH
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
    _cache["borradores"] = None
    _cache["fetched_at"] = 0
    return True


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    """Simula guardar/actualizar un borrador sin tocar GitHub (fuerza modo
    local seteando GH_TOKEN vacio)."""
    import tempfile, os as _os
    global _local_path

    old_token = _os.environ.pop("GH_TOKEN", None)
    old_local_path = _local_path
    tmpdir = tempfile.mkdtemp()
    fake_path = Path(tmpdir) / "data" / "alertas_borradores.json"
    _local_path = lambda: fake_path  # noqa: E731

    try:
        _cache["borradores"] = None
        _cache["fetched_at"] = 0
        ok1 = guardar_borrador(cliente="bayer", item_id="n_1", item_tipo="noticia",
                               pais="PE", item_titulo="Titulo de prueba",
                               item_url="http://x", texto="Version 1")
        assert ok1, "guardar_borrador debio devolver True"
        items = list_borradores("bayer")
        assert len(items) == 1, f"esperaba 1 borrador, hay {len(items)}"
        assert items[0]["texto"] == "Version 1"

        ok2 = guardar_borrador(cliente="bayer", item_id="n_1", item_tipo="noticia",
                               pais="PE", item_titulo="Titulo de prueba",
                               item_url="http://x", texto="Version 2 editada")
        assert ok2
        items = list_borradores("bayer")
        assert len(items) == 1, "actualizar un borrador existente no debe crear uno nuevo"
        assert items[0]["texto"] == "Version 2 editada"
        print("OK guardar_borrador: crea y actualiza (upsert) correctamente")
    finally:
        _local_path = old_local_path
        if old_token is not None:
            _os.environ["GH_TOKEN"] = old_token


if __name__ == "__main__":
    _demo()
