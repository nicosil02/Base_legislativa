"""Descartes de noticias (boton "Descartar" de las paginas Noticias PE/EC).

Las paginas abren proyectos.db en solo lectura y en Streamlit Cloud esa base
se reconstruye en cada redeploy, asi que los descartes van a un JSON del
repo (data/noticias_feedback.json) via core.store, y load_noticias() excluye
esos ids.
"""
from __future__ import annotations

from core import store
from core.db import now_iso

FEEDBACK_PATH = "data/noticias_feedback.json"
# Noticias juntadas con "Combinar": etiquetas humanas de "mismo hecho"
# (noticias/mismo_hecho.py las usa para entrenar y le ganan al modelo).
COMBINADAS_PATH = "data/noticias_combinadas.json"
CACHE_TTL_SECONDS = 30


def list_descartadas() -> set[int]:
    """IDs de noticias descartadas desde la UI. Cache corto para no golpear
    la API de GitHub en cada rerun de Streamlit."""
    return {int(d["noticia_id"]) for d in store.cargar(FEEDBACK_PATH, [], ttl=CACHE_TTL_SECONDS)}


def registrar_descarte(noticia_id: int, descartado_por: str | None = None) -> bool:
    """Idempotente: descartar 2 veces la misma noticia no duplica."""
    def cambio(descartes: list) -> list | None:
        if any(d.get("noticia_id") == noticia_id for d in descartes):
            return None
        return descartes + [{"noticia_id": int(noticia_id), "created_at": now_iso(),
                             "descartado_por": descartado_por}]
    store.actualizar(FEEDBACK_PATH, cambio, f"noticias: descartar {noticia_id}", [])
    return True


def deshacer_descarte(noticia_id: int) -> bool:
    """Undo de registrar_descarte(). Si ya no estaba descartada, no hace nada."""
    def cambio(descartes: list) -> list | None:
        nuevos = [d for d in descartes if d.get("noticia_id") != noticia_id]
        return nuevos if len(nuevos) != len(descartes) else None
    store.actualizar(FEEDBACK_PATH, cambio, f"noticias: deshacer descarte {noticia_id}", [])
    return True


def registrar_combinadas(ids: list[int], por: str | None = None) -> None:
    ids = sorted({int(i) for i in ids})
    if len(ids) < 2:
        return
    store.actualizar(COMBINADAS_PATH, lambda grupos: grupos + [
        {"ids": ids, "created_at": now_iso(), "por": por}], f"noticias: combinadas {ids}", [])
