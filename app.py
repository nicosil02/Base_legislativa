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
    # "Comisión" (visible) = la primera (principal).
    # "_comisiones_all" (oculta) = lista completa para que el filtro busque en todas.
    if not df.empty:
        df = df.groupby("pley_num", as_index=False).agg({
            "PL": "first", "Tema": "first", "Estado": "first",
            "Presentado": "first", "Último cambio": "first",
            "Partido": "first", "Proponente": "first", "Autor(es)": "first",
            "Comisión": lambda s: sorted({str(x) for x in s if isinstance(x, str) and x}),
            "Título": "first", "Portal": "first", "PDF": "first",
        })
        df["_comisiones_all"] = df["Comisión"]
        df["Comisión"] = df["Comisión"].apply(lambda lst: lst[0] if lst else None)
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

TODOS = "Todos"
TODAS = "Todas"


def _opciones(col: str, label_todos: str = TODOS) -> list[str]:
    """[label_todos] + valores únicos no nulos de la columna, ordenados."""
    if col not in df_full.columns:
        return [label_todos]
    vals = sorted({str(v) for v in df_full[col].dropna().unique() if str(v).strip()})
    return [label_todos] + vals


def _opciones_comision() -> list[str]:
    """Todas las comisiones que aparecen en cualquier PL (incluso si no son la principal)."""
    if "_comisiones_all" not in df_full.columns:
        return [TODAS]
    todos: set[str] = set()
    for lst in df_full["_comisiones_all"]:
        if isinstance(lst, list):
            todos.update(x for x in lst if isinstance(x, str) and x.strip())
    return [TODAS] + sorted(todos)


# Fila 1: 6 selectboxes (single-select) con "Todos" por defecto.
fc = st.columns([1, 1, 1, 1.2, 1, 1])
pl_input = fc[0].text_input("PL", placeholder="ej. 14515", help="Búsqueda parcial: '143' matchea 14300-14399")
sel_tema = fc[1].selectbox("Tema", _opciones("Tema"))
sel_estado = fc[2].selectbox("Estado", _opciones("Estado"))
sel_comision = fc[3].selectbox("Comisión", _opciones_comision())
sel_partido = fc[4].selectbox("Partido", _opciones("Partido"))
sel_proponente = fc[5].selectbox("Proponente", _opciones("Proponente"))

# Fila 2: búsqueda libre por texto en título / autor.
busqueda = st.text_input(
    "Buscar en título o autor",
    placeholder="🔍  título o nombre de autor — ej. biometría, Cruz Mamani...",
    label_visibility="collapsed",
)

# Aplicar filtros al dataframe.
df = df_full
if pl_input.strip():
    df = df[df["PL"].astype(str).str.contains(pl_input.strip(), case=False, na=False)]
if sel_tema != TODOS:
    df = df[df["Tema"] == sel_tema]
if sel_estado != TODOS:
    df = df[df["Estado"] == sel_estado]
if sel_comision != TODAS:
    # Busca en TODAS las comisiones del PL (no solo la principal mostrada).
    df = df[df["_comisiones_all"].apply(lambda lst: isinstance(lst, list) and sel_comision in lst)]
if sel_partido != TODOS:
    df = df[df["Partido"] == sel_partido]
if sel_proponente != TODOS:
    df = df[df["Proponente"] == sel_proponente]
if busqueda.strip():
    q = busqueda.strip().lower()
    mask = (
        df["Título"].astype(str).str.lower().str.contains(q, na=False)
        | df["Autor(es)"].astype(str).str.lower().str.contains(q, na=False)
    )
    df = df[mask]

st.markdown(f"#### {len(df):,} proyecto(s) — de {len(df_full):,} en el rango de fechas")

# Orden exacto: PL, Título, Presentado, Estado, Último cambio, Proponente,
# Autor, Partido, Comisión, Tema, Portal, PDF.
ORDEN_COLS = [
    "PL", "Título", "Presentado", "Estado", "Último cambio",
    "Proponente", "Autor(es)", "Partido", "Comisión", "Tema",
    "Portal", "PDF",
]
df_view = df.drop(columns=["pley_num", "_comisiones_all"], errors="ignore")
df_view = df_view[[c for c in ORDEN_COLS if c in df_view.columns]]

st.caption(
    "💡 Click en una fila para ver el detalle completo (sumilla, todas las comisiones, historial). "
    "Click en los headers para ordenar."
)

# Tabla nativa de Streamlit con selección de fila + row_height alto para que
# entren al menos 2 líneas de texto por celda. Sorting integrado por header.
tabla_event = st.dataframe(
    df_view,
    hide_index=True,
    use_container_width=True,
    height=720,
    row_height=72,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "PL":            st.column_config.TextColumn("PL",            width="medium", pinned=True),
        "Título":        st.column_config.TextColumn("Título",        width="large"),
        "Presentado":    st.column_config.TextColumn("Presentado",    width="small"),
        "Estado":        st.column_config.TextColumn("Estado",        width="medium"),
        "Último cambio": st.column_config.TextColumn("Últ. cambio",   width="small"),
        "Proponente":    st.column_config.TextColumn("Proponente",    width="medium"),
        "Autor(es)":     st.column_config.TextColumn("Autor(es)",     width="medium"),
        "Partido":       st.column_config.TextColumn("Partido",       width="medium"),
        "Comisión":      st.column_config.TextColumn("Comisión (princ.)", width="medium",
                                                     help="Comisión principal. El filtro busca en TODAS las comisiones del PL."),
        "Tema":          st.column_config.TextColumn("Tema",          width="medium"),
        "Portal":        st.column_config.LinkColumn("Portal", display_text="abrir", width="small"),
        "PDF":           st.column_config.LinkColumn("PDF",    display_text="ver",   width="small"),
    },
)

# ---------- Panel de detalle del PL seleccionado ----------
sel_rows = tabla_event.selection.rows if hasattr(tabla_event, "selection") else []
if sel_rows:
    sel_idx = sel_rows[0]
    if sel_idx < len(df):
        row = df.iloc[sel_idx]
        pley_num = int(row["pley_num"])
        st.markdown("---")
        st.markdown(f"### {row['PL']} — {row['Título']}")

        meta_cols = st.columns(5)
        meta_cols[0].markdown(f"**Estado**\n\n{row['Estado']}")
        meta_cols[1].markdown(f"**Tema**\n\n{row['Tema']}")
        meta_cols[2].markdown(f"**Partido**\n\n{row['Partido'] or '—'}")
        meta_cols[3].markdown(f"**Proponente**\n\n{row['Proponente'] or '—'}")
        meta_cols[4].markdown(f"**Presentado**\n\n{row['Presentado']}")

        comisiones_all = row.get("_comisiones_all") or []
        if isinstance(comisiones_all, list) and comisiones_all:
            st.markdown(f"**Comisiones asignadas:** {' · '.join(comisiones_all)}")

        conn = get_conn()
        extra = conn.execute(
            "SELECT sumilla, autores_raw FROM proyectos WHERE per_par_id=2021 AND pley_num=?",
            (pley_num,),
        ).fetchone()
        if extra and extra["sumilla"]:
            st.markdown("**Sumilla**")
            st.write(extra["sumilla"])
        if extra and extra["autores_raw"]:
            st.markdown("**Autores (completo)**")
            st.write(extra["autores_raw"])

        segs = conn.execute(
            "SELECT fecha, estado, comisiones, observacion FROM seguimientos "
            "WHERE per_par_id=2021 AND pley_num=? ORDER BY fecha DESC",
            (pley_num,),
        ).fetchall()
        if segs:
            st.markdown("**Historial de cambios**")
            seg_df = pd.DataFrame([dict(s) for s in segs])
            seg_df["fecha"] = pd.to_datetime(seg_df["fecha"]).dt.strftime("%Y-%m-%d")
            seg_df = seg_df.rename(columns={
                "fecha": "Fecha", "estado": "Estado",
                "comisiones": "Comisiones", "observacion": "Observación",
            })
            st.dataframe(seg_df, hide_index=True, use_container_width=True)

        link_cols = st.columns(2)
        if isinstance(row.get("Portal"), str):
            link_cols[0].markdown(f"[Abrir expediente en el portal del Congreso]({row['Portal']})")
        if isinstance(row.get("PDF"), str):
            link_cols[1].markdown(f"[Descargar PDF]({row['PDF']})")

st.markdown("---")
st.caption(
    "Filtros: dropdowns arriba (Todos = sin filtro) · "
    "Click en los headers de la tabla para ordenar (asc/desc) · "
    "Datos: api.congreso.gob.pe/spley-portal-service · "
    "Clasificación temática híbrida (Excel + reglas)"
)
