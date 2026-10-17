"""Orquestación del sync: listado → diff → detalle → persist."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from scraper.api import ApiClient
from scraper.db import Database, now_iso

log = logging.getLogger(__name__)

PERIODO_UNICAMERAL_2021 = 2021    # período 2021-2026, Congreso unicameral (cerrado 2026-07-26)
PER_PAR_ID_ACTUAL = 2026          # período 2026-2031, Congreso bicameral (Senado + Cámara de Diputados)

# Instalación del Congreso bicameral: corte para los módulos sin per_par_id.
FECHA_INICIO_BICAMERAL = "2026-07-27"

# Solo el período vigente (pedido de Nicolas): el 2021 queda en la DB sin tocar.
PERIODOS_SYNC: tuple[int, ...] = (PER_PAR_ID_ACTUAL,)

# Sin codTipoParl el API devuelve solo 'C': hay que pedir cada cámara.
CAMARAS_BICAMERAL: tuple[str, ...] = ("C", "D", "S")


def camaras_de(per_par_id: int) -> tuple[str | None, ...]:
    """Cámaras de un período; el legacy (< 2026) no filtra (None)."""
    if per_par_id >= 2026:
        return CAMARAS_BICAMERAL
    return (None,)


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
    cod_tipo_parl: str | None = None,
    full: bool = False,
    page_size: int = 200,
    max_proyectos: int | None = None,
    client: ApiClient | None = None,
) -> SyncStats:
    """Sync incremental de UNA cámara de un período: upsert de la lista y
    detalle solo para nuevos, con cambio de estado, sin detalle o `full`."""
    client = client or ApiClient()
    stats = SyncStats()
    run_id = db.start_run()

    # bootstrap comisiones si está vacía
    if db.count_comisiones() == 0:
        comis = client.list_comisiones()
        db.upsert_comisiones(comis)
        log.info("Comisiones cargadas: %d", len(comis))

    try:
        for row in client.iter_proyectos(per_par_id, cod_tipo_parl=cod_tipo_parl, page_size=page_size):
            stats.vistos += 1
            now = now_iso()
            # Se guarda la cámara que trae la fila, no la del filtro.
            row_cam = row.get("codTipoParl") or cod_tipo_parl or "C"
            try:
                is_new, estado_changed = db.upsert_from_lista(row, now)
            except Exception as e:
                stats.errores += 1
                log.exception("Error en upsert de %s/%s/%s: %s", row.get("perParId"), row_cam, row.get("pleyNum"), e)
                continue

            if is_new:
                stats.nuevos += 1
            elif estado_changed:
                stats.actualizados += 1

            current = db.get_known(row["perParId"], row_cam, row["pleyNum"])
            never_fetched = current is not None and current["detail_fetched_at"] is None
            need_detail = is_new or estado_changed or full or never_fetched
            if need_detail:
                try:
                    data = client.get_expediente(row["perParId"], row["pleyNum"], cod_tipo_parl=row_cam)
                    db.upsert_detalle(row["perParId"], row_cam, row["pleyNum"], data, now_iso())
                    stats.detail_fetches += 1
                except Exception as e:
                    stats.errores += 1
                    log.warning("Falló detalle de %s/%s/%s: %s", row.get("perParId"), row_cam, row.get("pleyNum"), e)

            if max_proyectos is not None and stats.vistos >= max_proyectos:
                log.info("Límite de %d proyectos alcanzado, deteniendo.", max_proyectos)
                break

    finally:
        db.finish_run(
            run_id,
            vistos=stats.vistos, nuevos=stats.nuevos, actualizados=stats.actualizados,
            detail_fetches=stats.detail_fetches, errores=stats.errores,
            mensaje=("full" if full else "incremental") + (f" cam={cod_tipo_parl}" if cod_tipo_parl else ""),
        )

    return stats


def run_sync_periodos(
    db: Database,
    *,
    full: bool = False,
    page_size: int = 200,
    max_proyectos: int | None = None,
    client: ApiClient | None = None,
) -> dict[tuple[int, str], SyncStats]:
    """`run_sync` por cada (período, cámara) de PERIODOS_SYNC, con stats
    por `(per_par_id, cámara)`, ej. `(2026, 'D')`."""
    client = client or ApiClient()
    out: dict[tuple[int, str], SyncStats] = {}
    for per_par_id in PERIODOS_SYNC:
        for cam in camaras_de(per_par_id):
            out[(per_par_id, cam or "C")] = run_sync(
                db, per_par_id=per_par_id, cod_tipo_parl=cam, full=full, page_size=page_size,
                max_proyectos=max_proyectos, client=client,
            )
    return out

