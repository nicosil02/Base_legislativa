"""Radar Legislativo — Home / landing.

Punto de entrada de la app multi-página. Cada país (por ahora solo Perú)
tiene su propia página bajo `pages/`. Streamlit auto-genera el sidebar
de navegación.

Corre con:
    python -m streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Radar Legislativo",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ====================== CSS (mismo estilo datadaf) ======================
st.markdown(
    """
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
    <style>
    :root {
      --ink:        #121212;
      --ink-soft:   #4B5563;
      --ink-mute:   #9CA3AF;
      --line:       #E5E7EB;
      --line-soft:  #F3F4F6;
      --accent:     #2563EB;
      --bg:         #FFFFFF;
      --bg-soft:    #F9FAFB;
    }
    html, body, [class*="css"], .stApp {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
      color: var(--ink);
      background-color: var(--bg);
    }
    .stApp { background-color: var(--bg); }
    section[data-testid="stSidebar"] {
      background-color: var(--bg-soft);
      border-right: 1px solid var(--line);
    }
    section[data-testid="stSidebar"] * { font-family: 'Inter', sans-serif !important; }

    .block-container { padding-top: 6vh; padding-bottom: 4rem; max-width: 1100px; }

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
      max-width: 680px; margin-bottom: 56px;
    }

    /* Country cards */
    .country-card {
      display: block;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 28px 32px;
      text-decoration: none;
      transition: border-color .2s, transform .2s;
      background: var(--bg);
    }
    .country-card:hover {
      border-color: var(--accent);
      transform: translateY(-2px);
    }
    .country-card .flag {
      font-size: 28px;
      margin-bottom: 14px;
    }
    .country-card .name {
      font-size: 1.5rem;
      font-weight: 800;
      letter-spacing: -0.015em;
      color: var(--ink);
      margin-bottom: 4px;
    }
    .country-card .institution {
      font-size: 13px;
      color: var(--ink-soft);
      font-weight: 500;
      margin-bottom: 16px;
    }
    .country-card .stats {
      display: flex;
      gap: 22px;
      margin-bottom: 16px;
    }
    .country-card .stat-num {
      font-size: 1.4rem;
      font-weight: 900;
      color: var(--ink);
      letter-spacing: -0.02em;
    }
    .country-card .stat-label {
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--ink-mute);
    }
    .country-card .cta {
      font-size: 11px; font-weight: 800; letter-spacing: 0.18em;
      text-transform: uppercase; color: var(--accent);
    }
    .country-card.soon {
      opacity: 0.55;
      pointer-events: none;
    }
    .country-card.soon .cta { color: var(--ink-mute); }

    .footer-rule {
      width: 32px; height: 2px; background: var(--ink);
      margin: 80px 0 14px 0;
    }
    .footer-text {
      font-size: 11px; font-weight: 700; letter-spacing: 0.18em;
      text-transform: uppercase; color: var(--ink-soft);
    }
    footer { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ====================== Helpers ======================
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "proyectos.db"


@st.cache_data(ttl=60)
def stats_peru() -> dict:
    if not DB_PATH.exists():
        return {"total": None, "leyes": None}
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        total = conn.execute("SELECT COUNT(*) FROM proyectos").fetchone()[0]
        leyes = conn.execute(
            "SELECT COUNT(*) FROM proyectos WHERE UPPER(estado) LIKE '%PUBLIC%PERUANO%' "
            "OR UPPER(estado) LIKE '%LEY PUBLICADA%'"
        ).fetchone()[0]
        return {"total": total, "leyes": leyes}
    except Exception:
        return {"total": None, "leyes": None}


# ====================== UI ======================

st.markdown('<div class="home-eyebrow">Monitoreo legislativo</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="home-title">Radar <span class="accent">Legislativo</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="home-sub">Base de datos viva de proyectos de ley con clasificación temática, '
    'seguimiento de cambios de estado y alertas. Diseñado para equipos de asuntos públicos '
    'y consultoras de policy.</p>',
    unsafe_allow_html=True,
)

# Country grid
s = stats_peru()
total_pe = f"{s['total']:,}" if s["total"] is not None else "—"
leyes_pe = f"{s['leyes']:,}" if s["leyes"] is not None else "—"

st.markdown("##### Países")
cols = st.columns(3)

# Perú — operativo
with cols[0]:
    if st.button("Abrir Perú →", key="btn_peru", use_container_width=True):
        st.switch_page("pages/1_Peru.py")
    st.markdown(
        f"""
        <div class="country-card">
            <div class="flag">🇵🇪</div>
            <div class="name">Perú</div>
            <div class="institution">Congreso de la República · Período 2021–2026</div>
            <div class="stats">
                <div><div class="stat-num">{total_pe}</div><div class="stat-label">Proyectos</div></div>
                <div><div class="stat-num">{leyes_pe}</div><div class="stat-label">Publicadas</div></div>
            </div>
            <div class="cta">Ver dashboard ↗</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Colombia — placeholder
with cols[1]:
    st.markdown(
        """
        <div class="country-card soon">
            <div class="flag">🇨🇴</div>
            <div class="name">Colombia</div>
            <div class="institution">Congreso de la República</div>
            <div class="stats">
                <div><div class="stat-num">—</div><div class="stat-label">Próximamente</div></div>
            </div>
            <div class="cta">Disponible pronto</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Ecuador — placeholder
with cols[2]:
    st.markdown(
        """
        <div class="country-card soon">
            <div class="flag">🇪🇨</div>
            <div class="name">Ecuador</div>
            <div class="institution">Asamblea Nacional</div>
            <div class="stats">
                <div><div class="stat-num">—</div><div class="stat-label">Próximamente</div></div>
            </div>
            <div class="cta">Disponible pronto</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Footer
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Radar Legislativo · datos abiertos del Estado · '
    'github.com/nicosil02/Base_legislativa</div>',
    unsafe_allow_html=True,
)
