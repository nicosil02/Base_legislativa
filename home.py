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

/* Material Symbols: forzar carga */
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=block');
[class*="material-symbols"] {
  font-family: 'Material Symbols Rounded' !important;
  font-variation-settings: 'opsz' 24;
  font-weight: normal !important;
  font-style: normal !important;
  letter-spacing: normal !important;
  display: inline-block;
  white-space: nowrap;
  direction: ltr;
  -webkit-font-feature-settings: 'liga';
  -webkit-font-smoothing: antialiased;
}

/* === Logo Vali: GRANDE y centrado === */
[data-testid="stSidebarHeader"] {
  padding-top: 16px !important;
  padding-bottom: 12px !important;
  display: flex !important;
  justify-content: center !important;
}
[data-testid="stLogo"] {
  margin: 0 auto !important;
  display: block !important;
}
[data-testid="stLogo"] img {
  max-height: 120px !important;
  height: 120px !important;
  width: auto !important;
  max-width: 160px !important;
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
def _find_db_path() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [here / "proyectos.db", Path.cwd() / "proyectos.db"]
    cur = here
    for _ in range(5):
        candidates.append(cur / "proyectos.db")
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None


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


# ====================== UI ======================

st.markdown('<div class="home-eyebrow">Monitoreo legislativo</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="home-title">Radar <span class="accent">Legislativo</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="home-sub">Diseñado para el equipo de Asuntos Públicos y de Gobierno de '
    'Vali Consultores. Base de datos viva de proyectos de ley con clasificación temática, '
    'seguimiento de cambios de estado y alertas.</p>',
    unsafe_allow_html=True,
)

# Country grid
s = stats_peru()
total_pe = f"{s['total']:,}" if s["total"] is not None else "—"
leyes_pe = f"{s['leyes']:,}" if s["leyes"] is not None else "—"

st.markdown('<div class="section-label">Países</div>', unsafe_allow_html=True)
cols = st.columns([1, 1, 1])

# Perú — operativo, card es un link <a> clickeable
with cols[0]:
    st.markdown(
        f"""
        <a href="/peru" target="_self" class="country-card">
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
            <div class="cta">Ver dashboard ↗</div>
        </a>
        """,
        unsafe_allow_html=True,
    )

# Ecuador — placeholder (no clickeable)
with cols[1]:
    st.markdown(
        """
        <div class="country-card soon">
            <div class="country-header">
                <div class="flag">🇪🇨</div>
                <div class="name">Ecuador</div>
            </div>
            <div class="institution">Asamblea Nacional</div>
            <div class="stats">
                <div>
                    <div class="stat-num">—</div>
                    <div class="stat-label">Próximamente</div>
                </div>
            </div>
            <div class="cta">Disponible pronto</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with cols[2]:
    st.markdown("&nbsp;", unsafe_allow_html=True)

# Footer
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Radar Legislativo · Vali Consultores · '
    'github.com/nicosil02/Base_legislativa</div>',
    unsafe_allow_html=True,
)
