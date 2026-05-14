"""Orquestación del sync: listado → diff → detalle → persist."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from scraper.api import ApiClient
from scraper.db import Database, now_iso

log = logging.getLogger(__name__)

PER_PAR_ID_ACTUAL = 2021  # período 2021-2026


@dataclass
class SyncStats:
    vistos: int = 0
    nuevos: int = 0
    actualizados: int = 0
    detail_fetches: int = 0
    errores: int = 0


def run_sync(
    db: Database,
    *,
    per_par_id: int = PER_PAR_ID_ACTUAL,
    full: bool = False,
    page_size: int = 200,
    max_proyectos: int | None = None,
    client: ApiClient | None = None,
) -> SyncStats:
    """Ejecuta un sync incremental.

    - Lista todos los proyectos del período (paginado).
    - Por cada uno: upsert con datos de la lista.
    - Si es nuevo, o el estado cambió, o `full=True`: llama al detalle y
      hace upsert de comisiones, firmantes, seguimientos, archivos.
    """
    client = client or ApiClient()
    stats = SyncStats()
    run_id = db.start_run()

    # bootstrap comisiones si está vacía
    if db.count_comisiones() == 0:
        comis = client.list_comisiones()
        db.upsert_comisiones(comis)
        log.info("Comisiones cargadas: %d", len(comis))

    try:
        for row in client.iter_proyectos(per_par_id, page_size=page_size):
            stats.vistos += 1
            now = now_iso()
            try:
                is_new, estado_changed = db.upsert_from_lista(row, now)
            except Exception as e:
                stats.errores += 1
                log.exception("Error en upsert de %s/%s: %s", row.get("perParId"), row.get("pleyNum"), e)
                continue

            if is_new:
                stats.nuevos += 1
            elif estado_changed:
                stats.actualizados += 1

            current = db.get_known(row["perParId"], row["pleyNum"])
            never_fetched = current is not None and current["detail_fetched_at"] is None
            need_detail = is_new or estado_changed or full or never_fetched
            if need_detail:
                try:
                    data = client.get_expediente(row["perParId"], row["pleyNum"])
                    db.upsert_detalle(row["perParId"], row["pleyNum"], data, now_iso())
                    stats.detail_fetches += 1
                except Exception as e:
                    stats.errores += 1
                    log.warning("Falló detalle de %s/%s: %s", row.get("perParId"), row.get("pleyNum"), e)

            if max_proyectos is not None and stats.vistos >= max_proyectos:
                log.info("Límite MAX_PROYECTOS=%d alcanzado, deteniendo.", max_proyectos)
                break

    finally:
        db.finish_run(
            run_id,
            vistos=stats.vistos, nuevos=stats.nuevos, actualizados=stats.actualizados,
            detail_fetches=stats.detail_fetches, errores=stats.errores,
            mensaje=("full" if full else "incremental"),
        )

    return stats


def env_max_proyectos() -> int | None:
    v = os.environ.get("MAX_PROYECTOS")
    return int(v) if v and v.isdigit() else None
