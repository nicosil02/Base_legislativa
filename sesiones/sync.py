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


CAMARA_LABEL = {"C": "Congreso", "D": "Diputados", "S": "Senado"}


def _comisiones_del_periodo(criterios: dict, per_par_id: int) -> list[tuple[int, str | None]]:
    """(comisionId, camara) de cada comision del periodo pedido, del catalogo
    /criterios.

    Bug real 2026-09-16: la version anterior mapeaba nombreComision ->
    camara, pero el MISMO nombre se repite en Senado y Diputados para casi
    todas las comisiones ordinarias (es como funciona un Congreso bicameral -
    "verificado 2026-09-11: 4 de 30 colisionan" resulto estar mal medido,
    en la practica eran 2209 de 2274 sesiones con camara=NULL). Un nombre
    NUNCA alcanza para distinguir camara.

    El fix real: /sesiones/busqueda acepta el parametro `comision` con el
    comisionId EXACTO (no el nombre) y devuelve solo las sesiones de ESA
    comision especifica - verificado en vivo que pedir sesion por sesion
    por comisionId (31 comisiones en perParId=2026) cubre el 100% de lo que
    devuelve un pedido sin filtro (91 de 91 sesiones), sin ambiguedad
    posible: la camara la sabemos porque nosotros elegimos con que
    comisionId pedimos, no porque la reconstruyamos despues del nombre."""
    return [
        (c["comisionId"], CAMARA_LABEL.get(c.get("codTipoParl")))
        for c in criterios.get("comisiones", [])
        if c.get("perParId") == per_par_id
    ]


def run_sync(
    db: Database,
    *,
    periodo_parlamentario: int = 2026,  # 2026-2031, Congreso bicameral vigente
    periodo_legislativo: int = 2026,
    full: bool = False,
    client: ApiClient | None = None,
    max_sesiones: int | None = None,
) -> SyncStats:
    """Sync incremental:
    - Lista las sesiones del periodo legislativo, UNA COMISION A LA VEZ (ver
      _comisiones_del_periodo - es lo que permite saber la camara sin
      ambiguedad, en vez de un pedido masivo que despues no se puede
      desambiguar por nombre)
    - Por cada una: upsert con datos de la lista
    - Si es nueva, cambio de estado, o `full=True`: llama al detalle y persiste
      agenda + PLs cruzados.
    """
    client = client or ApiClient()
    stats = SyncStats()

    log.info("Cargando catalogo de comisiones...")
    crit = client.get_criterios()
    comisiones = _comisiones_del_periodo(crit, periodo_parlamentario)
    log.info("Comisiones del periodo %d: %d", periodo_parlamentario, len(comisiones))

    log.info("Listando sesiones por comision (per_par=%d per_leg=%d)...",
             periodo_parlamentario, periodo_legislativo)
    sesiones: list[dict] = []
    vistos: set[int] = set()
    camara_por_sesion: dict[int, tuple[int, str | None]] = {}
    for comision_id, camara in comisiones:
        rows = client.list_sesiones(
            periodo_parlamentario=periodo_parlamentario,
            periodo_legislativo=periodo_legislativo,
            comision=comision_id,
        )
        for r in rows:
            id_sesion = r["idSesion"]
            if id_sesion in vistos:
                continue
            vistos.add(id_sesion)
            camara_por_sesion[id_sesion] = (comision_id, camara)
            sesiones.append(r)
    log.info("Sesiones devueltas: %d", len(sesiones))

    run_id = db.start_run()
    try:
        for row in sesiones:
            stats.vistas += 1
            now = now_iso()
            comision_id, camara = camara_por_sesion.get(row["idSesion"], (None, None))
            try:
                is_new, estado_changed = db.upsert_from_lista(row, comision_id, camara, now)
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
