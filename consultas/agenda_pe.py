"""Datos de la Agenda PE: sesiones de comisiones y Pleno, PL en agenda y sync en vivo."""
from __future__ import annotations

import datetime as dt
import sqlite3
import pandas as pd
import streamlit as st
from scraper.sync import FECHA_INICIO_BICAMERAL, PER_PAR_ID_ACTUAL
from consultas import base, conexion, hora_a_minutos


def get_conn() -> sqlite3.Connection:
    return conexion('proyectos.db', 'Inicializa con `python -m sesiones.cli init && python -m sesiones.cli update`.')


def _upsert_live_sesiones_pe(nuevas_api: list[dict],
                              periodo_par: int = PER_PAR_ID_ACTUAL,
                              periodo_leg: int = 2026) -> int:
    """Inserta sesiones detectadas en vivo a la DB. Auto-write para que
    aparezcan en la tabla principal sin tener que esperar al cron."""
    db = base("proyectos.db")
    if db is None:
        return 0
    # Convertir fecha DD/MM/YYYY -> YYYY-MM-DD (formato que usa la DB)
    def _norm_fecha(s):
        if not s or not isinstance(s, str):
            return None
        parts = s.split("/")
        if len(parts) == 3 and len(parts[2]) == 4:
            return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        return s
    inserted = 0
    try:
        conn = sqlite3.connect(str(db), check_same_thread=False)
        try:
            for s in nuevas_api:
                id_sesion = s.get("idSesion")
                if not id_sesion:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO sesiones
                       (id_sesion, comision_id, nombre_comision, tipo_comision,
                        nombre_sesion, fecha, hora_inicio, hora_fin, estado,
                        periodo_parlamentario, periodo_legislativo)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        id_sesion,
                        s.get("comisionId"),
                        s.get("nombreComision"),
                        s.get("tipoComision"),
                        s.get("nombreSesion"),
                        _norm_fecha(s.get("fecha")),
                        s.get("horaInicio"),
                        s.get("horaFin"),
                        s.get("estado"),
                        periodo_par,
                        periodo_leg,
                    ),
                )
                if conn.total_changes > inserted:
                    inserted += 1
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        print(f"[live-upsert-agenda-pe] skip: {e}")
        return 0
    return inserted

@st.cache_data(ttl=300)
def fetch_live_agenda_pe(periodo_par: int = PER_PAR_ID_ACTUAL, periodo_leg: int = 2026) -> dict:
    """Consulta la API visor-sesiones en VIVO. Auto-upsert a la DB para que
    las nuevas sesiones aparezcan integradas en la tabla principal.
    """
    try:
        from sesiones.api import ApiClient
        client = ApiClient()
        api_sesiones = client.list_sesiones(
            periodo_parlamentario=periodo_par,
            periodo_legislativo=periodo_leg,
        )
    except Exception as e:
        return {"total_api": 0, "total_db": 0, "inserted": 0, "error": str(e)}

    conn = get_conn()
    try:
        db_ids = {r[0] for r in conn.execute(
            "SELECT id_sesion FROM sesiones WHERE id_sesion IS NOT NULL"
        )}
    finally:
        conn.close()

    api_ids = {s.get("idSesion") for s in api_sesiones if s.get("idSesion")}
    new_ids = api_ids - db_ids
    nuevas_raw = [s for s in api_sesiones if s.get("idSesion") in new_ids]
    inserted = _upsert_live_sesiones_pe(
        nuevas_raw, periodo_par=periodo_par, periodo_leg=periodo_leg
    )
    return {
        "total_api": len(api_ids),
        "total_db": len(db_ids),
        "inserted": inserted,
        "error": None,
    }

@st.cache_data(ttl=60)
def has_sesiones_table() -> bool:
    conn = get_conn()
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sesiones'"
    ).fetchone()
    return r is not None

@st.cache_data(ttl=60)
def has_pleno_table() -> bool:
    """True si la DB ya tiene las tablas del Pleno pobladas (sync corrio
    al menos una vez)."""
    conn = get_conn()
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pleno_sesiones'"
    ).fetchone()
    if not r:
        return False
    # Tabla existe pero vacia tambien lo tratamos como "no hay datos"
    n = conn.execute("SELECT COUNT(*) FROM pleno_sesiones").fetchone()[0]
    return n > 0

@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    comisiones = [
        {"id": r[0], "nombre": r[1], "camara": r[2]}
        for r in conn.execute(
            "SELECT DISTINCT comision_id, nombre_comision, camara FROM sesiones "
            "WHERE comision_id IS NOT NULL AND fecha >= ? ORDER BY nombre_comision",
            (FECHA_INICIO_BICAMERAL,),
        )
    ]
    estados = sorted({
        r[0] for r in conn.execute(
            "SELECT DISTINCT estado FROM sesiones WHERE estado IS NOT NULL AND fecha >= ?",
            (FECHA_INICIO_BICAMERAL,),
        )
    })
    # Rango temporal: el menor entre comisiones y Pleno; el mayor idem. Ambos
    # acotados al Congreso bicameral vigente (ver FECHA_INICIO_BICAMERAL) —
    # la data histórica 2021-2026 queda en la DB pero desconectada de esta
    # página por pedido explícito de Nicolas (2026-09-11).
    fec_min, fec_max = conn.execute(
        "SELECT MIN(fecha), MAX(fecha) FROM sesiones WHERE fecha >= ?",
        (FECHA_INICIO_BICAMERAL,),
    ).fetchone()
    if has_pleno_table():
        pmin, pmax = conn.execute(
            "SELECT MIN(fecha_sesion), MAX(fecha_sesion) FROM pleno_sesiones WHERE fecha_sesion >= ?",
            (FECHA_INICIO_BICAMERAL,),
        ).fetchone()
        if pmin and (not fec_min or pmin < fec_min):
            fec_min = pmin
        if pmax and (not fec_max or pmax > fec_max):
            fec_max = pmax
    # Fallback si todavía no hay nada en el rango bicameral (ej. Pleno sin
    # agendas publicadas aún — ver pleno/api.py).
    fec_min = fec_min or FECHA_INICIO_BICAMERAL
    fec_max = fec_max or dt.date.today().isoformat()
    return {"comisiones": comisiones, "estados": estados,
            "fec_min": fec_min, "fec_max": fec_max}

@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    conn = get_conn()
    today = dt.date.today().isoformat()
    r = conn.execute(
        """SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN UPPER(estado)='CONVOCADA' AND fecha >= ? THEN 1 ELSE 0 END) AS por_venir,
              SUM(CASE WHEN UPPER(estado) IN ('CELEBRADA','FINALIZADA') THEN 1 ELSE 0 END) AS realizadas,
              (SELECT COUNT(DISTINCT pr.pley_num) FROM sesion_pl_referenciado pr
                 JOIN sesiones s2 ON s2.id_sesion = pr.id_sesion WHERE s2.fecha >= ?) AS pls_distintos,
              (SELECT COUNT(*) FROM sesion_pl_referenciado pr
                 JOIN sesiones s2 ON s2.id_sesion = pr.id_sesion WHERE s2.fecha >= ?) AS pls_referencias
            FROM sesiones WHERE fecha >= ?""",
        (today, FECHA_INICIO_BICAMERAL, FECHA_INICIO_BICAMERAL, FECHA_INICIO_BICAMERAL),
    ).fetchone()
    total = (r["total"] or 0)
    por_venir = (r["por_venir"] or 0)
    realizadas = (r["realizadas"] or 0)
    pls_distintos = r["pls_distintos"] or 0
    pls_referencias = r["pls_referencias"] or 0
    # Sumar agendas del Pleno si existen. El Pleno no tiene estado
    # "Convocada/Realizada" — clasificamos por fecha vs hoy.
    if has_pleno_table():
        rp = conn.execute(
            """SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN fecha_sesion >= ? THEN 1 ELSE 0 END) AS por_venir,
                  SUM(CASE WHEN fecha_sesion >= ? AND fecha_sesion < ? THEN 1 ELSE 0 END) AS realizadas
                FROM pleno_sesiones WHERE fecha_sesion >= ?""",
            (today, FECHA_INICIO_BICAMERAL, today, FECHA_INICIO_BICAMERAL),
        ).fetchone()
        total += (rp["total"] or 0)
        por_venir += (rp["por_venir"] or 0)
        realizadas += (rp["realizadas"] or 0)
        # PLs unicos y referencias: combinar las dos tablas, acotadas al Congreso vigente
        rpref = conn.execute(
            """SELECT COUNT(DISTINCT pley_num) AS d, COUNT(*) AS r
               FROM (
                 SELECT pr.pley_num FROM sesion_pl_referenciado pr
                   JOIN sesiones s2 ON s2.id_sesion = pr.id_sesion WHERE s2.fecha >= ?
                 UNION ALL
                 SELECT pp.pley_num FROM pleno_pl_referenciado pp
                   JOIN pleno_sesiones ps ON ps.cod_agenda = pp.cod_agenda WHERE ps.fecha_sesion >= ?
               )""",
            (FECHA_INICIO_BICAMERAL, FECHA_INICIO_BICAMERAL),
        ).fetchone()
        pls_distintos = rpref["d"] or 0
        pls_referencias = rpref["r"] or 0
    return {
        "Total sesiones": total,
        "Próximas": por_venir,
        "Realizadas": realizadas,
        "PLs únicos referenciados": pls_distintos,
        "Referencias totales": pls_referencias,
    }

@st.cache_data(ttl=60)
def load_sesiones(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    """Carga las sesiones de comisiones + agendas del Pleno en un solo DF.
    Columna `_fuente` distingue: 'comision' vs 'pleno'. El campo "ID" es
    `id_sesion` para comisiones y `cod_agenda` para el Pleno (sin colision
    porque los rangos son disjuntos en la API)."""
    conn = get_conn()
    sql_comisiones = """
      SELECT s.id_sesion AS "ID",
             'comision' AS "_fuente",
             s.fecha AS "Fecha",
             s.hora_inicio AS "Hora",
             s.nombre_comision AS "Comisión",
             s.camara AS "Cámara",
             s.tipo_comision AS "Tipo",
             s.estado AS "Estado",
             s.nombre_sesion AS "Nombre",
             (SELECT COUNT(*) FROM sesion_pl_referenciado WHERE id_sesion=s.id_sesion) AS "_n_pls",
             COALESCE((SELECT GROUP_CONCAT(
                       COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num),
                       ', ')
                FROM sesion_pl_referenciado pr
                LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                        -- sesion_pl_referenciado no guarda cod_tipo_parl (el parser de
                        -- texto libre no siempre sabe de que camara es un PL) -- sin este
                        -- desempate, un pley_num que existe en 2+ camaras (comun en el
                        -- periodo bicameral: D/S/C reinician numeracion desde 1) hacia
                        -- fan-out el JOIN y duplicaba/mezclaba titulos. Desempate
                        -- deterministico: 'C' > 'D' > 'S' (alfabetico), nunca mas de 1 fila.
                        AND p.cod_tipo_parl = (
                          SELECT MIN(p2.cod_tipo_parl) FROM proyectos p2
                          WHERE p2.per_par_id = pr.per_par_id AND p2.pley_num = pr.pley_num
                        )
                WHERE pr.id_sesion = s.id_sesion
                ORDER BY pr.pley_num
              ), '—') AS "PLs en agenda",
             s.link_teams AS "_link_teams",
             s.link_video AS "_link_video"
      FROM sesiones s
    """
    where_c, params_c = [], []
    if fec_inicio:
        where_c.append("s.fecha >= ?"); params_c.append(fec_inicio.isoformat())
    if fec_fin:
        where_c.append("s.fecha <= ?"); params_c.append(fec_fin.isoformat())
    if where_c:
        sql_comisiones += " WHERE " + " AND ".join(where_c)

    df = pd.read_sql_query(sql_comisiones, conn, params=params_c)

    # UNION con el Pleno (si la tabla existe y tiene datos).
    if has_pleno_table():
        sql_pleno = """
          SELECT ps.cod_agenda AS "ID",
                 'pleno' AS "_fuente",
                 ps.fecha_sesion AS "Fecha",
                 NULL AS "Hora",
                 'Pleno del Congreso' AS "Comisión",
                 CASE ps.camara WHEN 'D' THEN 'Diputados' WHEN 'S' THEN 'Senado'
                      WHEN 'C' THEN 'Congreso' ELSE NULL END AS "Cámara",  -- poblado
                      -- para fuente='agenda_pdf' (ver pleno/from_agenda_pdf.py);
                      -- NULL para las agendas viejas de la API unicameral
                 'Pleno' AS "Tipo",
                 CASE WHEN ps.fecha_sesion >= date('now') THEN 'Convocada' ELSE 'Realizada' END AS "Estado",
                 ps.titulo AS "Nombre",
                 (SELECT COUNT(*) FROM pleno_pl_referenciado WHERE cod_agenda=ps.cod_agenda) AS "_n_pls",
                 COALESCE((SELECT GROUP_CONCAT(
                           COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num),
                           ', ')
                    FROM pleno_pl_referenciado pr
                    LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                        -- sesion_pl_referenciado no guarda cod_tipo_parl (el parser de
                        -- texto libre no siempre sabe de que camara es un PL) -- sin este
                        -- desempate, un pley_num que existe en 2+ camaras (comun en el
                        -- periodo bicameral: D/S/C reinician numeracion desde 1) hacia
                        -- fan-out el JOIN y duplicaba/mezclaba titulos. Desempate
                        -- deterministico: 'C' > 'D' > 'S' (alfabetico), nunca mas de 1 fila.
                        AND p.cod_tipo_parl = (
                          SELECT MIN(p2.cod_tipo_parl) FROM proyectos p2
                          WHERE p2.per_par_id = pr.per_par_id AND p2.pley_num = pr.pley_num
                        )
                    WHERE pr.cod_agenda = ps.cod_agenda
                    ORDER BY pr.pley_num
                  ), '—') AS "PLs en agenda",
                 NULL AS "_link_teams",
                 NULL AS "_link_video"
          FROM pleno_sesiones ps
        """
        where_p, params_p = [], []
        if fec_inicio:
            where_p.append("ps.fecha_sesion >= ?"); params_p.append(fec_inicio.isoformat())
        if fec_fin:
            where_p.append("ps.fecha_sesion <= ?"); params_p.append(fec_fin.isoformat())
        if where_p:
            sql_pleno += " WHERE " + " AND ".join(where_p)
        df_pleno = pd.read_sql_query(sql_pleno, conn, params=params_p)
        if not df_pleno.empty:
            df = pd.concat([df, df_pleno], ignore_index=True)

    # Orden por fecha (DESC); el sort por hora se hace en pandas porque PE
    # usa formato 12hr "9:00AM"/"2:00PM" que no es lexicografico-sortable.
    if "Hora" in df.columns:
        df["_hora_min"] = df["Hora"].apply(hora_a_minutos)
        df = df.sort_values(
            by=["Fecha", "_hora_min"],
            ascending=[False, False],
            kind="mergesort",  # stable
        ).drop(columns=["_hora_min"]).reset_index(drop=True)
    return df

@st.cache_data(ttl=60)
def buscar_pl_en_agendas(pley_num: int) -> pd.DataFrame:
    """Para un numero de PL, devuelve todas las apariciones en agenda
    (Comisiones Ordinarias + Pleno). Cruzado con tabla proyectos para
    mostrar tema/estado."""
    conn = get_conn()
    sql = """
      SELECT s.fecha AS "Fecha",
             s.hora_inicio AS "Hora",
             s.nombre_comision AS "Comisión",
             s.camara AS "Cámara",
             s.tipo_comision AS "Tipo",
             s.estado AS "Estado sesión",
             s.nombre_sesion AS "Sesión",
             s.id_sesion AS "_id_sesion",
             pr.proyecto_ley_raw AS "_raw",
             pr.contexto AS "Contexto en agenda",
             COALESCE(p.titulo, '(no en DB de proyectos)') AS "Título del PL",
             COALESCE(p.tema, '—') AS "Tema",
             COALESCE(p.estado, '—') AS "Estado del PL"
      FROM sesion_pl_referenciado pr
      JOIN sesiones s ON s.id_sesion = pr.id_sesion
      LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                        -- sesion_pl_referenciado no guarda cod_tipo_parl (el parser de
                        -- texto libre no siempre sabe de que camara es un PL) -- sin este
                        -- desempate, un pley_num que existe en 2+ camaras (comun en el
                        -- periodo bicameral: D/S/C reinician numeracion desde 1) hacia
                        -- fan-out el JOIN y duplicaba/mezclaba titulos. Desempate
                        -- deterministico: 'C' > 'D' > 'S' (alfabetico), nunca mas de 1 fila.
                        AND p.cod_tipo_parl = (
                          SELECT MIN(p2.cod_tipo_parl) FROM proyectos p2
                          WHERE p2.per_par_id = pr.per_par_id AND p2.pley_num = pr.pley_num
                        )
      WHERE pr.pley_num = ?
    """
    df = pd.read_sql_query(sql, conn, params=(pley_num,))

    if has_pleno_table():
        sql_pleno = """
          SELECT ps.fecha_sesion AS "Fecha",
                 NULL AS "Hora",
                 'Pleno del Congreso' AS "Comisión",
                 CASE ps.camara WHEN 'D' THEN 'Diputados' WHEN 'S' THEN 'Senado'
                      WHEN 'C' THEN 'Congreso' ELSE NULL END AS "Cámara",
                 'Pleno' AS "Tipo",
                 CASE WHEN ps.fecha_sesion >= date('now') THEN 'Convocada' ELSE 'Realizada' END AS "Estado sesión",
                 ps.titulo AS "Sesión",
                 ps.cod_agenda AS "_id_sesion",
                 pr.proyecto_ley_raw AS "_raw",
                 COALESCE(pt.des_resumen, substr(pt.des_tema_texto,1,200)) AS "Contexto en agenda",
                 COALESCE(p.titulo, '(no en DB de proyectos)') AS "Título del PL",
                 COALESCE(p.tema, '—') AS "Tema",
                 COALESCE(p.estado, '—') AS "Estado del PL"
          FROM pleno_pl_referenciado pr
          JOIN pleno_sesiones ps ON ps.cod_agenda = pr.cod_agenda
          LEFT JOIN pleno_tema pt ON pt.cod_tema = pr.cod_tema
          LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                        -- sesion_pl_referenciado no guarda cod_tipo_parl (el parser de
                        -- texto libre no siempre sabe de que camara es un PL) -- sin este
                        -- desempate, un pley_num que existe en 2+ camaras (comun en el
                        -- periodo bicameral: D/S/C reinician numeracion desde 1) hacia
                        -- fan-out el JOIN y duplicaba/mezclaba titulos. Desempate
                        -- deterministico: 'C' > 'D' > 'S' (alfabetico), nunca mas de 1 fila.
                        AND p.cod_tipo_parl = (
                          SELECT MIN(p2.cod_tipo_parl) FROM proyectos p2
                          WHERE p2.per_par_id = pr.per_par_id AND p2.pley_num = pr.pley_num
                        )
          WHERE pr.pley_num = ?
        """
        df_p = pd.read_sql_query(sql_pleno, conn, params=(pley_num,))
        if not df_p.empty:
            df = pd.concat([df, df_p], ignore_index=True)

    # Ordenar por fecha desc (Hora puede ser None para Pleno; queda al final
    # naturalmente con sort_values mergesort stable)
    if not df.empty:
        df = df.sort_values(by=["Fecha"], ascending=False, kind="mergesort").reset_index(drop=True)
    return df

@st.cache_data(ttl=60)
def load_pls_de_sesion(id_sesion: int, fuente: str = "comision") -> pd.DataFrame:
    """PLs en agenda para 1 sesion. `fuente` decide la tabla de referencia
    (sesion_pl_referenciado para comisiones, pleno_pl_referenciado para Pleno)."""
    conn = get_conn()
    if fuente == "pleno":
        sql = """
          SELECT pr.pley_num AS pley_num,
                 'https://wb2server.congreso.gob.pe/spley-portal/?pl='
                   || COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num)
                   || '#/expediente/' || COALESCE(pr.per_par_id, 2026) || '/' || pr.pley_num
                 AS "Nº PL",
                 COALESCE(p.tema, '—') AS "Tema",
                 COALESCE(p.estado, '(no en DB)') AS "Estado",
                 COALESCE(p.grupo_parlamentario, '—') AS "Bancada",
                 COALESCE(p.titulo, pt.des_resumen, '(sin título)') AS "Título",
                 pt.des_resumen AS "_Contexto",
                 pr.proyecto_ley_raw AS "_Raw"
          FROM pleno_pl_referenciado pr
          LEFT JOIN pleno_tema pt ON pt.cod_tema = pr.cod_tema
          LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                        -- sesion_pl_referenciado no guarda cod_tipo_parl (el parser de
                        -- texto libre no siempre sabe de que camara es un PL) -- sin este
                        -- desempate, un pley_num que existe en 2+ camaras (comun en el
                        -- periodo bicameral: D/S/C reinician numeracion desde 1) hacia
                        -- fan-out el JOIN y duplicaba/mezclaba titulos. Desempate
                        -- deterministico: 'C' > 'D' > 'S' (alfabetico), nunca mas de 1 fila.
                        AND p.cod_tipo_parl = (
                          SELECT MIN(p2.cod_tipo_parl) FROM proyectos p2
                          WHERE p2.per_par_id = pr.per_par_id AND p2.pley_num = pr.pley_num
                        )
          WHERE pr.cod_agenda=?
          ORDER BY pt.num_tema, pr.pley_num
        """
        return pd.read_sql_query(sql, conn, params=(id_sesion,))

    # Default: comision
    sql = """
      SELECT pr.pley_num AS pley_num,
             'https://wb2server.congreso.gob.pe/spley-portal/?pl='
               || COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num)
               || '#/expediente/' || COALESCE(pr.per_par_id, 2026) || '/' || pr.pley_num
             AS "Nº PL",
             COALESCE(p.tema, '—') AS "Tema",
             COALESCE(p.estado, '(no en DB)') AS "Estado",
             COALESCE(p.grupo_parlamentario, '—') AS "Bancada",
             COALESCE(p.titulo, pr.contexto, '(sin título)') AS "Título",
             pr.contexto AS "_Contexto",
             pr.proyecto_ley_raw AS "_Raw"
      FROM sesion_pl_referenciado pr
      LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                        -- sesion_pl_referenciado no guarda cod_tipo_parl (el parser de
                        -- texto libre no siempre sabe de que camara es un PL) -- sin este
                        -- desempate, un pley_num que existe en 2+ camaras (comun en el
                        -- periodo bicameral: D/S/C reinician numeracion desde 1) hacia
                        -- fan-out el JOIN y duplicaba/mezclaba titulos. Desempate
                        -- deterministico: 'C' > 'D' > 'S' (alfabetico), nunca mas de 1 fila.
                        AND p.cod_tipo_parl = (
                          SELECT MIN(p2.cod_tipo_parl) FROM proyectos p2
                          WHERE p2.per_par_id = pr.per_par_id AND p2.pley_num = pr.pley_num
                        )
      WHERE pr.id_sesion=?
      ORDER BY pr.pley_num
    """
    return pd.read_sql_query(sql, conn, params=(id_sesion,))

@st.cache_data(ttl=60)
def load_pls_por_comision(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    """Agrega PLs únicos referenciados por comisión en el rango de fechas
    (incluye el Pleno como una "comisión" más). Cada fila es 1 PL en 1
    comisión (un mismo PL puede aparecer en varias)."""
    conn = get_conn()
    parts = []
    params: list = []
    parts.append("""
      SELECT s.nombre_comision AS "Comisión",
             pr.pley_num AS pley_num,
             'https://wb2server.congreso.gob.pe/spley-portal/?pl='
               || COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num)
               || '#/expediente/' || COALESCE(pr.per_par_id, 2026) || '/' || pr.pley_num
             AS "Nº PL",
             COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num) AS "PL",
             COALESCE(p.tema, '—') AS "Tema",
             COALESCE(p.estado, '(no en DB)') AS "Estado del PL",
             COALESCE(p.titulo, '(sin título)') AS "Título",
             s.id_sesion AS _sesion_id,
             s.fecha AS _fecha
      FROM sesion_pl_referenciado pr
      JOIN sesiones s ON s.id_sesion = pr.id_sesion
      LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                        -- sesion_pl_referenciado no guarda cod_tipo_parl (el parser de
                        -- texto libre no siempre sabe de que camara es un PL) -- sin este
                        -- desempate, un pley_num que existe en 2+ camaras (comun en el
                        -- periodo bicameral: D/S/C reinician numeracion desde 1) hacia
                        -- fan-out el JOIN y duplicaba/mezclaba titulos. Desempate
                        -- deterministico: 'C' > 'D' > 'S' (alfabetico), nunca mas de 1 fila.
                        AND p.cod_tipo_parl = (
                          SELECT MIN(p2.cod_tipo_parl) FROM proyectos p2
                          WHERE p2.per_par_id = pr.per_par_id AND p2.pley_num = pr.pley_num
                        )
      WHERE 1=1
    """)
    if fec_inicio:
        parts.append(" AND s.fecha >= ?"); params.append(fec_inicio.isoformat())
    if fec_fin:
        parts.append(" AND s.fecha <= ?"); params.append(fec_fin.isoformat())
    if has_pleno_table():
        parts.append("""
          UNION ALL
          SELECT 'Pleno del Congreso' AS "Comisión",
                 pr.pley_num AS pley_num,
                 'https://wb2server.congreso.gob.pe/spley-portal/?pl='
                   || COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num)
                   || '#/expediente/' || COALESCE(pr.per_par_id, 2026) || '/' || pr.pley_num
                 AS "Nº PL",
                 COALESCE(p.proyecto_ley, pr.proyecto_ley_raw, 'PL ' || pr.pley_num) AS "PL",
                 COALESCE(p.tema, '—') AS "Tema",
                 COALESCE(p.estado, '(no en DB)') AS "Estado del PL",
                 COALESCE(p.titulo, '(sin título)') AS "Título",
                 ps.cod_agenda AS _sesion_id,
                 ps.fecha_sesion AS _fecha
          FROM pleno_pl_referenciado pr
          JOIN pleno_sesiones ps ON ps.cod_agenda = pr.cod_agenda
          LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
                        -- sesion_pl_referenciado no guarda cod_tipo_parl (el parser de
                        -- texto libre no siempre sabe de que camara es un PL) -- sin este
                        -- desempate, un pley_num que existe en 2+ camaras (comun en el
                        -- periodo bicameral: D/S/C reinician numeracion desde 1) hacia
                        -- fan-out el JOIN y duplicaba/mezclaba titulos. Desempate
                        -- deterministico: 'C' > 'D' > 'S' (alfabetico), nunca mas de 1 fila.
                        AND p.cod_tipo_parl = (
                          SELECT MIN(p2.cod_tipo_parl) FROM proyectos p2
                          WHERE p2.per_par_id = pr.per_par_id AND p2.pley_num = pr.pley_num
                        )
          WHERE 1=1
        """)
        if fec_inicio:
            parts.append(" AND ps.fecha_sesion >= ?"); params.append(fec_inicio.isoformat())
        if fec_fin:
            parts.append(" AND ps.fecha_sesion <= ?"); params.append(fec_fin.isoformat())
    inner = "".join(parts)
    sql = f"""
      SELECT "Comisión", pley_num, "Nº PL", "PL", "Tema", "Estado del PL", "Título",
             COUNT(DISTINCT _sesion_id) AS "Sesiones",
             MIN(_fecha) AS "Primera",
             MAX(_fecha) AS "Última"
      FROM ({inner})
      GROUP BY "Comisión", pley_num, "PL"
      ORDER BY "Comisión", "Sesiones" DESC, pley_num
    """
    return pd.read_sql_query(sql, conn, params=params)

@st.cache_data(ttl=60)
def load_puntos_agenda(id_sesion: int, fuente: str = "comision") -> list[dict]:
    """Para comisiones: filas de sesion_agenda_punto. Para Pleno: filas de
    pleno_tema (cada tema es un "punto" con resumen, comision dictaminadora
    y HTML rich)."""
    conn = get_conn()
    if fuente == "pleno":
        rows = conn.execute(
            """SELECT cod_tema AS id_orden_dia, num_tema AS orden,
                      COALESCE(des_resumen, des_tema_texto) AS descripcion_texto,
                      des_sec, des_comisiones, nom_tema_cor
               FROM pleno_tema WHERE cod_agenda=? ORDER BY num_tema""",
            (id_sesion,),
        ).fetchall()
        return [dict(r) for r in rows]
    rows = conn.execute(
        "SELECT id_orden_dia, orden, descripcion_texto FROM sesion_agenda_punto "
        "WHERE id_sesion=? ORDER BY orden",
        (id_sesion,),
    ).fetchall()
    return [dict(r) for r in rows]
