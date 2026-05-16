"""Radar Legislativo — Perú · Congreso de la República.

Vista de proyectos de ley del período 2021-2026. Lee proyectos.db en read-only.
Diseño inspirado en datadaf.com: tipografía Inter, headings en peso 900,
acentos azules, mucho whitespace.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

COMISIONES_ESPECIALES_LABEL = "Comisiones Especiales"


def _find_db_path() -> Path | None:
    """Busca proyectos.db en varias ubicaciones razonables.

    Necesario porque Streamlit puede arrancar desde directorios distintos
    según cómo lo invocaste (raíz del repo, worktree, etc.).
    """
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "proyectos.db",       # <repo>/proyectos.db (pages está en <repo>/pages)
        Path.cwd() / "proyectos.db",        # CWD donde se ejecuta streamlit
    ]
    # Caminar hacia arriba 5 niveles desde el archivo actual
    cur = here
    for _ in range(5):
        candidates.append(cur / "proyectos.db")
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None

st.set_page_config(
    page_title="Radar Legislativo · Perú",
    page_icon="🇵🇪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# El logo Vali se setea desde app.py (entrada de navegación). No hace falta
# repetir st.logo() en cada página.

# ====================== CSS estilo datadaf ======================
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
:root {
      /* Paleta corporativa Vali Consultores */
      --ink:        #0A294D;   /* navy principal — titulos y texto */
      --ink-soft:   #435D74;   /* navy medio — texto secundario */
      --ink-mute:   #869FB2;   /* gris azulado — texto suave / labels */
      --line:       #CFD9E0;   /* borde y separador */
      --line-soft:  #E3E9ED;
      --accent:     #0A294D;   /* navy como acento institucional */
      --accent-red: #BF1A1A;   /* rojo Vali (del puntito del logo) */
      --bg:         #FFFFFF;
      --bg-soft:    #F4F6F8;
    }

    html, body, [class*="css"], .stApp {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
      color: var(--ink);
      background-color: var(--bg);
    }

    .stApp { background-color: var(--bg); }

    /* === Sidebar navy + texto blanco === */
    section[data-testid="stSidebar"] {
      background-color: var(--ink) !important;
      border-right: 0 !important;
    }
    section[data-testid="stSidebar"] *,
    section[data-testid="stSidebar"] a,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] span {
      color: #FFFFFF !important;
      font-family: 'Inter', sans-serif !important;
    }
    /* Nav links activos / hover */
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
      background-color: transparent !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
      background-color: rgba(255,255,255,0.06) !important;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarNav"] [aria-current="page"] {
      background-color: rgba(255,255,255,0.10) !important;
    }

    /* Cards internas del sidebar (date input, sync card) mantienen fondo blanco */
    section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
    section[data-testid="stSidebar"] .sync-card {
      background-color: #FFFFFF !important;
    }
    section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
    section[data-testid="stSidebar"] .sync-card,
    section[data-testid="stSidebar"] .sync-card * {
      color: var(--ink) !important;
    }
    section[data-testid="stSidebar"] .sync-card .label {
      color: var(--ink-mute) !important;
    }

    /* === Ocultar TODO texto crudo de Material Symbols/Icons en sidebar === */
    /* Cualquier elemento con clase relacionada a iconos Material, en sidebar */
    [data-testid="stSidebar"] [class*="material-symbols"],
    [data-testid="stSidebar"] [class*="material-icons"],
    [data-testid="stSidebar"] [class*="MaterialSymbols"],
    [data-testid="stSidebar"] [class*="MaterialIcons"],
    [data-testid="stSidebar"] span[aria-hidden="true"]:not([class*="emoji"]),
    [data-testid="stSidebar"] i[class*="icon"] {
      font-size: 0 !important;
      color: transparent !important;
      line-height: 0 !important;
      visibility: hidden !important;
    }
    /* Botones del header del sidebar (collapse) — esconder texto, poner icono propio */
    [data-testid="stSidebarHeader"] button,
    [data-testid="stSidebarHeader"] button *,
    button[data-testid="stExpandSidebarButton"],
    button[data-testid="stExpandSidebarButton"] *,
    button[data-testid="stSidebarCollapsedControl"],
    button[data-testid="stSidebarCollapsedControl"] *,
    button[kind="header"],
    button[kind="header"] * {
      font-size: 0 !important;
      color: transparent !important;
      line-height: 0 !important;
    }
    [data-testid="stSidebarHeader"] button::before,
    button[data-testid="stExpandSidebarButton"]::before,
    button[kind="header"]::before {
      content: "‹" !important;
      font-size: 18px !important;
      color: #FFFFFF !important;
      visibility: visible !important;
      display: inline-block !important;
      line-height: 1 !important;
      font-family: 'Inter', sans-serif !important;
    }

    /* === Logo Vali: tamaño cómodo, centrado al tope === */
    [data-testid="stSidebarHeader"] {
      padding: 24px 16px 20px 16px !important;
      display: flex !important;
      justify-content: center !important;
      align-items: center !important;
      min-height: 220px !important;
      background-color: var(--ink) !important;
    }
    [data-testid="stLogo"] {
      margin: 0 auto !important;
      display: block !important;
    }
    [data-testid="stLogo"] img {
      max-height: 200px !important;
      height: 200px !important;
      width: auto !important;
      max-width: 200px !important;
      margin: 0 auto !important;
      display: block !important;
    }

    /* Reduce padding superior */
    .block-container {
      padding-top: 2rem;
      padding-bottom: 4rem;
      max-width: 1400px;
    }

    /* === Hero del país === */
    .country-eyebrow {
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.25em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 12px;
    }
    .country-title {
      font-size: clamp(2.5rem, 5vw, 3.75rem);
      font-weight: 900;
      letter-spacing: -0.03em;
      line-height: 0.95;
      color: var(--ink);
      margin: 0 0 10px 0;
    }
    .country-title .accent { color: var(--accent); }
    .country-title .period {
      font-weight: 500;
      color: var(--ink-soft);
      font-size: 0.7em;
      letter-spacing: -0.01em;
    }
    .country-subtitle {
      font-size: 1.15rem;
      color: var(--ink-soft);
      /* full-width, alineado al ancho del contenedor / tabla */
      line-height: 1.6;
      margin-bottom: 36px;
    }

    /* === KPIs === */
    div[data-testid="stMetric"] {
      background-color: var(--bg);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px 18px;
      box-shadow: none;
      transition: border-color .2s;
    }
    div[data-testid="stMetric"]:hover { border-color: var(--ink-mute); }
    div[data-testid="stMetricLabel"] {
      color: var(--ink-soft) !important;
      font-size: 10px !important;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-weight: 700 !important;
    }
    div[data-testid="stMetricValue"] {
      color: var(--ink) !important;
      font-weight: 900 !important;
      font-size: 2rem !important;
      letter-spacing: -0.02em;
    }

    /* === Section titles === */
    h2, h3 { font-weight: 800; color: var(--ink); letter-spacing: -0.01em; }

    /* === Filtros: labels centrados, uppercase chiquito === */
    label[data-testid="stWidgetLabel"] p {
      font-size: 10px !important;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      font-weight: 700;
      color: var(--ink-soft);
      text-align: center;
    }

    /* === Tabla === */
    div[data-testid="stDataFrame"] {
      border: 1px solid var(--line);
      border-radius: 12px;
      overflow: hidden;
    }
    /* Header de tabla: fondo navy Vali + letras blancas */
    div[data-testid="stDataFrame"] thead th,
    div[data-testid="stDataFrame"] [role="columnheader"] {
      background-color: var(--ink) !important;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-size: 11px !important;
      font-weight: 700 !important;
      color: #FFFFFF !important;
      border-bottom: 2px solid var(--ink) !important;
    }
    div[data-testid="stDataFrame"] thead th *,
    div[data-testid="stDataFrame"] [role="columnheader"] * {
      color: #FFFFFF !important;
    }
    div[data-testid="stDataFrame"] tbody td {
      font-size: 13px;
      line-height: 1.4;
      border-bottom: 1px solid var(--line-soft) !important;
    }

    /* === Sync card === */
    .sync-card {
      background: var(--bg);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 14px;
      font-size: 12.5px;
      color: var(--ink-soft);
    }
    .sync-card .label {
      color: var(--ink-mute);
      text-transform: uppercase;
      font-size: 10px;
      letter-spacing: 0.18em;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .sync-card .value { color: var(--ink); font-weight: 600; }

    /* === Detail panel === */
    .detail-card {
      background: var(--bg);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 28px 32px;
      margin-top: 28px;
    }
    .detail-eyebrow {
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: 10px;
    }
    .detail-title {
      font-size: 1.6rem;
      font-weight: 800;
      letter-spacing: -0.015em;
      line-height: 1.25;
      color: var(--ink);
      margin-bottom: 8px;
    }
    .detail-meta-label {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--ink-mute);
      margin-bottom: 4px;
    }
    .detail-meta-value {
      font-size: 14px;
      font-weight: 600;
      color: var(--ink);
    }
    .detail-section-title {
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--ink-soft);
      margin: 24px 0 8px 0;
    }

    /* Footer minimalista */
    .footer-rule {
      width: 32px; height: 2px; background: var(--ink);
      margin: 60px 0 14px 0;
    }
    .footer-text {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--ink-soft);
    }

    /* Esconde el footer 'Made with Streamlit' */
    footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============ DB helpers ============

def get_conn() -> sqlite3.Connection:
    """Abre una conexión fresca read-only a la DB.

    No cacheamos la conexión con @st.cache_resource porque eso producía
    'disk I/O error' cuando el handle se quedaba stale entre reruns o
    cambios de directorio.
    """
    db = _find_db_path()
    if db is None:
        st.error(
            "No encontré `proyectos.db`. Corre desde la carpeta raíz del repo:\n\n"
            "```\npython -m scraper.cli restaurar\n```"
        )
        st.stop()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=60)
def load_catalogs() -> dict:
    conn = get_conn()
    temas = sorted(r[0] for r in conn.execute("SELECT DISTINCT tema FROM proyectos WHERE tema IS NOT NULL"))
    estados = sorted(r[0] for r in conn.execute("SELECT DISTINCT estado FROM proyectos WHERE estado IS NOT NULL"))
    proponentes = sorted(r[0] for r in conn.execute("SELECT DISTINCT proponente FROM proyectos WHERE proponente IS NOT NULL"))
    partidos = sorted(r[0] for r in conn.execute("SELECT DISTINCT grupo_parlamentario FROM proyectos WHERE grupo_parlamentario IS NOT NULL"))
    fec_min, fec_max = conn.execute(
        "SELECT MIN(date(fec_presentacion)), MAX(date(fec_presentacion)) FROM proyectos"
    ).fetchone()
    return {
        "temas": temas, "estados": estados, "proponentes": proponentes,
        "partidos": partidos, "fec_min": fec_min, "fec_max": fec_max,
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
           FROM proyectos"""
    ).fetchone()
    return {
        "Total": r["total"] or 0,
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
def load_proyectos(fec_inicio: dt.date | None, fec_fin: dt.date | None) -> pd.DataFrame:
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
        where.append("date(p.fec_presentacion) >= ?"); params.append(fec_inicio.isoformat())
    if fec_fin:
        where.append("date(p.fec_presentacion) <= ?"); params.append(fec_fin.isoformat())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY p.fec_presentacion DESC, p.pley_num DESC"
    df = pd.read_sql_query(sql, conn, params=params)
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


SYNC_MIN_MINUTES = 5      # gap mínimo entre auto-syncs
SYNC_STALE_MINUTES = 15   # un sync sin terminar después de esto se considera muerto


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
    db = _find_db_path()
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


def _fmt_ago(mins: float | None) -> str:
    if mins is None:
        return "—"
    if mins < 1:
        return "hace segundos"
    if mins < 60:
        return f"hace {int(mins)} min"
    h = mins / 60
    if h < 24:
        return f"hace {int(h)} h"
    return f"hace {int(h / 24)} d"


# ====================== UI ======================

st.markdown('<div class="country-eyebrow">Radar Legislativo</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="country-title"><span class="accent">Perú</span> · Congreso de la República <span class="period">(2021–2026)</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Plataforma para seguir, filtrar y analizar todos los '
    'proyectos de ley presentados ante el Congreso de la República del Perú durante el '
    'período parlamentario 2021–2026. Pensada para equipos de asuntos públicos, '
    'consultoras de policy y áreas regulatorias que necesitan identificar iniciativas '
    'legislativas relevantes por tema, comisión, partido o autor — y mantener el '
    'seguimiento de su estado.</p>',
    unsafe_allow_html=True,
)

# ---------- KPIs ----------
totals = kpi_totals()
cols = st.columns(len(totals))
for col, (label, val) in zip(cols, totals.items()):
    col.metric(label, f"{val:,}")

st.markdown("")

cats = load_catalogs()

# ---------- Sidebar: rango de fechas + sync ----------
with st.sidebar:
    st.markdown("### Rango de fechas")
    fec_min_iso = cats["fec_min"] or "2021-07-28"
    fec_max_iso = cats["fec_max"] or dt.date.today().isoformat()
    fec_min = dt.date.fromisoformat(fec_min_iso)
    fec_max = dt.date.fromisoformat(fec_max_iso)
    rango = st.date_input(
        "Presentación",
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
    # Auto-sync silencioso al cargar la página: si el último terminó hace
    # > SYNC_MIN_MINUTES y no hay otro corriendo, dispara `scraper update` en
    # segundo plano. No bloquea — la página renderiza con los datos actuales.
    sync_state = maybe_fire_background_sync()
    status_info = _sync_status()
    if sync_state == "started" or status_info["running"]:
        st.markdown(
            '<div class="sync-card"><div class="label">Estado</div>'
            '<div class="value">🔄 Buscando nuevos proyectos…</div>'
            '<div style="font-size:11px;color:#9CA3AF;margin-top:4px">'
            'Recarga la página en 1–2 min para ver los cambios</div></div>',
            unsafe_allow_html=True,
        )
    else:
        last = status_info["last"]
        mins = status_info["mins_ago"]
        if last:
            ago = _fmt_ago(mins)
            st.markdown(
                f"""<div class="sync-card">
                <div class="label">Actualizado</div>
                <div class="value">{ago}</div>
                <div class="label" style="margin-top:10px">Último run</div>
                <div>Nuevos: <span class="value">{last['proyectos_nuevos']}</span> · Actualizados: <span class="value">{last['proyectos_actualizados']}</span> · Errores: <span class="value">{last['errores']}</span></div>
                </div>""",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="sync-card"><div class="label">Estado</div>'
                '<div class="value">Sin syncs previos</div></div>',
                unsafe_allow_html=True,
            )

# ---------- Tabla con barra de filtros ----------
df_full = load_proyectos(f_ini, f_fin)

TODOS = "Todos"
TODAS = "Todas"


def _opciones(col: str, label_todos: str = TODOS) -> list[str]:
    if col not in df_full.columns:
        return [label_todos]
    vals = sorted({str(v) for v in df_full[col].dropna().unique() if str(v).strip()})
    return [label_todos] + vals


def _opciones_comision() -> list[str]:
    if "_comisiones_all" not in df_full.columns:
        return [TODAS]
    todos: set[str] = set()
    for lst in df_full["_comisiones_all"]:
        if isinstance(lst, list):
            todos.update(x for x in lst if isinstance(x, str) and x.strip())
    return [TODAS] + sorted(todos)


def _opciones_autor() -> list[str]:
    """Lista de autores únicos extraídos del campo `autores_raw` (separados por '; ')."""
    if "Autor(es)" not in df_full.columns:
        return [TODOS]
    todos: set[str] = set()
    for s in df_full["Autor(es)"].dropna():
        for nombre in str(s).split(";"):
            n = nombre.strip()
            if n:
                todos.add(n)
    return [TODOS] + sorted(todos)


# Fila de filtros: PL + 6 dropdowns (Tema, Estado, Comisión, Partido, Proponente, Autor)
fc = st.columns([0.9, 1, 1, 1.2, 1.1, 1, 1.1])
pl_input = fc[0].text_input("PL", placeholder="ej. 14515")
sel_tema = fc[1].selectbox("Tema", _opciones("Tema"))
sel_estado = fc[2].selectbox("Estado", _opciones("Estado"))
sel_comision = fc[3].selectbox("Comisión", _opciones_comision())
sel_partido = fc[4].selectbox("Bancada", _opciones("Partido"))
sel_proponente = fc[5].selectbox("Proponente", _opciones("Proponente"))
sel_autor = fc[6].selectbox("Autor", _opciones_autor())

busqueda = st.text_input(
    "Buscar libre en título",
    placeholder="🔍  buscar texto en el título — ej. biometría, ciberseguridad, vacuna",
    label_visibility="collapsed",
)

# Aplicar filtros
df = df_full
if pl_input.strip():
    df = df[df["PL"].astype(str).str.contains(pl_input.strip(), case=False, na=False)]
if sel_tema != TODOS:
    df = df[df["Tema"] == sel_tema]
if sel_estado != TODOS:
    df = df[df["Estado"] == sel_estado]
if sel_comision != TODAS:
    df = df[df["_comisiones_all"].apply(lambda lst: isinstance(lst, list) and sel_comision in lst)]
if sel_partido != TODOS:
    df = df[df["Partido"] == sel_partido]
if sel_proponente != TODOS:
    df = df[df["Proponente"] == sel_proponente]
if sel_autor != TODOS:
    df = df[df["Autor(es)"].astype(str).str.contains(sel_autor, case=False, na=False, regex=False)]
if busqueda.strip():
    q = busqueda.strip().lower()
    df = df[df["Título"].astype(str).str.lower().str.contains(q, na=False)]

st.markdown(f"##### {len(df):,} proyecto(s) de {len(df_full):,} en el rango")

# Construcción del df de la tabla:
# - La columna "PL" pasa a ser la URL del portal (LinkColumn) — el regex
#   `display_text` extrae el pleyNum como label clickeable.
# - "Partido" se renombra a "Bancada" para coincidir con la terminología pedida.
# - Orden: PL · Título · Presentado · Estado · Autor · Bancada · Comisión · Tema.
df_view = df.copy()
df_view["PL"] = df_view["Portal"]  # ahora "PL" contiene la URL para LinkColumn
# Mostramos solo el autor principal en la columna (primer nombre antes del ";").
# El filtro de Autor sigue buscando en todos los firmantes (full string).
df_view["Autor(es)"] = (
    df_view["Autor(es)"].astype(str).str.split(";").str[0].str.strip().replace("nan", "")
)
df_view = df_view.rename(columns={"Partido": "Bancada", "Autor(es)": "Autor"})
COLS_VISIBLES = ["PL", "Título", "Presentado", "Estado", "Autor", "Bancada", "Comisión", "Tema"]
df_view = df_view[[c for c in COLS_VISIBLES if c in df_view.columns]]

# CSS para que el título envuelva (multi-línea) en lugar de truncar con "..."
st.markdown(
    """<style>
    div[data-testid="stDataFrame"] [role="gridcell"] {
        white-space: pre-wrap !important;
        overflow-wrap: break-word !important;
        line-height: 1.45 !important;
        padding-top: 10px !important;
        padding-bottom: 10px !important;
    }
    div[data-testid="stDataFrame"] [role="gridcell"] > div {
        white-space: pre-wrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
    }
    </style>""",
    unsafe_allow_html=True,
)

st.dataframe(
    df_view,
    hide_index=True,
    use_container_width=True,
    height=720,
    row_height=170,  # más espacio vertical para que el título envuelva sin cortarse
    column_config={
        "PL":           st.column_config.LinkColumn(
            "PL",
            display_text=r"expediente/\d+/(\d+)",
            width="small",
            pinned=True,
            help="Click para abrir el expediente en el portal del Congreso.",
        ),
        # Título: medium en vez de large → la tabla entera entra sin scroll
        # horizontal. El texto largo envuelve verticalmente (row_height=140).
        "Título":       st.column_config.TextColumn("Título", width="medium"),
        "Presentado":   st.column_config.TextColumn("Presentado", width="small"),
        "Estado":       st.column_config.TextColumn("Estado", width="small"),
        "Autor":        st.column_config.TextColumn("Autor", width="small"),
        "Bancada":      st.column_config.TextColumn("Bancada", width="small"),
        "Comisión":     st.column_config.TextColumn(
            "Comisión",
            width="medium",
            help="Comisión principal. El filtro busca en TODAS las comisiones del PL.",
        ),
        "Tema":         st.column_config.TextColumn("Tema", width="small"),
    },
)

# ---------- Footer ----------
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Fuente · api.congreso.gob.pe/spley-portal-service · '
    'Radar Legislativo</div>',
    unsafe_allow_html=True,
)
