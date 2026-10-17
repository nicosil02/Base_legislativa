"""Comisiones marcadas como "de interes" en `data/seguimiento_comisiones.json`
({"comisiones": [...], "updated_at": ...}), guardadas con core.store.

Se usa para resaltar en la Agenda las sesiones de esas comisiones y para que
el workflow de alertas sepa por cuales avisar.
"""
from __future__ import annotations

from core import store
from core.db import now_iso

SEGUIMIENTO_PATH = "data/seguimiento_comisiones.json"
CACHE_TTL_SECONDS = 30


def list_seguidas() -> set[str]:
    """Nombres de comision marcados como de interes (cache corto)."""
    data = store.cargar(SEGUIMIENTO_PATH, {"comisiones": []}, ttl=CACHE_TTL_SECONDS)
    return set(data.get("comisiones", []))


def set_seguidas(nombres: set[str] | list[str]) -> bool:
    """Reemplaza la lista completa (la UI manda el estado de todos los
    checkboxes de una vez)."""
    nuevo = {"comisiones": sorted(set(nombres)), "updated_at": now_iso()}
    store.actualizar(SEGUIMIENTO_PATH, lambda _: nuevo,
                     f"seguimiento: {len(nuevo['comisiones'])} comision(es) marcadas",
                     {"comisiones": []})
    return True
