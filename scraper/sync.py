"""Orquestación del sync: listado → diff → detalle → persist."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from scraper.api import ApiClient
from scraper.db import Database, now_iso

log = logging.getLogger(__name__)

PERIODO_UNICAMERAL_2021 = 2021    # período 2021-2026, Congreso unicameral (cerrado 2026-07-26)
PER_PAR_ID_ACTUAL = 2026          # período 2026-2031, Congreso bicameral (Senado + Cámara de Diputados)

# Períodos que el sync recorre en cada corrida. Por pedido explícito de
# Nicolas (2026-09-11): solo el período vigente — nada de re-sincronizar el
# 2021 (cerrado, legislativamente muerto). La data 2021 ya recolectada queda
# en la DB para consulta histórica, simplemente no se vuelve a tocar.
PERIODOS_SYNC: tuple[int, ...] = (PER_PAR_ID_ACTUAL,)

# Cámaras del período bicameral. El API IGNORA la distinción de cámara si no
# se pide explícito: {perParId:2026} sin más devuelve SOLO 'C' (verificado
# 2026-09-11: 4 PLs). Con codTipoParl='D' salen 195, con 'S' salen 7 — sin
# esto el scraper estaba viendo el 2% de lo que existe de verdad. Cada
# cámara reinicia su numeración desde 1 (D-1 y S-1 y C-1 son PLs distintos).
CAMARAS_BICAMERAL: tuple[str, ...] = ("C", "D", "S")


def camaras_de(per_par_id: int) -> tuple[str | None, ...]:
    """Cámaras a sincronizar para un período dado. El período legacy
    (< 2026) no tiene esta distinción — pasar cod_tipo_parl=None (sin
    filtro) trae todo, igual que siempre."""
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
    """Ejecuta un sync incremental para UNA cámara de un período.

    - Lista todos los proyectos del período+cámara (paginado).
    - Por cada uno: upsert con datos de la lista.
    - Si es nuevo, o el estado cambió, o `full=True`: llama al detalle y
      hace upsert de comisiones, firmantes, seguimientos, archivos.

    `cod_tipo_parl`: 'C'/'D'/'S' para filtrar la lista por cámara (período
    bicameral), o None para no filtrar (período legacy — todo es 'C' igual).
    Usar `run_sync_periodos` para recorrer todas las cámaras de un período.
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
        for row in client.iter_proyectos(per_par_id, cod_tipo_parl=cod_tipo_parl, page_size=page_size):
            stats.vistos += 1
            now = now_iso()
            # codTipoParl real de la fila (la API lo devuelve siempre, filtres
            # o no) — es lo que se guarda; cod_tipo_parl del filtro es solo el
            # pedido, no necesariamente igual (por seguridad, no asumimos).
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
                log.info("Límite MAX_PROYECTOS=%d alcanzado, deteniendo.", max_proyectos)
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
    periodos: tuple[int, ...] = PERIODOS_SYNC,
    full: bool = False,
    page_size: int = 200,
    max_proyectos: int | None = None,
    client: ApiClient | None = None,
) -> dict[tuple[int, str], SyncStats]:
    """Corre `run_sync` para cada (período, cámara) y devuelve sus stats,
    keyed por `(per_par_id, cod_tipo_parl_efectivo)` — ej. `(2026, 'D')`.

    Usar esto (no `run_sync` directo) en el cron/CLI — así un período nuevo
    (ej. el cambio a bicameral) o una cámara nueva no requiere tocar más que
    `PERIODOS_SYNC`/`CAMARAS_BICAMERAL` arriba.
    """
    client = client or ApiClient()
    out: dict[tuple[int, str], SyncStats] = {}
    for per_par_id in periodos:
        for cam in camaras_de(per_par_id):
            out[(per_par_id, cam or "C")] = run_sync(
                db, per_par_id=per_par_id, cod_tipo_parl=cam, full=full, page_size=page_size,
                max_proyectos=max_proyectos, client=client,
            )
    return out


def env_max_proyectos() -> int | None:
    v = os.environ.get("MAX_PROYECTOS")
    return int(v) if v and v.isdigit() else None
