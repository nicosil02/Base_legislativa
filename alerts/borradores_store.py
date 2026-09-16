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


def _upsert(*, cliente: str, item_id: str, item_tipo: str, pais: str,
            item_titulo: str, item_url: str | None, item_resumen: str | None,
            texto: str, estado: str, fuentes_adicionales: list[dict] | None = None,
            creado_por: str | None = None) -> bool:
    """Crea o actualiza una entrada. No pisa un `estado='borrador'` existente
    con datos de un marcado nuevo (ver `marcar_pendiente`) - solo
    `guardar_borrador` (texto real, escrito a mano o por el agente) puede
    pasar un item a `estado='borrador'`.

    `creado_por` (email de quien marco el item, ver auth/store.py) solo se
    setea al CREAR la entrada - un update (ej. el agente redactando, o
    guardar_borrador sin pasar creado_por) nunca lo pisa, para que la
    pagina de Borradores pueda filtrar "lo mio" por persona."""
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
        if estado == "pendiente" and existente.get("estado") == "borrador":
            # Ya redactado - marcarlo de nuevo no debe volverlo a "pendiente".
            return True
        existente["texto"] = texto
        existente["estado"] = estado
        existente["updated_at"] = now
        if item_resumen:
            existente["item_resumen"] = item_resumen
        if fuentes_adicionales:
            existente["fuentes_adicionales"] = fuentes_adicionales
    else:
        borradores.append({
            "cliente": cliente, "item_id": item_id, "item_tipo": item_tipo,
            "pais": pais, "item_titulo": item_titulo, "item_url": item_url,
            "item_resumen": item_resumen, "texto": texto, "estado": estado,
            "creado_por": creado_por,
            "fuentes_adicionales": fuentes_adicionales or [],
            "created_at": now, "updated_at": now,
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
        "message": f"alertas: {estado} {cliente}/{item_id}",
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


def guardar_borrador(*, cliente: str, item_id: str, item_tipo: str, pais: str,
                     item_titulo: str, item_url: str | None, texto: str,
                     item_resumen: str | None = None) -> bool:
    """Guarda un borrador YA REDACTADO (a mano en la UI, o por el agente
    programado) - estado='borrador'. Clave logica: (cliente, item_id)."""
    return _upsert(cliente=cliente, item_id=item_id, item_tipo=item_tipo,
                   pais=pais, item_titulo=item_titulo, item_url=item_url,
                   item_resumen=item_resumen, texto=texto, estado="borrador")


def marcar_pendiente(*, clientes: list[str], item_id: str, item_tipo: str, pais: str,
                     item_titulo: str, item_url: str | None,
                     item_resumen: str | None = None,
                     fuentes_adicionales: list[dict] | None = None,
                     creado_por: str | None = None) -> bool:
    """Un miembro del equipo marca un item (tipicamente desde Noticias PE/EC)
    como 'vale la pena redactar una alerta de esto' para uno o mas clientes -
    crea una entrada con estado='pendiente' y texto vacio por cada cliente.
    El agente programado busca estas entradas, las redacta, y las pasa a
    estado='borrador' via `guardar_borrador`. Si un item ya tiene un borrador
    real para ese cliente, no lo toca (ver `_upsert`).

    `creado_por` (opcional): email de quien marco el item (ver auth/store.py)
    - permite que la pagina de Borradores filtre "lo mio" por persona una
    vez que el login este activo. Sin login (auth no configurado todavia),
    queda en None y la pagina muestra todo, como antes.

    `fuentes_adicionales` (opcional): a veces varias noticias relacionadas se
    combinan en UNA sola alerta con mas perspectiva, pero solo se cita la
    fuente principal al final (asi lo hace el equipo, ver chat.txt) - lista de
    {"item_titulo", "item_url"} de contexto extra para que el agente los lea,
    sin citarlos."""
    ok = True
    for cliente in clientes:
        ok = _upsert(cliente=cliente, item_id=item_id, item_tipo=item_tipo,
                     pais=pais, item_titulo=item_titulo, item_url=item_url,
                     item_resumen=item_resumen, texto="", estado="pendiente",
                     fuentes_adicionales=fuentes_adicionales,
                     creado_por=creado_por) and ok
    return ok


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
        assert items[0]["estado"] == "borrador"
        print("OK guardar_borrador: crea y actualiza (upsert) correctamente")

        ok3 = marcar_pendiente(clientes=["bayer", "syngenta"], item_id="n_2",
                              item_tipo="noticia", pais="PE",
                              item_titulo="Otra noticia", item_url="http://y",
                              item_resumen="resumen crudo")
        assert ok3
        assert len(list_borradores("bayer")) == 2
        pendiente = next(b for b in list_borradores("syngenta") if b["item_id"] == "n_2")
        assert pendiente["estado"] == "pendiente" and pendiente["texto"] == ""
        print("OK marcar_pendiente: crea una entrada pendiente por cada cliente")

        marcar_pendiente(clientes=["bayer"], item_id="n_1", item_tipo="noticia",
                         pais="PE", item_titulo="Titulo de prueba", item_url="http://x")
        items = list_borradores("bayer")
        n1 = next(b for b in items if b["item_id"] == "n_1")
        assert n1["estado"] == "borrador" and n1["texto"] == "Version 2 editada", (
            "marcar un item que ya tiene borrador real NO debe pisarlo")
        print("OK marcar_pendiente: no pisa un borrador ya redactado")

        marcar_pendiente(clientes=["bayer"], item_id="n_3", item_tipo="noticia",
                         pais="PE", item_titulo="Noticia principal", item_url="http://z",
                         fuentes_adicionales=[{"item_titulo": "Otro angulo", "item_url": "http://w"}])
        n3 = next(b for b in list_borradores("bayer") if b["item_id"] == "n_3")
        assert n3["fuentes_adicionales"] == [{"item_titulo": "Otro angulo", "item_url": "http://w"}]
        print("OK marcar_pendiente: guarda fuentes_adicionales (varias noticias, una alerta)")

        marcar_pendiente(clientes=["syngenta"], item_id="n_4", item_tipo="noticia",
                         pais="PE", item_titulo="Noticia de otra persona", item_url="http://q",
                         creado_por="compañera@valiconsultores.com")
        n4 = next(b for b in list_borradores("syngenta") if b["item_id"] == "n_4")
        assert n4["creado_por"] == "compañera@valiconsultores.com"
        guardar_borrador(cliente="syngenta", item_id="n_4", item_tipo="noticia",
                         pais="PE", item_titulo="Noticia de otra persona", item_url="http://q",
                         texto="Texto redactado por el agente")
        n4 = next(b for b in list_borradores("syngenta") if b["item_id"] == "n_4")
        assert n4["creado_por"] == "compañera@valiconsultores.com", (
            "guardar_borrador (el agente redactando, sin creado_por) NO debe "
            "pisar el dueño original del item")
        print("OK creado_por: se setea al crear y no se pisa en updates posteriores")
    finally:
        _local_path = old_local_path
        if old_token is not None:
            _os.environ["GH_TOKEN"] = old_token


if __name__ == "__main__":
    _demo()
