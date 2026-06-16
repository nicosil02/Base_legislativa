"""Radar Legislativo - Peru - Noticias y temas de interes.

Agregador de noticias de medios, instituciones y gremios peruanos
organizadas por categoria (Coyuntura Politica, Institucion, Temas
Agrarios, Temas Salud, Temas Tech, KYC/AML).

Fuente: tablas noticias + noticias_fuentes en proyectos.db, alimentadas
por el modulo noticias/ y el workflow refrescar-pe.yml.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


PAIS = "PE"
PAIS_LABEL = "Perú"


def _s(v) -> str:
    """str() seguro: convierte NaN/None a string vacio."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)


def _find_db_path() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [here.parent / "proyectos.db", Path.cwd() / "proyectos.db"]
    cur = here
    for _ in range(5):
        candidates.append(cur / "proyectos.db")
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None


# ====================== CSS (estetica Vali) ======================
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
:root {
  --ink:#0A294D; --ink-soft:#435D74; --ink-mute:#869FB2;
  --line:#CFD9E0; --line-soft:#E3E9ED;
  --accent:#0A294D; --accent-red:#BF1A1A;
  --bg:#FFFFFF; --bg-soft:#F4F6F8;
}
html, body, [class*="css"], .stApp {
  font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif !important;
  color:var(--ink); background-color:var(--bg);
}
section[data-testid="stSidebar"] { background-color:var(--ink) !important; }
section[data-testid="stSidebar"] *, section[data-testid="stSidebar"] a {
  color:#FFFFFF !important; font-family:'Inter',sans-serif !important;
}
.block-container { padding-top:2rem; padding-bottom:4rem; max-width:1400px; }

.country-eyebrow {
  font-size:11px; font-weight:800; letter-spacing:0.25em;
  text-transform:uppercase; color:var(--accent); margin-bottom:12px;
}
.country-title {
  font-size:clamp(2.5rem,5vw,3.75rem); font-weight:900;
  letter-spacing:-0.03em; line-height:0.95; color:var(--ink); margin:0 0 10px 0;
}
.country-title .accent { color:var(--accent); }
.country-subtitle {
  font-size:1.15rem; color:var(--ink-soft); line-height:1.6; margin-bottom:36px;
}
div[data-testid="stMetric"] {
  background-color:var(--bg); border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; box-shadow:none;
}
div[data-testid="stMetricLabel"] {
  color:var(--ink-soft) !important; font-size:10px !important;
  text-transform:uppercase; letter-spacing:0.18em; font-weight:700 !important;
}
div[data-testid="stMetricValue"] {
  color:var(--ink) !important; font-weight:900 !important;
  font-size:1.6rem !important; letter-spacing:-0.02em;
}
h2,h3 { font-weight:800; color:var(--ink); letter-spacing:-0.01em; }
.categoria-eyebrow {
  font-size:11px; font-weight:800; letter-spacing:0.18em;
  text-transform:uppercase; color:var(--accent); margin: 30px 0 6px 0;
}
.noticia-card {
  border: 1px solid var(--line-soft); border-radius: 10px;
  padding: 14px 16px; margin: 8px 0;
  transition: border-color .15s, box-shadow .15s;
}
.noticia-card:hover { border-color: var(--accent); box-shadow: 0 2px 8px rgba(10,41,77,0.08); }
.noticia-fuente {
  font-size:11px; font-weight:700; color:var(--ink-mute);
  text-transform:uppercase; letter-spacing:0.06em;
}
.noticia-titulo {
  font-size:15px; font-weight:700; color:var(--ink); line-height:1.35;
  margin: 4px 0; text-decoration: none;
}
.noticia-titulo a { color:var(--ink); text-decoration: none; }
.noticia-titulo a:hover { color: var(--accent-red); text-decoration: underline; }
.noticia-meta {
  font-size:11px; color:var(--ink-mute);
}
.noticia-resumen {
  font-size:13px; color:var(--ink-soft); line-height:1.45; margin-top:4px;
}
.footer-rule { width:32px; height:2px; background:var(--ink); margin:60px 0 14px 0; }
.footer-text {
  font-size:11px; font-weight:700; letter-spacing:0.18em;
  text-transform:uppercase; color:var(--ink-soft);
}
footer { visibility:hidden; }
</style>""",
    unsafe_allow_html=True,
)


def get_conn() -> sqlite3.Connection:
    db = _find_db_path()
    if db is None:
        st.error("No encuentro `proyectos.db`. Inicializa con: "
                 "`python -m noticias.cli init && python -m noticias.cli seed && "
                 "python -m noticias.cli sync`")
        st.stop()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=60)
def has_tables() -> bool:
    conn = get_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM noticias_fuentes WHERE pais=?", (PAIS,)
        ).fetchone()[0]
        return n > 0
    except sqlite3.OperationalError:
        return False


@st.cache_data(ttl=60)
def load_categorias() -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT categoria FROM noticias_fuentes WHERE pais=? "
        "ORDER BY categoria", (PAIS,),
    ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=60)
def load_fuentes() -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT nombre FROM noticias_fuentes WHERE pais=? AND activa=1 "
        "ORDER BY nombre", (PAIS,),
    ).fetchall()
    return [r[0] for r in rows]


@st.cache_data(ttl=60)
def load_kpis() -> dict:
    conn = get_conn()
    r = conn.execute(
        """SELECT
             COUNT(DISTINCT f.id) AS n_fuentes,
             SUM(CASE WHEN date(COALESCE(n.fecha_pub, n.first_seen_at)) = date('now')
                     THEN 1 ELSE 0 END) AS hoy,
             SUM(CASE WHEN date(COALESCE(n.fecha_pub, n.first_seen_at)) >= date('now', '-1 days')
                     THEN 1 ELSE 0 END) AS ultimas_24h,
             SUM(CASE WHEN date(COALESCE(n.fecha_pub, n.first_seen_at)) >= date('now', '-3 days')
                     THEN 1 ELSE 0 END) AS ultimos_3d
           FROM noticias_fuentes f
           LEFT JOIN noticias n ON n.fuente_id = f.id
           WHERE f.pais=? AND f.activa=1""", (PAIS,),
    ).fetchone()
    return {
        "Fuentes activas": r["n_fuentes"] or 0,
        "Hoy": r["hoy"] or 0,
        "Últimas 24h": r["ultimas_24h"] or 0,
        "Últimos 3 días": r["ultimos_3d"] or 0,
    }


VENTANAS = {
    "Hoy": "date('now')",
    "Últimas 24 horas": "date('now', '-1 days')",
    "Últimos 3 días": "date('now', '-3 days')",
    "Últimos 7 días": "date('now', '-7 days')",
}


@st.cache_data(ttl=60)
def load_noticias(ventana_sql: str,
                   categoria: str | None = None,
                   fuente: str | None = None,
                   busqueda: str | None = None,
                   limit: int = 300) -> pd.DataFrame:
    conn = get_conn()
    sql = f"""
      SELECT n.url AS "Enlace",
             n.titulo AS "Título",
             n.resumen AS "Resumen",
             COALESCE(n.fecha_pub, n.first_seen_at) AS "Fecha",
             f.nombre AS "Fuente",
             f.categoria AS "Categoría"
      FROM noticias n
      JOIN noticias_fuentes f ON f.id = n.fuente_id
      WHERE f.pais = ? AND f.activa = 1
        AND date(COALESCE(n.fecha_pub, n.first_seen_at)) >= {ventana_sql}
    """
    params: list = [PAIS]
    if categoria:
        sql += " AND f.categoria = ?"; params.append(categoria)
    if fuente:
        sql += " AND f.nombre = ?"; params.append(fuente)
    if busqueda:
        sql += " AND (LOWER(n.titulo) LIKE ? OR LOWER(COALESCE(n.resumen,'')) LIKE ?)"
        q = f"%{busqueda.lower()}%"
        params.extend([q, q])
    sql += " ORDER BY COALESCE(n.fecha_pub, n.first_seen_at) DESC LIMIT ?"
    params.append(limit)
    return pd.read_sql_query(sql, conn, params=params)


# ====================== UI ======================

st.markdown('<div class="country-eyebrow">Radar Legislativo · Noticias</div>',
            unsafe_allow_html=True)
st.markdown(
    f'<h1 class="country-title"><span class="accent">{PAIS_LABEL}</span> · Noticias y temas de interés</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Mapeo de medios, instituciones, ministerios, '
    'agencias regulatorias y gremios sectoriales del Perú. Cobertura de '
    'Coyuntura Política, Instituciones, Temas Agrarios, Salud, Tech y KYC/AML.</p>',
    unsafe_allow_html=True,
)

if not has_tables():
    st.warning(
        "Las tablas de noticias todavía no existen en la DB. "
        "Inicializá corriendo:\n\n"
        "```\npython -m noticias.cli init\n"
        "python -m noticias.cli seed\n"
        "python -m noticias.cli sync --pais PE\n```"
    )
    st.stop()

# KPIs
kpis = load_kpis()
cols = st.columns(len(kpis))
for col, (label, val) in zip(cols, kpis.items()):
    col.metric(label, f"{val:,}")

st.markdown("")

# Filtros
categorias = load_categorias()
fuentes = load_fuentes()

fc = st.columns([1.1, 1.4, 1.4, 1.5])
TODAS = "Todas"
TODOS = "Todos"
sel_ventana = fc[0].selectbox("Ventana", list(VENTANAS.keys()), index=0)
sel_cat = fc[1].selectbox("Categoría", [TODAS] + categorias)
sel_fuente = fc[2].selectbox("Fuente", [TODAS] + fuentes)
busqueda = fc[3].text_input("Buscar en título o resumen", placeholder="ej. AFP, IA, agricultura")

df = load_noticias(
    ventana_sql=VENTANAS[sel_ventana],
    categoria=sel_cat if sel_cat != TODAS else None,
    fuente=sel_fuente if sel_fuente != TODAS else None,
    busqueda=busqueda.strip() if busqueda.strip() else None,
    limit=300,
)

st.markdown(f"##### {len(df):,} noticia(s) · {sel_ventana.lower()}")

if df.empty:
    st.info("Sin noticias con esos filtros. Probá ajustar la búsqueda o "
            "ampliar la categoría.")
else:
    # Render como cards (no como dataframe — mejor UX para texto largo)
    # Agrupar por categoria para visualizacion
    if sel_cat == TODAS:
        for cat in df["Categoría"].unique():
            st.markdown(f'<div class="categoria-eyebrow">{cat}</div>',
                        unsafe_allow_html=True)
            sub = df[df["Categoría"] == cat].head(40)
            for _, n in sub.iterrows():
                fecha = _s(n["Fecha"])[:10]
                titulo = _s(n["Título"]).strip()
                resumen = _s(n["Resumen"]).strip()
                if len(resumen) > 220:
                    resumen = resumen[:220] + "…"
                st.markdown(
                    f'<div class="noticia-card">'
                    f'<div class="noticia-fuente">{n["Fuente"]} · {fecha}</div>'
                    f'<div class="noticia-titulo">'
                    f'<a href="{n["Enlace"]}" target="_blank" rel="noopener">{titulo}</a>'
                    f'</div>'
                    + (f'<div class="noticia-resumen">{resumen}</div>' if resumen else '')
                    + '</div>',
                    unsafe_allow_html=True,
                )
    else:
        # Filtro por categoría específica: mostrar sin agrupar
        for _, n in df.head(80).iterrows():
            fecha = _s(n["Fecha"])[:10]
            titulo = _s(n["Título"]).strip()
            resumen = _s(n["Resumen"]).strip()
            if len(resumen) > 240:
                resumen = resumen[:240] + "…"
            st.markdown(
                f'<div class="noticia-card">'
                f'<div class="noticia-fuente">{n["Fuente"]} · {fecha}</div>'
                f'<div class="noticia-titulo">'
                f'<a href="{n["Enlace"]}" target="_blank" rel="noopener">{titulo}</a>'
                f'</div>'
                + (f'<div class="noticia-resumen">{resumen}</div>' if resumen else '')
                + '</div>',
                unsafe_allow_html=True,
            )


# ---------- Footer ----------
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<p style="font-size:12px;color:var(--ink-soft);line-height:1.55;max-width:760px;">'
    'Sincronizado automáticamente cada hora desde RSS feeds y portales públicos. '
    'Las fuentes sin feed (HTML scraping) se actualizan con heurística genérica '
    'que puede tener cobertura menor.</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="footer-text">Radar Legislativo · Vali Consultores</div>',
    unsafe_allow_html=True,
)
