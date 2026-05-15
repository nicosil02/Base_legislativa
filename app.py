"""Dashboard institucional de proyectos de ley.

Corre con:
    python -m streamlit run app.py

Lee `proyectos.db` en read-only. Tabla AgGrid con filtros multi-select por
columna en el header. Tema claro / institucional. Date range picker.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, ColumnsAutoSizeMode, GridOptionsBuilder, GridUpdateMode

DB_PATH = Path(__file__).parent / "proyectos.db"
COMISIONES_ESPECIALES_LABEL = "Comisiones Especiales"

st.set_page_config(
    page_title="Base Legislativa — Proyectos de Ley",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- CSS institucional ----------
st.markdown(
    """
    <style>
    /* Fondo claro general */
    .stApp { background-color: #FFFFFF; }
    section[data-testid="stSidebar"] { background-color: #F4F6F8; border-right: 1px solid #E5E7EB; }
    /* Header del título */
    h1 { color: #0B3E5C; font-weight: 600; letter-spacing: -0.5px; }
    h2, h3 { color: #0B3E5C; font-weight: 500; }
    /* Métricas como cards */
    div[data-testid="stMetric"] {
        background-color: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 8px;
        padding: 12px 16px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    div[data-testid="stMetricLabel"] { color: #6B7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    div[data-testid="stMetricValue"] { color: #0B3E5C; font-weight: 600; }
    /* Reducir padding superior */
    .block-container { padding-top: 1.5rem; }
    /* Sync info card */
    .sync-card { background:#FFFFFF; border:1px solid #E5E7EB; border-radius:8px; padding:12px; font-size:13px; }
    .sync-card .label { color:#6B7280; text-transform:uppercase; font-size:11px; letter-spacing:0.5px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============ DB helpers ============

@st.cache_resource
def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        st.error(f"No se encontró {DB_PATH}. Corre `python -m scraper.cli init` primero.")
        st.stop()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    temas = sorted(
        r[0] for r in conn.execute("SELECT DISTINCT tema FROM proyectos WHERE tema IS NOT NULL")
    )
    estados = sorted(
        r[0] for r in conn.execute("SELECT DISTINCT estado FROM proyectos WHERE estado IS NOT NULL")
    )
    proponentes = sorted(
        r[0] for r in conn.execute("SELECT DISTINCT proponente FROM proyectos WHERE proponente IS NOT NULL")
    )
    partidos = sorted(
        r[0] for r in conn.execute("SELECT DISTINCT grupo_parlamentario FROM proyectos WHERE grupo_parlamentario IS NOT NULL")
    )
    # Comisiones: sólo las Ordinarias (alfabéticamente) + grupo "Comisiones Especiales".
    ordinarias = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT c.nombre FROM comisiones c "
            "JOIN proyecto_comision pc USING(comision_id) "
            "WHERE c.tipo = 'Ordinaria' ORDER BY c.nombre"
        )
    ]
    # Detectar si hay PLs en comisiones Especiales (para mostrar el grupo).
    tiene_especiales = conn.execute(
        "SELECT 1 FROM proyecto_comision pc JOIN comisiones c USING(comision_id) "
        "WHERE c.tipo = 'Especial' LIMIT 1"
    ).fetchone() is not None
    comisiones_opciones = list(ordinarias)
    if tiene_especiales:
        comisiones_opciones.append(COMISIONES_ESPECIALES_LABEL)
    # Rango de fechas disponible
    fec_min, fec_max = conn.execute(
        "SELECT MIN(date(fec_presentacion)), MAX(date(fec_presentacion)) FROM proyectos"
    ).fetchone()
    return {
        "temas": temas,
        "estados": estados,
        "proponentes": proponentes,
        "partidos": partidos,
        "comisiones": comisiones_opciones,
        "fec_min": fec_min,
        "fec_max": fec_max,
    }


@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    """Cuenta KPIs con LIKE flexible para Ley Publicada."""
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
           FROM proyectos"""
    ).fetchone()
    return {
        "Total proyectos": r["total"] or 0,
        "Presentados": r["presentados"] or 0,
        "En comisión": r["en_comision"] or 0,
        "Con dictamen": r["dictamen"] or 0,
        "Autógrafas": r["autografa"] or 0,
        "Ley publicada": r["ley_publicada"] or 0,
    }


@st.cache_data(ttl=60)
def last_sync() -> dict | None:
    conn = get_conn()
    r = conn.execute(
        "SELECT started_at, finished_at, proyectos_nuevos, proyectos_actualizados, errores "
        "FROM sync_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else None


@st.cache_data(ttl=60)
def load_proyectos(
    fec_inicio: dt.date | None,
    fec_fin: dt.date | None,
) -> pd.DataFrame:
    """Carga TODOS los proyectos (filtrados sólo por rango de fechas — el resto
    de filtros se aplican en AgGrid en el cliente)."""
    conn = get_conn()
    sql = """
      SELECT p.pley_num,
             p.proyecto_ley AS "PL",
             p.tema AS "Tema",
             p.estado AS "Estado",
             date(p.fec_presentacion) AS "Presentado",
             date(p.last_changed_at) AS "Último cambio",
             p.grupo_parlamentario AS "Partido",
             p.proponente AS "Proponente",
             p.autores_raw AS "Autor(es)",
             CASE WHEN c.tipo = 'Ordinaria' THEN c.nombre
                  WHEN c.tipo = 'Especial'  THEN ?
                  ELSE NULL END AS "Comisión",
             p.titulo AS "Título",
             p.url_portal AS "Portal",
             p.url_pdf AS "PDF"
      FROM proyectos p
      LEFT JOIN proyecto_comision pc
             ON pc.per_par_id = p.per_par_id AND pc.pley_num = p.pley_num
      LEFT JOIN comisiones c
             ON c.comision_id = pc.comision_id
    """
    where, params = [], [COMISIONES_ESPECIALES_LABEL]
    if fec_inicio:
        where.append("date(p.fec_presentacion) >= ?")
        params.append(fec_inicio.isoformat())
    if fec_fin:
        where.append("date(p.fec_presentacion) <= ?")
        params.append(fec_fin.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.fec_presentacion DESC, p.pley_num DESC"
    df = pd.read_sql_query(sql, conn, params=params)
    # Deduplicar: un PL puede aparecer varias veces si está en >1 comisión.
    # Para el dashboard, colapso comisiones del mismo PL en una sola fila con "X | Y".
    if not df.empty:
        df = df.groupby("pley_num", as_index=False).agg({
            "PL": "first", "Tema": "first", "Estado": "first",
            "Presentado": "first", "Último cambio": "first",
            "Partido": "first", "Proponente": "first", "Autor(es)": "first",
            "Comisión": lambda s: " | ".join(sorted({str(x) for x in s if isinstance(x, str) and x})) or None,
            "Título": "first", "Portal": "first", "PDF": "first",
        })
        df = df.sort_values("Presentado", ascending=False).reset_index(drop=True)
    return df


def run_update_now() -> tuple[int, str]:
    cmd = [sys.executable, "-m", "scraper.cli", "update"]
    res = subprocess.run(cmd, cwd=str(Path(__file__).parent), capture_output=True, text=True, timeout=900)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


# ============ UI ============

st.title("Base Legislativa — Proyectos de Ley del Congreso del Perú")
st.caption("Período 2021–2026 · Fuente: api.congreso.gob.pe/spley-portal-service")

# ---------- KPIs ----------
totals = kpi_totals()
cols = st.columns(len(totals))
for col, (label, val) in zip(cols, totals.items()):
    col.metric(label, f"{val:,}")

st.markdown("")

cats = load_catalogs()

# ---------- Sidebar: rango de fechas + sync ----------
with st.sidebar:
    st.markdown("### Rango de fechas (presentación)")
    fec_min_iso = cats["fec_min"] or "2021-07-28"
    fec_max_iso = cats["fec_max"] or dt.date.today().isoformat()
    fec_min = dt.date.fromisoformat(fec_min_iso)
    fec_max = dt.date.fromisoformat(fec_max_iso)
    rango = st.date_input(
        "Filtrar por presentación",
        value=(fec_min, fec_max),
        min_value=fec_min,
        max_value=fec_max,
        format="YYYY-MM-DD",
    )
    if isinstance(rango, tuple) and len(rango) == 2:
        f_ini, f_fin = rango
    else:
        f_ini, f_fin = fec_min, fec_max

    st.markdown("---")
    st.markdown("### Sync")
    last = last_sync()
    if last:
        st.markdown(
            f"""<div class="sync-card">
            <div class="label">Último run</div>
            <div>{last['started_at']}</div>
            <div class="label" style="margin-top:8px">Cambios</div>
            <div>Nuevos: <b>{last['proyectos_nuevos']}</b> · Actualizados: <b>{last['proyectos_actualizados']}</b> · Errores: <b>{last['errores']}</b></div>
            </div>""",
            unsafe_allow_html=True,
        )
    if st.button("🔄  Actualizar ahora", use_container_width=True):
        with st.spinner("Corriendo `scraper update`..."):
            code, out = run_update_now()
        if code == 0:
            st.success("Sync completado")
            st.cache_data.clear()
        else:
            st.error("Falló el sync — revisa el log")
        with st.expander("Output del sync"):
            st.code(out)

# ---------- Tabla con barra de filtros propios ----------
df_full = load_proyectos(f_ini, f_fin)

def _opciones(col: str) -> list[str]:
    """Valores únicos no nulos de una columna del dataframe completo, ordenados."""
    if col not in df_full.columns:
        return []
    return sorted({str(v) for v in df_full[col].dropna().unique() if str(v).strip()})


# Fila 1: 5 dropdowns multi-select con flecha. Vacío = "Todos".
fc = st.columns([1, 1, 1.2, 1, 1])
sel_tema = fc[0].multiselect("Tema", _opciones("Tema"), placeholder="Todos")
sel_estado = fc[1].multiselect("Estado", _opciones("Estado"), placeholder="Todos")
sel_comision = fc[2].multiselect("Comisión", _opciones("Comisión"), placeholder="Todas")
sel_partido = fc[3].multiselect("Partido", _opciones("Partido"), placeholder="Todos")
sel_proponente = fc[4].multiselect("Proponente", _opciones("Proponente"), placeholder="Todos")

# Fila 2: búsqueda libre por texto.
busqueda = st.text_input(
    "🔍 Buscar por PL, título o autor",
    placeholder="ej. 14515, biometría, Cruz Mamani...",
    label_visibility="collapsed",
)

# Aplicar filtros al dataframe.
df = df_full
if sel_tema:
    df = df[df["Tema"].isin(sel_tema)]
if sel_estado:
    df = df[df["Estado"].isin(sel_estado)]
if sel_comision:
    df = df[df["Comisión"].isin(sel_comision)]
if sel_partido:
    df = df[df["Partido"].isin(sel_partido)]
if sel_proponente:
    df = df[df["Proponente"].isin(sel_proponente)]
if busqueda.strip():
    q = busqueda.strip().lower()
    mask = (
        df["PL"].astype(str).str.lower().str.contains(q, na=False)
        | df["Título"].astype(str).str.lower().str.contains(q, na=False)
        | df["Autor(es)"].astype(str).str.lower().str.contains(q, na=False)
    )
    df = df[mask]

st.markdown(f"#### {len(df):,} proyecto(s) — de {len(df_full):,} en el rango de fechas")

if df.empty:
    st.info("Sin proyectos que cumplan los filtros.")
else:
    gb = GridOptionsBuilder.from_dataframe(df.drop(columns=["pley_num"]))
    # Por columna: sortable + resizable, SIN floating filters
    # (los filtros viven arriba de la tabla, en Streamlit).
    gb.configure_default_column(
        sortable=True,
        resizable=True,
        filter=False,
        floatingFilter=False,
        wrapHeaderText=True,
        autoHeaderHeight=True,
    )
    gb.configure_column("PL", width=140, pinned="left", filter="agTextColumnFilter")
    gb.configure_column("Presentado", width=120)
    gb.configure_column("Último cambio", width=130)
    gb.configure_column("Título", width=400, tooltipField="Título", wrapText=True)
    gb.configure_column("Autor(es)", width=220, tooltipField="Autor(es)")
    gb.configure_column(
        "Portal",
        width=100,
        cellRenderer="""function(p){return p.value?`<a href="${p.value}" target="_blank">abrir</a>`:''}""",
    )
    gb.configure_column(
        "PDF",
        width=80,
        cellRenderer="""function(p){return p.value?`<a href="${p.value}" target="_blank">ver</a>`:''}""",
    )
    gb.configure_grid_options(
        domLayout="normal",
        pagination=True,
        paginationPageSize=25,
        paginationPageSizeSelector=[25, 50, 100, 200, 500],
        rowSelection="single",
        animateRows=True,
    )

    AgGrid(
        df.drop(columns=["pley_num"]),
        gridOptions=gb.build(),
        height=620,
        theme="alpine",
        update_mode=GridUpdateMode.NO_UPDATE,
        columns_auto_size_mode=ColumnsAutoSizeMode.NO_AUTOSIZE,
        allow_unsafe_jscode=True,
        enable_enterprise_modules=False,
        fit_columns_on_grid_load=False,
    )

st.markdown("---")
st.caption(
    "Filtros: dropdowns multi-select arriba (vacío = todos) y búsqueda libre · "
    "Click en los headers de la tabla para ordenar · "
    "Datos: api.congreso.gob.pe/spley-portal-service · "
    "Clasificación temática híbrida (Excel + reglas)"
)
