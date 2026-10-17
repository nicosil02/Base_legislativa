"""Datos de la pagina Ecuador (PL de la Asamblea): catalogos, KPIs, evolucion y proyectos."""
from __future__ import annotations

import datetime as dt
import sqlite3
import pandas as pd
import streamlit as st
from noticias.avances_ec import noticias_tramite_recientes
from consultas import base, conexion

# Instalación de la Asamblea Nacional del período vigente 2025-2029 -
# equivalente a FECHA_INICIO_BICAMERAL en scraper/sync.py para Perú.
# Ecuador no tiene un per_par_id que aisle el periodo vigente de
# legislaturas viejas en la tabla `proyectos` (a diferencia de Perú), así
# que las queries que deben acotarse al periodo actual (ej. el gráfico de
# "Evolución mensual") usan esta constante en vez de un string suelto.
FECHA_INICIO_PERIODO = "2025-05-14"


def get_conn() -> sqlite3.Connection:
    return conexion('proyectos_ec.db', 'Inicializá la DB con `python -m scraper_ec.cli init` y `python -m scraper_ec.cli importar-csv data/ppless_listado_2025-2029_snapshot.csv`.')


@st.cache_data(ttl=300)
def _noticias_tramite_recientes() -> list[dict]:
    db_path = base("proyectos.db")
    if not db_path:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return noticias_tramite_recientes(conn, dias=10)
    finally:
        conn.close()

@st.cache_data(ttl=300)
def documentos_hoy() -> tuple[int, int]:
    """(PLs hoy, noticias hoy) - gap real vs Dapper identificado 2026-09-20
    (ver memoria dapper-gap-analysis): ellos muestran un contador de
    "documentos publicados hoy" en el dashboard. Dato barato, ya lo
    tenemos - solo faltaba mostrarlo.

    Antes se sumaban en un solo numero ("Nuevos hoy") al lado de metricas
    puras de PL - hallazgo real de critique 2026-09-22, ver pages/1_Peru.py
    para el detalle. Separado en 2 tiles, mismo fix que Peru."""
    conn = get_conn()
    pls_hoy = conn.execute(
        "SELECT COUNT(*) FROM proyectos WHERE date(first_seen_at)=date('now')"
    ).fetchone()[0]
    noticias_hoy = 0
    db_noticias = base("proyectos.db")
    if db_noticias:
        nconn = sqlite3.connect(f"file:{db_noticias}?mode=ro", uri=True)
        try:
            noticias_hoy = nconn.execute(
                "SELECT COUNT(*) FROM noticias n JOIN noticias_fuentes f ON f.id=n.fuente_id "
                "WHERE f.pais='EC' AND date(n.first_seen_at)=date('now')"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            pass
        finally:
            nconn.close()
    return pls_hoy, noticias_hoy

@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    temas = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT tema FROM proyectos WHERE tema IS NOT NULL"))
    estados = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT estado FROM proyectos WHERE estado IS NOT NULL"))
    tipos = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT tipo_proponente FROM proyectos WHERE tipo_proponente IS NOT NULL"))
    comisiones = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT comision_asignada FROM proyectos "
        "WHERE comision_asignada IS NOT NULL AND comision_asignada NOT IN ('No Asignado', 'No se Asigna Comisión por calificación Negada')"))
    fec_min, fec_max = conn.execute(
        "SELECT MIN(date(fec_presentacion)), MAX(date(fec_presentacion)) FROM proyectos"
    ).fetchone()
    return {
        "temas": temas, "estados": estados,
        "tipos_proponente": tipos, "comisiones": comisiones,
        "fec_min": fec_min, "fec_max": fec_max,
    }

@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    conn = get_conn()
    r = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN UPPER(estado) = 'PROYECTO PRESENTADO' THEN 1 ELSE 0 END) AS presentados,
             SUM(CASE WHEN UPPER(estado) LIKE '%CALIFICACI%CONSEJO%' THEN 1 ELSE 0 END) AS en_cal,
             SUM(CASE WHEN UPPER(estado) LIKE '%AVOCO%' OR UPPER(estado) LIKE '%INFORME NO VINCULANTE%' THEN 1 ELSE 0 END) AS en_comision,
             SUM(CASE WHEN UPPER(estado) LIKE '%PRIMER DEBATE%' OR UPPER(estado) LIKE '%SEGUNDO DEBATE%' OR UPPER(estado) LIKE '%REMISI%EJECUTIVO%' THEN 1 ELSE 0 END) AS en_debate,
             SUM(CASE WHEN UPPER(estado) = 'REGISTRO OFICIAL' THEN 1 ELSE 0 END) AS publicados
           FROM proyectos"""
    ).fetchone()
    return {
        "Total": r["total"] or 0,
        "Presentados": r["presentados"] or 0,
        "En CAL": r["en_cal"] or 0,
        "En comisión": r["en_comision"] or 0,
        "En debate": r["en_debate"] or 0,
        "Publicados": r["publicados"] or 0,
    }

@st.cache_data(ttl=300)
def evolucion_mensual() -> pd.DataFrame:
    """PLs presentados y publicados en Registro Oficial por mes - mismo
    grafico que pages/1_Peru.py, inspirado en "Evolucion mensual" de
    Quals (pedido explicito de Nicolas 2026-09-22: no su paleta, solo la
    idea). "Publicados" usa last_changed_at como proxy del mes de
    publicacion - no hay historial completo de cambios de estado.

    Acotado a FECHA_INICIO_PERIODO (arranque real del periodo 2025-2029)
    - a diferencia de Peru, la tabla de Ecuador no tiene un per_par_id
    que aisle el periodo vigente de legislaturas viejas. Sin este corte,
    entraban filas con fec_presentacion en 1900-01-01 (dato faltante/
    default) y un historial disperso hasta 2015 - hallazgo real
    probando la query, hacia el grafico ilegible."""
    conn = get_conn()
    presentados = pd.read_sql_query(
        """SELECT date(fec_presentacion, 'start of month') AS mes,
                  COUNT(*) AS "Presentados"
           FROM proyectos WHERE fec_presentacion >= ?
           GROUP BY mes""",
        conn, params=(FECHA_INICIO_PERIODO,),
    )
    publicados = pd.read_sql_query(
        """SELECT date(last_changed_at, 'start of month') AS mes,
                  COUNT(*) AS "Publicados"
           FROM proyectos WHERE UPPER(estado) = 'REGISTRO OFICIAL'
                 AND fec_presentacion >= ?
           GROUP BY mes""",
        conn, params=(FECHA_INICIO_PERIODO,),
    )
    df = pd.merge(presentados, publicados, on="mes", how="outer").fillna(0)
    if df.empty:
        return df
    df = df.sort_values("mes").set_index("mes")
    df.index.name = "Mes"
    return df.astype(int)

@st.cache_data(ttl=60)
def last_sync() -> dict | None:
    """Devuelve info de la ultima actualizacion.

    Prioridad: heartbeat del workflow (corre cada 4h aunque no haya
    cambios) → fallback a sync_runs (escrito solo si hubo cambios).
    El segundo puede ser de hace varios dias si los datos no cambiaron.
    """
    conn = get_conn()
    # 1) Heartbeat del workflow (mas fresco, refleja "el workflow corrio")
    try:
        r = conn.execute(
            "SELECT last_run, last_status FROM system_heartbeats "
            "WHERE source = 'ec_proyectos'"
        ).fetchone()
        if r:
            return {"finished_at": r[0], "started_at": r[0],
                    "status": r[1], "source": "heartbeat"}
    except Exception:
        pass
    # 2) Fallback a sync_runs (solo si hubo cambios)
    r = conn.execute(
        "SELECT started_at, finished_at, proyectos_vistos, proyectos_nuevos, "
        "       proyectos_actualizados, errores, csv_source "
        "FROM sync_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else None

@st.cache_data(ttl=60)
def load_proyectos(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    conn = get_conn()
    # LEFT JOIN con documentos: traemos la URL del PDF principal (el de menor
    # orden) y el conteo total de documentos. Si el proyecto no tiene docs en
    # la tabla (porque enriquecer-documentos no se corrió), pdf_url queda NULL.
    # Chequeo defensivo: si la tabla unificacion_pl no existe todavia (DB
    # vieja sin la migracion), devolvemos NULL en lugar de joinear. Evita
    # OperationalError "no such table: unificacion_pl".
    has_unif = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='unificacion_pl'"
    ).fetchone() is not None
    unif_col = (
        """(SELECT GROUP_CONCAT(up2.n_tramite, ', ')
              FROM unificacion_pl up1
              JOIN unificacion_pl up2 ON up2.grupo_id = up1.grupo_id
                                     AND up2.n_tramite != up1.n_tramite
              WHERE up1.n_tramite = p.n_tramite)"""
        if has_unif else "NULL"
    )
    # Chequeo defensivo para columna es_unificado (puede no existir aun)
    cols_proy = [r[1] for r in conn.execute("PRAGMA table_info(proyectos)")]
    has_es_unif = "es_unificado" in cols_proy
    sql = f"""
      SELECT p.n_tramite AS "_n_tramite_label",
             -- URL clickeable directa al PDF (o portal home si no hay docs).
             -- Append '#<n_tramite>' al final para que el LinkColumn pueda
             -- extraer el numero como display_text via regex.
             COALESCE(
               (SELECT url FROM documentos
                  WHERE n_tramite = p.n_tramite
                    AND UPPER(COALESCE(fase, '')) LIKE '%PROYECTO%PRESENTADO%'
                  ORDER BY orden ASC LIMIT 1),
               (SELECT url FROM documentos
                  WHERE n_tramite = p.n_tramite
                  ORDER BY orden ASC LIMIT 1),
               'https://proyectosdeley.asambleanacional.gob.ec/report?n=' || p.n_tramite
             ) || '#' || p.n_tramite AS "N. Trámite",
             {unif_col} AS "Unificado con",
             -- Flag del portal: TRUE si el checkbox "Unificado" esta marcado
             -- (scrapeado con scrapear-unificados via Playwright)
             {"COALESCE(p.es_unificado, 0)" if has_es_unif else "0"} AS "_es_unificado_portal",
             p.titulo AS "Título",
             date(p.fec_presentacion) AS "Presentado",
             date(p.last_changed_at) AS "Último cambio",
             p.estado AS "Estado",
             COALESCE(NULLIF(p.tipo_proponente, ''), '—') AS "Tipo proponente",
             COALESCE(NULLIF(p.proponentes_raw, ''), '—') AS "Proponentes",
             COALESCE(NULLIF(p.comision_asignada, ''), 'No Asignado') AS "Comisión",
             COALESCE(NULLIF(p.tema, ''), 'Otros') AS "Tema",
             (SELECT url FROM documentos
                WHERE n_tramite = p.n_tramite
                ORDER BY orden ASC LIMIT 1) AS "PDF",
             (SELECT COUNT(*) FROM documentos
                WHERE n_tramite = p.n_tramite) AS "_n_docs"
      FROM proyectos p
    """
    where, params = [], []
    if fec_inicio:
        where.append('date(p.fec_presentacion) >= ?'); params.append(fec_inicio.isoformat())
    if fec_fin:
        where.append('date(p.fec_presentacion) <= ?'); params.append(fec_fin.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date(p.fec_presentacion) DESC, p.n_tramite DESC"
    return pd.read_sql_query(sql, conn, params=params)


def detalle_pl(tramite: str) -> tuple[list, sqlite3.Row | None, bool]:
    """(documentos, grupo de unificacion manual o None, ¿el portal lo marca unificado?)."""
    conn = get_conn()
    docs = conn.execute(
        "SELECT fase, descripcion, url, orden FROM documentos WHERE n_tramite = ? ORDER BY orden ASC",
        (tramite,),
    ).fetchall()
    unif = None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='unificacion_pl'").fetchone():
        unif = conn.execute(
            """SELECT g.id, g.nombre, g.descripcion, g.n_tramite_principal,
                      GROUP_CONCAT(up2.n_tramite, ',') AS miembros
               FROM unificacion_pl up
               JOIN unificacion_grupos g ON g.id = up.grupo_id
               JOIN unificacion_pl up2 ON up2.grupo_id = up.grupo_id
               WHERE up.n_tramite = ?
               GROUP BY g.id""",
            (tramite,),
        ).fetchone()
    try:
        r = conn.execute("SELECT COALESCE(es_unificado, 0) FROM proyectos WHERE n_tramite = ?",
                         (tramite,)).fetchone()
        es_unif_portal = bool(r and r[0])
    except sqlite3.OperationalError:
        es_unif_portal = False
    return docs, unif, es_unif_portal


def proyectos_por_tramite(tramites: list[str]) -> list[sqlite3.Row]:
    return get_conn().execute(
        f"SELECT n_tramite, titulo, estado FROM proyectos WHERE n_tramite IN ({','.join('?' * len(tramites))})",
        tramites,
    ).fetchall()
