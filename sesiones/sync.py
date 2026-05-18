"""Orquestador del sync de sesiones: lista -> detalle -> persist con cruce PLs."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sesiones.agenda_parser import parse_agenda_punto
from sesiones.api import ApiClient
from sesiones.db import Database, now_iso

log = logging.getLogger(__name__)


@dataclass
class SyncStats:
    vistas: int = 0
    nuevas: int = 0
    actualizadas: int = 0
    detail_fetches: int = 0
    errores: int = 0


def _build_comision_id_map(criterios: dict) -> dict[str, int]:
    """Mapea nombreComision -> comisionId del catalogo /criterios."""
    return {c["nombreComision"]: c["comisionId"] for c in criterios.get("comisiones", [])}


def run_sync(
    db: Database,
    *,
    periodo_parlamentario: int = 2021,
    periodo_legislativo: int = 2025,
    full: bool = False,
    client: ApiClient | None = None,
    max_sesiones: int | None = None,
) -> SyncStats:
    """Sync incremental:
    - Lista todas las sesiones del periodo legislativo
    - Por cada una: upsert con datos de la lista
    - Si es nueva, cambio de estado, o `full=True`: llama al detalle y persiste
      agenda + PLs cruzados.
    """
    client = client or ApiClient()
    stats = SyncStats()

    log.info("Cargando catalogo de comisiones...")
    crit = client.get_criterios()
    comision_id_map = _build_comision_id_map(crit)
    log.info("Comisiones en catalogo: %d", len(comision_id_map))

    log.info("Listando sesiones (per_par=%d per_leg=%d)...", periodo_parlamentario, periodo_legislativo)
    sesiones = client.list_sesiones(
        periodo_parlamentario=periodo_parlamentario,
        periodo_legislativo=periodo_legislativo,
    )
    log.info("Sesiones devueltas: %d", len(sesiones))

    run_id = db.start_run()
    try:
        for row in sesiones:
            stats.vistas += 1
            now = now_iso()
            try:
                is_new, estado_changed = db.upsert_from_lista(row, comision_id_map, now)
            except Exception as e:
                stats.errores += 1
                log.exception("Error upsert sesion %s: %s", row.get("idSesion"), e)
                continue
            if is_new:
                stats.nuevas += 1
            elif estado_changed:
                stats.actualizadas += 1

            need_detail = is_new or estado_changed or full
            if need_detail:
                try:
                    data = client.get_sesion(row["idSesion"])
                    pls_por_punto = _extract_pls_from_detalle(data)
                    db.upsert_detalle(data, pls_por_punto, now_iso())
                    stats.detail_fetches += 1
                except Exception as e:
                    stats.errores += 1
                    log.warning("Fallo detalle sesion %s: %s", row.get("idSesion"), e)

            if max_sesiones is not None and stats.vistas >= max_sesiones:
                log.info("Limite max_sesiones=%d alcanzado, terminando", max_sesiones)
                break
    finally:
        db.finish_run(
            run_id,
            vistas=stats.vistas, nuevas=stats.nuevas, actualizadas=stats.actualizadas,
            detail_fetches=stats.detail_fetches, errores=stats.errores,
            mensaje=("full" if full else "incremental"),
        )
    return stats


def _extract_pls_from_detalle(data: dict) -> dict[int, list[dict]]:
    """Recorre todos los puntos del orden del dia, parsea HTML, extrae PLs.

    Returns dict {idAgendaOrdenDia: [{pley_num, raw, contexto, ...}, ...]}.
    Tambien deja `_texto_plano` en cada punto para que upsert_detalle lo persista
    en sesion_agenda_punto.descripcion_texto.
    """
    agenda = data.get("agenda") or {}
    ordenes = agenda.get("ordenesDia") or []
    result: dict[int, list[dict]] = {}
    for p in ordenes:
        id_orden = p.get("idAgendaOrdenDia")
        if id_orden is None:
            continue
        texto, pls = parse_agenda_punto(p.get("descripcion"))
        p["_texto_plano"] = texto  # se persiste despues
        result[id_orden] = pls
    return result
