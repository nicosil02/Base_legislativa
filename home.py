"""Radar Legislativo — Home / landing.

Esta página se carga como `home.py` desde app.py vía st.navigation.
Muestra el grid de países disponibles. Cada card es un <a> clickeable
que navega a la página del país.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st


# ====================== CSS (estilo Vali) ======================
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
:root {
  --ink:        #0A294D;
  --ink-soft:   #435D74;
  --ink-mute:   #869FB2;
  --line:       #CFD9E0;
  --line-soft:  #E3E9ED;
  --accent:     #0A294D;
  --accent-red: #BF1A1A;
  --bg:         #FFFFFF;
  --bg-soft:    #F4F6F8;
}
html, body, [class*="css"], .stApp {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
  color: var(--ink);
  background-color: var(--bg);
}
/* === Sidebar navy + texto blanco === */
section[data-testid="stSidebar"] {
  background-color: var(--ink) !important;
  border-right: 0 !important;
}
section[data-testid="stSidebar"] *,
section[data-testid="stSidebar"] a,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3, section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] span {
  color: #FFFFFF !important;
  font-family: 'Inter', sans-serif !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
  background-color: rgba(255,255,255,0.06) !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] [aria-current="page"] {
  background-color: rgba(255,255,255,0.10) !important;
}

/* Ocultar TODO texto crudo de Material Symbols/Icons en sidebar */
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

/* === Logo Vali: 200px centrado === */
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

.block-container { padding-top: 5vh; padding-bottom: 4rem; max-width: 1100px; }

.home-eyebrow {
  font-size: 12px; font-weight: 800; letter-spacing: 0.28em;
  text-transform: uppercase; color: var(--accent); margin-bottom: 14px;
}
.home-title {
  font-size: clamp(3rem, 8vw, 5.5rem);
  font-weight: 900; letter-spacing: -0.035em; line-height: 0.95;
  color: var(--ink); margin: 0 0 24px 0;
}
.home-title .accent { color: var(--accent); }
.home-sub {
  font-size: 1.15rem; line-height: 1.6; color: var(--ink-soft);
  max-width: 720px; margin-bottom: 48px;
}

.section-label {
  font-size: 11px; font-weight: 800; letter-spacing: 0.22em;
  text-transform: uppercase; color: var(--ink-mute); margin-bottom: 14px;
}

/* Country card — single clickable element */
a.country-card, div.country-card {
  display: block;
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 28px 32px;
  text-decoration: none !important;
  color: var(--ink) !important;
  transition: border-color .2s, transform .2s, box-shadow .2s;
  background: var(--bg);
}
a.country-card:hover {
  border-color: var(--accent);
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(10,41,77,0.08);
}
.country-card .country-header {
  display: flex; align-items: center; gap: 14px; margin-bottom: 8px;
}
.country-card .flag {
  font-size: 36px; line-height: 1;
}
.country-card .name {
  font-size: 1.75rem; font-weight: 800;
  letter-spacing: -0.02em; color: var(--ink); line-height: 1;
}
.country-card .institution {
  font-size: 14px;
  color: var(--ink-soft);
  font-weight: 500;
  margin-bottom: 22px;
}
.country-card .stats {
  display: flex; gap: 36px; margin-bottom: 18px;
}
.country-card .stat-num {
  font-size: 1.6rem; font-weight: 900; color: var(--ink);
  letter-spacing: -0.02em; line-height: 1;
}
.country-card .stat-label {
  font-size: 10px; font-weight: 700; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--ink-mute); margin-top: 4px;
}
.country-card .cta {
  font-size: 11px; font-weight: 800; letter-spacing: 0.2em;
  text-transform: uppercase; color: var(--accent);
}
.country-card.soon {
  opacity: 0.6;
}
.country-card.soon .cta { color: var(--ink-mute); }
.country-card.soon .stat-num { color: var(--ink-mute); }

.footer-rule {
  width: 32px; height: 2px; background: var(--ink);
  margin: 80px 0 14px 0;
}
.footer-text {
  font-size: 11px; font-weight: 700; letter-spacing: 0.18em;
  text-transform: uppercase; color: var(--ink-soft);
}
footer { visibility: hidden; }
</style>""",
    unsafe_allow_html=True,
)


# ====================== Helpers ======================
def _find_db_file(filename: str) -> Path | None:
    """Busca un archivo SQLite en varias ubicaciones razonables (repo root,
    CWD, ancestros). Funciona para `proyectos.db` y `proyectos_ec.db`."""
    here = Path(__file__).resolve().parent
    candidates = [here / filename, Path.cwd() / filename]
    cur = here
    for _ in range(5):
        candidates.append(cur / filename)
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None


def _find_db_path() -> Path | None:
    return _find_db_file("proyectos.db")


@st.cache_data(ttl=60)
def stats_peru() -> dict:
    db = _find_db_path()
    if db is None:
        return {"total": None, "leyes": None}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM proyectos").fetchone()[0]
            leyes = conn.execute(
                "SELECT COUNT(*) FROM proyectos WHERE UPPER(estado) LIKE '%PUBLIC%PERUANO%' "
                "OR UPPER(estado) LIKE '%LEY PUBLICADA%'"
            ).fetchone()[0]
            return {"total": total, "leyes": leyes}
        finally:
            conn.close()
    except Exception:
        return {"total": None, "leyes": None}


@st.cache_data(ttl=60)
def stats_ecuador() -> dict:
    db = _find_db_file("proyectos_ec.db")
    if db is None:
        return {"total": None, "publicados": None}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            total = conn.execute("SELECT COUNT(*) FROM proyectos").fetchone()[0]
            publicados = conn.execute(
                "SELECT COUNT(*) FROM proyectos WHERE UPPER(estado) = 'REGISTRO OFICIAL'"
            ).fetchone()[0]
            return {"total": total, "publicados": publicados}
        finally:
            conn.close()
    except Exception:
        return {"total": None, "publicados": None}


# ====================== UI ======================

st.markdown('<div class="home-eyebrow">Asuntos Públicos · Vali Consultores</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="home-title">Vali <span class="accent">Intelligence</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="home-sub">Suite de herramientas de inteligencia regulatoria para el equipo de '
    'Asuntos Públicos y de Gobierno. Monitoreo legislativo, clasificación temática, '
    'seguimiento de cambios de estado y alertas diarias automáticas.</p>',
    unsafe_allow_html=True,
)

# Section: herramientas activas
st.markdown('<div class="section-label">Herramientas</div>', unsafe_allow_html=True)
st.markdown(
    '<p style="font-size:13px;color:#869FB2;margin-bottom:18px;">Radar Legislativo · '
    'Monitoreo de proyectos de ley</p>',
    unsafe_allow_html=True,
)

# Country grid
s = stats_peru()
total_pe = f"{s['total']:,}" if s["total"] is not None else "—"
leyes_pe = f"{s['leyes']:,}" if s["leyes"] is not None else "—"

s_ec = stats_ecuador()
total_ec = f"{s_ec['total']:,}" if s_ec["total"] is not None else "—"
publicados_ec = f"{s_ec['publicados']:,}" if s_ec["publicados"] is not None else "—"

st.markdown('<div class="section-label">Países</div>', unsafe_allow_html=True)
cols = st.columns([1, 1, 1])

# Perú — card visual (sin <a href> que hace HARD nav y rompe la sesion).
# La navegacion la hace el st.page_link de abajo que usa SOFT nav.
with cols[0]:
    st.markdown(
        f"""
        <div class="country-card">
            <div class="country-header">
                <div class="flag">🇵🇪</div>
                <div class="name">Perú</div>
            </div>
            <div class="institution">Congreso de la República · Período 2021–2026</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{total_pe}</div>
                    <div class="stat-label">Proyectos</div>
                </div>
                <div>
                    <div class="stat-num">{leyes_pe}</div>
                    <div class="stat-label">Publicadas</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/1_Peru.py", label="Abrir dashboard de Perú",
                 icon="🇵🇪", use_container_width=True)

# Ecuador — card visual + st.page_link (soft nav)
with cols[1]:
    st.markdown(
        f"""
        <div class="country-card">
            <div class="country-header">
                <div class="flag">🇪🇨</div>
                <div class="name">Ecuador</div>
            </div>
            <div class="institution">Asamblea Nacional · Período 2025–2029</div>
            <div class="stats">
                <div>
                    <div class="stat-num">{total_ec}</div>
                    <div class="stat-label">Proyectos</div>
                </div>
                <div>
                    <div class="stat-num">{publicados_ec}</div>
                    <div class="stat-label">Reg. Oficial</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.page_link("pages/2_Ecuador.py", label="Abrir dashboard de Ecuador",
                 icon="🇪🇨", use_container_width=True)

with cols[2]:
    st.markdown("&nbsp;", unsafe_allow_html=True)

# Footer
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Radar Legislativo · Vali Consultores · '
    'github.com/nicosil02/Base_legislativa</div>',
    unsafe_allow_html=True,
)
