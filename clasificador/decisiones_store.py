"""Decisiones de la UI (aceptar/rechazar) sobre las sugerencias de
reclasificación, guardadas en data/clasificador_decisiones.json vía core.store.

La página abre proyectos.db en solo lectura y en Streamlit Cloud ese archivo
se borra en cada redeploy: la UI solo registra la decisión acá y
`clasificador.cli aplicar-decisiones` (en refrescar-pe.yml, con la base real)
la aplica y la saca del JSON.
"""
from __future__ import annotations

import json

from core import store
from core.db import now_iso

DECISIONES_PATH = "data/clasificador_decisiones.json"
CACHE_TTL_SECONDS = 30


def list_decisiones_pendientes() -> list[dict]:
    """Decisiones que `aplicar-decisiones` todavía no procesó (cache de 30s)."""
    return store.cargar(DECISIONES_PATH, [], ttl=CACHE_TTL_SECONDS)


def registrar_decision(*, sugerencia_id: int, decision: str, decided_by: str | None = None) -> bool:
    """decision: 'aceptar' o 'rechazar'. Upsert por sugerencia_id: si Nicolas
    cambia de opinión antes de que se aplique, gana la última."""
    assert decision in ("aceptar", "rechazar"), decision

    def cambio(decisiones: list[dict]) -> list[dict]:
        now = now_iso()
        existente = next((d for d in decisiones if d.get("sugerencia_id") == sugerencia_id), None)
        if existente:
            existente.update(decision=decision, decided_at=now, decided_by=decided_by)
        else:
            decisiones.append({"sugerencia_id": sugerencia_id, "decision": decision,
                               "decided_at": now, "decided_by": decided_by})
        return decisiones

    store.actualizar(DECISIONES_PATH, cambio,
                     f"clasificador: {decision} sugerencia {sugerencia_id}", [])
    return True


def limpiar_decisiones_aplicadas(sugerencia_ids: list[int]) -> None:
    """Saca del JSON local las decisiones ya aplicadas. Solo lo llama
    `aplicar-decisiones` en GitHub Actions, que commitea el archivo él mismo."""
    if not sugerencia_ids:
        return
    p = store.ROOT / DECISIONES_PATH
    quedan = [d for d in store._leer_local(DECISIONES_PATH, [])
              if d.get("sugerencia_id") not in set(sugerencia_ids)]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(quedan, ensure_ascii=False, indent=2), encoding="utf-8")
    store._cache.pop(DECISIONES_PATH, None)
