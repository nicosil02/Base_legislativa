"""Datos de la Agenda EC: sesiones de la Asamblea, PL en agenda y transcripciones."""
from __future__ import annotations

import datetime as dt
import sqlite3
import pandas as pd
import streamlit as st
from consultas import base, conexion, hora_a_minutos


def get_conn() -> sqlite3.Connection:
    return conexion('proyectos_ec.db', 'Inicializa con el workflow `enriquecer-ec.yml`.')


def _upsert_live_sesiones_ec(events_new) -> int:
    """Inserta sesiones EC nuevas a la DB usando el mismo pipeline del
    sync regular (upsert_events + rematch). Asi quedan con metadata y
    matching de PLs igual que las del cron."""
    db = base("proyectos_ec.db")
    if db is None or not events_new:
        return 0
    try:
        from agenda_ec.sync import upsert_events, rematch_all
        conn = sqlite3.connect(str(db), check_same_thread=False)
        try:
            nuevos, _act = upsert_events(conn, events_new)
            if nuevos > 0:
                rematch_all(conn)
            return nuevos
        finally:
            conn.close()
    except Exception as e:
        print(f"[live-upsert-agenda-ec] skip: {e}")
        return 0

@st.cache_data(ttl=300)
def fetch_live_agenda_ec() -> dict:
    """Consulta el ICS publico de Zimbra (Asamblea Nacional) en VIVO.
    Auto-upsert a la DB para que aparezcan en la tabla principal.
    """
    try:
        from agenda_ec.sync import download_ics
        from agenda_ec.ics_parser import parse_events
        text = download_ics(days_back=30, days_fwd=60, timeout=30)
        events = list(parse_events(text))
    except Exception as e:
        return {"total_api": 0, "total_db": 0, "inserted": 0, "error": str(e)}

    conn = get_conn()
    try:
        db_uids = {r[0] for r in conn.execute("SELECT uid FROM sesiones_ec")}
    finally:
        conn.close()

    api_events = [e for e in events if e.uid and e.dtstart]
    new_events = [e for e in api_events if e.uid not in db_uids]
    inserted = _upsert_live_sesiones_ec(new_events)
    return {
        "total_api": len(api_events),
        "total_db": len(db_uids),
        "inserted": inserted,
        "error": None,
    }

@st.cache_data(ttl=60)
def has_sesiones_table() -> bool:
    conn = get_conn()
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sesiones_ec'"
    ).fetchone()
    return r is not None

@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    conn = get_conn()
    today = dt.date.today().isoformat()
    r = conn.execute(
        f"""SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN fecha >= '{today}' THEN 1 ELSE 0 END) AS por_venir,
              SUM(CASE WHEN fecha < '{today}' THEN 1 ELSE 0 END) AS realizadas,
              (SELECT COUNT(DISTINCT n_tramite)
                 FROM sesion_ec_pl_referenciado
                WHERE n_tramite IS NOT NULL) AS pls_distintos,
              (SELECT COUNT(*) FROM sesion_ec_pl_referenciado) AS pls_referencias
            FROM sesiones_ec"""
    ).fetchone()
    return {
        "Total sesiones": r["total"] or 0,
        "Próximas": r["por_venir"] or 0,
        "Realizadas": r["realizadas"] or 0,
        "PLs únicos referenciados": r["pls_distintos"] or 0,
        "Referencias totales": r["pls_referencias"] or 0,
    }

@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    comisiones = sorted(
        {r[0] for r in conn.execute(
            "SELECT DISTINCT nombre_comision FROM sesiones_ec "
            "WHERE nombre_comision IS NOT NULL AND nombre_comision != ''"
        ) if r[0]}
    )
    modalidades = sorted(
        {r[0] for r in conn.execute(
            "SELECT DISTINCT modalidad FROM sesiones_ec "
            "WHERE modalidad IS NOT NULL AND modalidad != ''"
        ) if r[0]}
    )
    fec_min, fec_max = conn.execute(
        "SELECT MIN(fecha), MAX(fecha) FROM sesiones_ec"
    ).fetchone()
    return {"comisiones": comisiones, "modalidades": modalidades,
            "fec_min": fec_min, "fec_max": fec_max}

@st.cache_data(ttl=60)
def load_sesiones(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    conn = get_conn()
    # "Nombre de sesión": SUMMARY con la cola "modalidad X" removida en SQL.
    # Asi se ve igual de limpio que el de PE ("DÉCIMA TERCERA SESIÓN ORDINARIA
    # DE LA COMISIÓN AGRARIA") y no mete "modalidad virtual" en el title.
    sql = """
      SELECT s.uid AS "UID",
             s.fecha AS "Fecha",
             s.hora_inicio AS "Hora",
             COALESCE(s.nombre_comision, '—') AS "Comisión",
             COALESCE(s.status, '—') AS "Estado",
             (SELECT COUNT(*) FROM sesion_ec_pl_referenciado
                WHERE uid=s.uid AND n_tramite IS NOT NULL) AS "_n_pls",
             COALESCE(
               (SELECT GROUP_CONCAT(COALESCE(p.n_tramite, m.n_tramite), ', ')
                  FROM sesion_ec_pl_referenciado m
                  LEFT JOIN proyectos p ON p.n_tramite = m.n_tramite
                  WHERE m.uid = s.uid AND m.n_tramite IS NOT NULL
                  ORDER BY m.score DESC), '—'
             ) AS "PLs en agenda",
             -- Limpieza del SUMMARY: cortar en ", modalidad" / " modalidad"
             TRIM(
               CASE
                 WHEN INSTR(LOWER(s.summary), ', modalidad') > 0
                   THEN SUBSTR(s.summary, 1, INSTR(LOWER(s.summary), ', modalidad') - 1)
                 WHEN INSTR(LOWER(s.summary), ' modalidad') > 0
                   THEN SUBSTR(s.summary, 1, INSTR(LOWER(s.summary), ' modalidad') - 1)
                 ELSE s.summary
               END
             ) AS "Nombre de sesión"
      FROM sesiones_ec s
    """
    where, params = [], []
    if fec_inicio:
        where.append("s.fecha >= ?"); params.append(fec_inicio.isoformat())
    if fec_fin:
        where.append("s.fecha <= ?"); params.append(fec_fin.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Sort por fecha en SQL, por hora en pandas (helper hora_a_minutos
    # convierte cualquier formato — 24hr o 12hr — a numero sortable).
    # Dentro del dia: HORA DESC (la mas tarde primero, mas temprano abajo).
    sql += " ORDER BY s.fecha DESC"
    df = pd.read_sql_query(sql, conn, params=params)
    if "Hora" in df.columns:
        df["_hora_min"] = df["Hora"].apply(hora_a_minutos)
        df = df.sort_values(
            by=["Fecha", "_hora_min"],
            ascending=[False, False],
            kind="mergesort",
        ).drop(columns=["_hora_min"]).reset_index(drop=True)
    return df

@st.cache_data(ttl=60)
def load_pls_agenda_ec(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    """Agrega PLs unicos referenciados en agendas EC en el rango de fechas,
    con su Tema (para el filtro Cliente) - misma idea que
    pages/3_Agenda_PE.py::load_pls_por_comision. Cada fila es 1 PL en 1
    comision (un mismo PL puede aparecer en varias)."""
    conn = get_conn()
    sql = """
      SELECT COALESCE(s.nombre_comision, '—') AS "Comisión",
             m.n_tramite AS "PL",
             COALESCE(
               (SELECT url FROM documentos
                  WHERE n_tramite = m.n_tramite
                    AND UPPER(COALESCE(fase, '')) LIKE '%PROYECTO%PRESENTADO%'
                  ORDER BY orden ASC LIMIT 1),
               (SELECT url FROM documentos
                  WHERE n_tramite = m.n_tramite ORDER BY orden ASC LIMIT 1),
               'https://proyectosdeley.asambleanacional.gob.ec/report?n=' || m.n_tramite
             ) || '#' || m.n_tramite AS "Nº trámite",
             COALESCE(p.tema, '—') AS "Tema",
             COALESCE(p.estado, '(no en DB)') AS "Estado del PL",
             COALESCE(p.titulo, '(sin título)') AS "Título",
             COUNT(DISTINCT s.uid) AS "Sesiones",
             MIN(s.fecha) AS "Primera",
             MAX(s.fecha) AS "Última"
      FROM sesion_ec_pl_referenciado m
      JOIN sesiones_ec s ON s.uid = m.uid
      LEFT JOIN proyectos p ON p.n_tramite = m.n_tramite
      WHERE m.n_tramite IS NOT NULL
    """
    params: list = []
    if fec_inicio:
        sql += " AND s.fecha >= ?"; params.append(fec_inicio.isoformat())
    if fec_fin:
        sql += " AND s.fecha <= ?"; params.append(fec_fin.isoformat())
    sql += ' GROUP BY "Comisión", m.n_tramite ORDER BY "Comisión", "Sesiones" DESC, m.n_tramite'
    return pd.read_sql_query(sql, conn, params=params)

@st.cache_data(ttl=60)
def load_pls_de_sesion(uid: str) -> pd.DataFrame:
    """Devuelve los PLs identificados en una sesion. La columna "Nº tramite"
    es URL al PDF directo (fileservice publico, sin auth) o al portal home
    como fallback. Append '#<n_tramite>' al final para que el LinkColumn
    pueda extraer el numero como display_text via regex.
    """
    conn = get_conn()
    sql = """
      SELECT
        COALESCE(
          (SELECT url FROM documentos
             WHERE n_tramite = m.n_tramite
               AND UPPER(COALESCE(fase, '')) LIKE '%PROYECTO%PRESENTADO%'
             ORDER BY orden ASC LIMIT 1),
          (SELECT url FROM documentos
             WHERE n_tramite = m.n_tramite
             ORDER BY orden ASC LIMIT 1),
          'https://proyectosdeley.asambleanacional.gob.ec/report?n=' || m.n_tramite
        ) || '#' || m.n_tramite AS "Nº trámite",
        COALESCE(p.titulo, '(no en DB)') AS "Título",
        COALESCE(p.estado, '—') AS "Estado",
        COALESCE(p.tema, '—') AS "Tema",
        m.score AS "_score"
      FROM sesion_ec_pl_referenciado m
      LEFT JOIN proyectos p ON p.n_tramite = m.n_tramite
      WHERE m.uid = ? AND m.n_tramite IS NOT NULL
      ORDER BY m.score DESC
    """
    return pd.read_sql_query(sql, conn, params=(uid,))

@st.cache_data(ttl=60)
def load_descripcion(uid: str) -> tuple[str, str, str, str]:
    """Devuelve (descripcion, location, fecha, hora_inicio) para mostrar
    el detalle completo de la sesion seleccionada."""
    conn = get_conn()
    r = conn.execute(
        "SELECT descripcion, location, fecha, hora_inicio FROM sesiones_ec WHERE uid = ?",
        (uid,),
    ).fetchone()
    if r is None:
        return ("", "", "", "")
    return (r[0] or "", r[1] or "", r[2] or "", r[3] or "")

@st.cache_data(ttl=300)
def load_sesiones_ec_transcritas(limit: int = 400) -> pd.DataFrame:
    from congreso_live.transcripciones import _find_db_path as _db_pe
    db = _db_pe()
    if not db.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    try:
        return pd.read_sql_query(
            """SELECT video_id, tipo, titulo, fecha, duracion_seg, texto
               FROM sesiones_transcripciones WHERE tipo LIKE '%(EC)' AND tipo NOT LIKE 'Entrevista:%'
               ORDER BY fecha DESC, video_id DESC LIMIT ?""",
            conn, params=(limit,))
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()
