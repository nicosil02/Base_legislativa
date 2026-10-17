"""Datos de la pagina Peru (PL del Congreso): catalogos, KPIs, evolucion, proyectos y sync en vivo."""
from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess
import sys
from pathlib import Path
import pandas as pd
import streamlit as st
from scraper.sync import FECHA_INICIO_BICAMERAL, PER_PAR_ID_ACTUAL
from consultas import base, conexion

COMISIONES_ESPECIALES_LABEL = "Comisiones Especiales"

# Cámara de origen del PL — 'C' (Congreso/general: Ejecutivo, Comisión
# Permanente), 'D' (Cámara de Diputados), 'S' (Senado). Cada cámara reinicia
# su numeración desde 1 dentro del mismo período, así que dos PLs con el
# mismo "PL 4" pueden ser proyectos distintos — esta columna los distingue.
CAMARA_LABEL = {"C": "Congreso", "D": "Diputados", "S": "Senado"}

SYNC_MIN_MINUTES = 5      # gap mínimo entre auto-syncs
SYNC_STALE_MINUTES = 15   # un sync sin terminar después de esto se considera muerto


def get_conn() -> sqlite3.Connection:
    return conexion('proyectos.db', 'Corre desde la carpeta raíz del repo: `bash scripts/bajar_db.sh proyectos.db.gz proyectos.db`')


@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    # Acotado al Congreso bicameral vigente (per_par_id actual) — el 2021-2026
    # queda en la DB pero desconectado de esta página por pedido explícito
    # de Nicolas (2026-09-11): "no me sirve la base histórica... desconéctala".
    temas = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT tema FROM proyectos WHERE tema IS NOT NULL AND per_par_id=?", (PER_PAR_ID_ACTUAL,)
    ))
    estados = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT estado FROM proyectos WHERE estado IS NOT NULL AND per_par_id=?", (PER_PAR_ID_ACTUAL,)
    ))
    proponentes = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT proponente FROM proyectos WHERE proponente IS NOT NULL AND per_par_id=?", (PER_PAR_ID_ACTUAL,)
    ))
    partidos = sorted(r[0] for r in conn.execute(
        "SELECT DISTINCT grupo_parlamentario FROM proyectos WHERE grupo_parlamentario IS NOT NULL AND per_par_id=?",
        (PER_PAR_ID_ACTUAL,),
    ))
    fec_min, fec_max = conn.execute(
        "SELECT MIN(date(fec_presentacion)), MAX(date(fec_presentacion)) FROM proyectos WHERE per_par_id=?",
        (PER_PAR_ID_ACTUAL,),
    ).fetchone()
    # Catálogo COMPLETO de comisiones por cámara (no solo las que ya tienen
    # un PL asignado) — para que el filtro deje elegir cualquier comisión de
    # Diputados/Senado aunque todavía no haya PLs derivados a ella.
    comisiones_catalogo = [
        {"nombre": r[0], "tipo": r[1]}
        for r in conn.execute(
            "SELECT nombre, tipo FROM comisiones "
            "WHERE tipo IN ('Ordinaria','Senado','Diputados','Bicameral') "
            "ORDER BY tipo, nombre"
        )
    ]
    return {
        "temas": temas, "estados": estados, "proponentes": proponentes,
        "partidos": partidos, "fec_min": fec_min, "fec_max": fec_max,
        "comisiones_catalogo": comisiones_catalogo,
    }

@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    conn = get_conn()
    r = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN UPPER(estado) LIKE '%PRESENTADO%' THEN 1 ELSE 0 END) AS presentados,
             SUM(CASE WHEN UPPER(estado) LIKE '%COMISI%' THEN 1 ELSE 0 END) AS en_comision,
             SUM(CASE WHEN UPPER(estado) LIKE '%DICTAMEN%' THEN 1 ELSE 0 END) AS dictamen,
             SUM(CASE WHEN UPPER(estado) LIKE '%AUTOGRAFA%' OR UPPER(estado) LIKE '%AUTÓGRAFA%' THEN 1 ELSE 0 END) AS autografa,
             SUM(CASE WHEN UPPER(estado) LIKE '%PUBLIC%PERUANO%'
                       OR UPPER(estado) LIKE '%LEY PUBLICADA%'
                       OR UPPER(estado) LIKE '%PUBLICACI%PERUANO%'
                       THEN 1 ELSE 0 END) AS ley_publicada
           FROM proyectos WHERE per_par_id=?""",
        (PER_PAR_ID_ACTUAL,),
    ).fetchone()
    return {
        "Total": r["total"] or 0,
        "Presentados": r["presentados"] or 0,
        "En comisión": r["en_comision"] or 0,
        "Con dictamen": r["dictamen"] or 0,
        "Autógrafas": r["autografa"] or 0,
        "Ley publicada": r["ley_publicada"] or 0,
    }

@st.cache_data(ttl=300)
def evolucion_mensual() -> pd.DataFrame:
    """PLs presentados y leyes publicadas por mes - inspirado en el
    grafico "Evolucion mensual" de Quals (quals.apoyocomunicacion.com,
    pedido explicito de Nicolas 2026-09-22: no su paleta rojo/negro, solo
    la idea del grafico). "Leyes publicadas" usa last_changed_at como
    proxy del mes de publicacion (no tenemos historial completo de
    cambios de estado, solo el ultimo) - misma limitacion razonable que
    tendria cualquier dashboard sin auditoria completa.

    Acotado explicitamente a FECHA_INICIO_BICAMERAL ademas del filtro
    por per_par_id (pedido de Nicolas 2026-09-22: que la fecha no pase
    de cuando arrancó la legislatura bicameral vigente) - per_par_id ya
    debería garantizar esto solo, pero un filtro de fecha explícito no
    depende de que ese campo esté bien cargado en cada fila."""
    conn = get_conn()
    presentados = pd.read_sql_query(
        """SELECT date(fec_presentacion, 'start of month') AS mes,
                  COUNT(*) AS "Presentados"
           FROM proyectos
           WHERE per_par_id=? AND fec_presentacion >= ?
           GROUP BY mes""",
        conn, params=(PER_PAR_ID_ACTUAL, FECHA_INICIO_BICAMERAL),
    )
    publicadas = pd.read_sql_query(
        """SELECT date(last_changed_at, 'start of month') AS mes,
                  COUNT(*) AS "Leyes publicadas"
           FROM proyectos
           WHERE per_par_id=? AND fec_presentacion >= ?
                 AND (UPPER(estado) LIKE '%PUBLIC%PERUANO%'
                      OR UPPER(estado) LIKE '%LEY PUBLICADA%'
                      OR UPPER(estado) LIKE '%PUBLICACI%PERUANO%')
           GROUP BY mes""",
        conn, params=(PER_PAR_ID_ACTUAL, FECHA_INICIO_BICAMERAL),
    )
    df = pd.merge(presentados, publicadas, on="mes", how="outer").fillna(0)
    if df.empty:
        return df
    df = df.sort_values("mes").set_index("mes")
    df.index.name = "Mes"
    return df.astype(int)

@st.cache_data(ttl=300)
def documentos_hoy() -> tuple[int, int]:
    """(PLs hoy, noticias hoy) - gap real vs Dapper identificado 2026-09-20
    (ver memoria dapper-gap-analysis): ellos muestran un contador de
    "documentos publicados hoy" en el dashboard. Dato barato, ya lo
    tenemos - solo faltaba mostrarlo.

    Antes se sumaban en un solo numero ("Nuevos hoy") al lado de metricas
    puras de PL (Presentados, En comision, ...) - hallazgo real de
    critique 2026-09-22: el numero combinado (210) opacaba a su vecino
    "Presentados" (45) sin ninguna explicacion visible salvo un tooltip
    hover, leyendo como un bug o un numero inflado. Separado en 2 tiles."""
    conn = get_conn()
    pls_hoy = conn.execute(
        "SELECT COUNT(*) FROM proyectos WHERE per_par_id=? AND date(first_seen_at)=date('now')",
        (PER_PAR_ID_ACTUAL,),
    ).fetchone()[0]
    noticias_hoy = 0
    try:
        noticias_hoy = conn.execute(
            "SELECT COUNT(*) FROM noticias n JOIN noticias_fuentes f ON f.id=n.fuente_id "
            "WHERE f.pais='PE' AND date(n.first_seen_at)=date('now')"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        pass
    return pls_hoy, noticias_hoy

@st.cache_data(ttl=60)
def sugerencias_pendientes() -> list[dict]:
    """PLs en 'Otros' que el clasificador ML (re-entrenado semanal, ver
    entrenar-ml.yml) sugiere mover a otro tema con confianza 70-85%
    (arriba de eso ya se aplica solo, ver clasificador/reclassify.py).

    Gap real encontrado 2026-09-21: esta tabla existe y crece desde
    mayo (246 pendientes en la auditoria que lo encontro) pero no habia
    NINGUNA forma de verla - ni pagina, ni reporte, solo un conteo por
    CLI que Nicolas nunca corre. Excluye las que ya tienen una decision
    encolada (ver clasificador/decisiones_store.py) para no mostrar de
    nuevo algo que ya se decidio pero todavia no se aplico en la DB
    real (eso pasa en la proxima corrida de refrescar-pe.yml)."""
    from clasificador.decisiones_store import list_decisiones_pendientes

    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT s.id, s.pley_num, s.per_par_id, s.cod_tipo_parl,
                      s.tema_anterior, s.tema_sugerido, s.confidence, s.created_at,
                      p.titulo, p.sumilla
               FROM clasificacion_sugerencias s
               JOIN proyectos p ON p.pley_num = s.pley_num
                                AND p.per_par_id = s.per_par_id
                                AND p.cod_tipo_parl = s.cod_tipo_parl
               WHERE s.estado = 'pendiente' AND s.per_par_id = ?
               ORDER BY s.confidence DESC""",
            (PER_PAR_ID_ACTUAL,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    ya_decididas = {d["sugerencia_id"] for d in list_decisiones_pendientes()}
    return [dict(r) for r in rows if r["id"] not in ya_decididas]

@st.cache_data(ttl=60)
def last_sync() -> dict | None:
    conn = get_conn()
    r = conn.execute(
        "SELECT started_at, finished_at, proyectos_nuevos, proyectos_actualizados, errores "
        "FROM sync_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else None

@st.cache_data(ttl=60)
def load_proyectos(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
    conn = get_conn()
    sql = """
      SELECT p.per_par_id,
             p.cod_tipo_parl,
             p.pley_num,
             p.proyecto_ley AS "PL",
             p.tema AS "Tema",
             p.estado AS "Estado",
             date(p.fec_presentacion) AS "Presentado",
             date(p.last_changed_at) AS "Último cambio",
             p.grupo_parlamentario AS "Partido",
             p.proponente AS "Proponente",
             p.autores_raw AS "Autor(es)",
             CASE WHEN c.tipo IN ('Ordinaria', 'Senado', 'Diputados', 'Bicameral') THEN c.nombre
                  WHEN c.tipo = 'Especial'  THEN ?
                  ELSE NULL END AS "Comisión",
             p.titulo AS "Título",
             p.url_portal AS "Portal",
             p.url_pdf AS "PDF"
      FROM proyectos p
      LEFT JOIN proyecto_comision pc
             ON pc.per_par_id = p.per_par_id AND pc.cod_tipo_parl = p.cod_tipo_parl
             AND pc.pley_num = p.pley_num
      LEFT JOIN comisiones c
             ON c.comision_id = pc.comision_id
    """
    # per_par_id=? acota al Congreso bicameral vigente — el histórico 2021-2026
    # queda en la DB pero desconectado de esta página (pedido de Nicolas, 2026-09-11).
    where, params = ["p.per_par_id = ?"], [COMISIONES_ESPECIALES_LABEL, PER_PAR_ID_ACTUAL]
    if fec_inicio:
        where.append("date(p.fec_presentacion) >= ?"); params.append(fec_inicio.isoformat())
    if fec_fin:
        where.append("date(p.fec_presentacion) <= ?"); params.append(fec_fin.isoformat())
    sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.fec_presentacion DESC, p.pley_num DESC"
    df = pd.read_sql_query(sql, conn, params=params)
    if not df.empty:
        # Agrupar por (per_par_id, cod_tipo_parl, pley_num), NO solo pley_num:
        # cada período reinicia su numeración desde 1 (bug real que hacía
        # "desaparecer" PLs del período 2026 al fusionarse con el 2021), y
        # DENTRO del período bicameral cada cámara (Congreso/Diputados/Senado)
        # TAMBIÉN reinicia su propia numeración — el PL D-1, S-1 y C-1 del
        # 2026-2031 son tres proyectos distintos que comparten número.
        df = df.groupby(["per_par_id", "cod_tipo_parl", "pley_num"], as_index=False).agg({
            "PL": "first", "Tema": "first", "Estado": "first",
            "Presentado": "first", "Último cambio": "first",
            "Partido": "first", "Proponente": "first", "Autor(es)": "first",
            "Comisión": lambda s: sorted({str(x) for x in s if isinstance(x, str) and x}),
            "Título": "first", "Portal": "first", "PDF": "first",
        })
        df["_comisiones_all"] = df["Comisión"]
        df["Comisión"] = df["Comisión"].apply(lambda lst: lst[0] if lst else "—")
        # Sort: fecha de presentacion DESC, y dentro del mismo dia per_par_id+
        # pley_num DESC (el ultimo numero asignado es el mas reciente). Sin
        # esto como tiebreaker, los PLs del mismo dia salian en orden inestable.
        df = df.sort_values(
            ["Presentado", "per_par_id", "cod_tipo_parl", "pley_num"],
            ascending=[False, False, False, False],
        ).reset_index(drop=True)
        df["Cámara"] = df["cod_tipo_parl"].map(CAMARA_LABEL).fillna(df["cod_tipo_parl"])
    return df

def _upsert_live_pls(nuevos_api: list[dict], per_par_id: int = PER_PAR_ID_ACTUAL) -> int:
    """Inserta PLs detectados en la API que no estan en la DB local.

    En Streamlit Cloud la DB es ephemeral, pero los writes persisten
    durante el runtime. El proximo cron de GH Actions hace el sync
    completo con todos los campos (sumilla, autores, comisiones, etc) y
    los reescribe correctamente. Mientras tanto, estos inserts ligeros
    hacen que el usuario vea los PLs en la tabla principal de inmediato.

    Campos disponibles del endpoint /lista-con-filtro:
      pleyNum, codTipoParl, titulo (o descTitulo), estado, fecPresentacion
    Campos sin valor (NULL): sumilla, proponente, grupo_parlamentario,
      autores_raw, url_portal, url_pdf, comisiones. Se completan en el
      proximo cron via /expediente.
    """
    db = base("proyectos.db")
    if db is None:
        return 0
    from datetime import datetime, timezone
    from scraper.api import portal_url
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    inserted = 0
    try:
        conn = sqlite3.connect(str(db), check_same_thread=False)
        try:
            for p in nuevos_api:
                pley_num = p.get("pleyNum")
                if not pley_num:
                    continue
                cod_tipo_parl = p.get("codTipoParl") or "C"
                titulo = p.get("titulo") or p.get("descTitulo") or "(sin titulo)"
                estado = p.get("estado") or "PRESENTADO"
                fec_pres = p.get("fecPresentacion") or ""
                portal = portal_url(per_par_id, pley_num, cod_tipo_parl)
                # INSERT OR IGNORE — si ya esta (race con cron), no pisa
                conn.execute(
                    """INSERT OR IGNORE INTO proyectos
                       (per_par_id, cod_tipo_parl, pley_num, titulo, estado, fec_presentacion,
                        url_portal, first_seen_at, last_seen_at, last_changed_at,
                        tema, tema_manual)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Otros', 0)""",
                    (per_par_id, cod_tipo_parl, pley_num, titulo, estado, fec_pres,
                     portal, now, now, now),
                )
                if conn.total_changes > inserted:
                    inserted += 1
            conn.commit()
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        # DB locked (otra escritura en curso) o readonly — ignorar silente
        print(f"[live-upsert] skip: {e}")
        return 0
    return inserted

@st.cache_data(ttl=300)  # cache 5 min: tras la primera carga del dia,
                          # los siguientes 5 min son instant para todos
def fetch_live_pe(per_par_id: int = PER_PAR_ID_ACTUAL) -> dict:
    """Consulta la API del Congreso PE en TIEMPO REAL y devuelve la lista
    actual de PLs. Compara con la DB local para identificar los que no
    estan sincronizados todavia.

    Recorre las 3 cámaras (Congreso/Diputados/Senado) del período bicameral
    — sin esto, la API solo devuelve los PLs 'C' (ver scraper/sync.py,
    camaras_de). Tarda ~10-30 seg por cámara.

    Returns:
        {
            "total_api": int,
            "total_db": int,
            "nuevos": [{"pley_num", "titulo", "estado", "fec_presentacion"}, ...],
            "error": str | None,
        }
    """
    from concurrent.futures import ThreadPoolExecutor
    from scraper.sync import camaras_de

    try:
        from scraper.api import ApiClient
        camaras = camaras_de(per_par_id)
        # Una cámara por request y ~10-30s cada una — en paralelo (cada
        # thread con su propio ApiClient/Session, más simple y seguro que
        # compartir una sesión entre threads) en vez de secuencial, así el
        # período bicameral (3 cámaras) no triplica la latencia de carga.
        with ThreadPoolExecutor(max_workers=len(camaras) or 1) as pool:
            resultados = pool.map(
                lambda cam: ApiClient().list_all_proyectos(per_par_id=per_par_id, cod_tipo_parl=cam),
                camaras,
            )
            api_pls: list[dict] = [p for lote in resultados for p in lote]
    except Exception as e:
        return {"total_api": 0, "total_db": 0, "nuevos": [], "error": str(e)}

    # Set de (cod_tipo_parl, pley_num) que ya tenemos en DB — cada cámara
    # numera desde 1, así que pley_num solo no alcanza para el diff.
    conn = get_conn()
    try:
        db_keys = {
            (r[0], r[1]) for r in conn.execute(
                "SELECT cod_tipo_parl, pley_num FROM proyectos WHERE per_par_id = ?",
                (per_par_id,),
            )
        }
    finally:
        conn.close()

    api_keys = {
        (p.get("codTipoParl") or "C", p.get("pleyNum"))
        for p in api_pls if p.get("pleyNum")
    }
    nuevos_keys = api_keys - db_keys

    # Items raw para upsert directo a la DB (no solo display)
    nuevos_raw = [
        p for p in api_pls
        if ((p.get("codTipoParl") or "C"), p.get("pleyNum")) in nuevos_keys
    ]
    # AUTO-UPSERT: escribir los nuevos a la DB ya mismo para que aparezcan
    # integrados en la tabla principal (sin necesidad de banner separado).
    inserted = _upsert_live_pls(nuevos_raw, per_par_id=per_par_id)

    return {
        "total_api": len(api_keys),
        "total_db": len(db_keys),
        # "nuevos": lista para el botón "Buscar PLs nuevos en vivo" (bug
        # preexistente: antes solo se devolvía nuevos_count, un int, y la UI
        # esperaba esta lista — KeyError en cada click). "nuevos_count" se
        # mantiene por compatibilidad con quien lo estuviera leyendo.
        "nuevos": [
            {
                "PL": p.get("proyectoLey") or f"{p.get('pleyNum')} ({p.get('codTipoParl') or 'C'})",
                "titulo": p.get("titulo") or p.get("descTitulo"),
                "estado": p.get("estado"),
                "fec_presentacion": p.get("fecPresentacion"),
            }
            for p in nuevos_raw
        ],
        "nuevos_count": len(nuevos_raw),
        "inserted": inserted,
        "error": None,
    }

def _sync_status() -> dict:
    """Devuelve estado del último sync: minutos desde el último completado,
    si hay uno corriendo, y métricas del último."""
    conn = get_conn()
    try:
        running = conn.execute(
            "SELECT id FROM sync_runs WHERE finished_at IS NULL "
            "AND started_at > datetime('now', ?, 'utc') LIMIT 1",
            (f"-{SYNC_STALE_MINUTES} minutes",),
        ).fetchone()
        last = conn.execute(
            "SELECT started_at, finished_at, proyectos_nuevos, proyectos_actualizados, errores, "
            "       (julianday('now') - julianday(finished_at)) * 24 * 60 AS mins_ago "
            "FROM sync_runs WHERE finished_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return {
        "running": running is not None,
        "last": dict(last) if last else None,
        "mins_ago": (last["mins_ago"] if last else None),
    }

def maybe_fire_background_sync() -> str:
    """Auto-sync silencioso. Lanza `scraper update` en segundo plano si el
    último completó hace > SYNC_MIN_MINUTES y no hay uno corriendo. Devuelve
    el estado para mostrar en UI: 'fresh' | 'running' | 'started'."""
    status = _sync_status()
    if status["running"]:
        return "running"
    mins = status["mins_ago"]
    if mins is not None and mins < SYNC_MIN_MINUTES:
        return "fresh"
    # Lanzar en segundo plano, sin esperar
    db = base("proyectos.db")
    cwd = str(db.parent) if db else str(Path(__file__).resolve().parent.parent)
    creationflags = 0
    if sys.platform == "win32":
        # No abrir nueva ventana en Windows
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "scraper.cli", "update"],
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return "started"
    except Exception:
        return "fresh"
