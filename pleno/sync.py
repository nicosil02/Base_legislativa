"""Orquestador del sync de agendas del Pleno: lista -> detalle -> persist con
cruce de PLs."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from pleno.api import ApiClient
from pleno.db import Database, now_iso
from pleno.parser import flatten_temas, parse_tema

log = logging.getLogger(__name__)


@dataclass
class SyncStats:
    vistas: int = 0
    nuevas: int = 0
    actualizadas: int = 0
    detail_fetches: int = 0
    errores: int = 0


def run_sync(
    db: Database,
    *,
    periodo_filtro: str | None = "2021-2026",
    full: bool = False,
    client: ApiClient | None = None,
    max_agendas: int | None = None,
) -> SyncStats:
    """Sync incremental:
      - Lista todas las agendas del Pleno del periodo (default: 2021-2026).
      - Por cada una: upsert con datos de la lista.
      - Si es nueva, cambio detectado, o `full=True`: llama al detalle y
        persiste temas + PLs cruzados.
    """
    client = client or ApiClient()
    stats = SyncStats()

    log.info("Listando agendas del Pleno (periodo=%s)...", periodo_filtro or "TODOS")
    agendas = client.list_agendas(periodo_filtro=periodo_filtro)
    log.info("Agendas devueltas: %d", len(agendas))

    run_id = db.start_run()
    try:
        for row in agendas:
            stats.vistas += 1
            now = now_iso()
            try:
                is_new, changed = db.upsert_from_lista(row, now)
            except Exception as e:
                stats.errores += 1
                log.exception("Error upsert agenda %s: %s", row.get("codAgenda"), e)
                continue
            if is_new:
                stats.nuevas += 1
            elif changed:
                stats.actualizadas += 1

            need_detail = is_new or changed or full
            if need_detail:
                try:
                    data = client.get_agenda(row["codAgenda"])
                    temas = flatten_temas(data)
                    temas_con_pls = []
                    for t in temas:
                        tema_row, pls = parse_tema(t)
                        temas_con_pls.append({"tema_row": tema_row, "pls": pls})
                    db.upsert_detalle(data, temas_con_pls, now_iso())
                    stats.detail_fetches += 1
                except Exception as e:
                    stats.errores += 1
                    log.warning("Fallo detalle agenda %s: %s", row.get("codAgenda"), e)

            if max_agendas is not None and stats.vistas >= max_agendas:
                log.info("Limite max_agendas=%d alcanzado, terminando", max_agendas)
                break
    finally:
        db.finish_run(
            run_id,
            vistas=stats.vistas, nuevas=stats.nuevas, actualizadas=stats.actualizadas,
            detail_fetches=stats.detail_fetches, errores=stats.errores,
            mensaje=("full" if full else "incremental"),
        )
    return stats
