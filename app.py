"""Radar Legislativo — Punto de entrada (router de navegación).

Define las páginas vía `st.navigation` para que el sidebar muestre los
nombres correctos ("Radar Legislativo" y "Perú") en lugar de los nombres
de archivo (`app`, `1_Peru`).

Corre con:
    python -m streamlit run app.py
"""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st


# ─── Tab title + favicon ────────────────────────────────────────────────────
st.set_page_config(
    page_title="Radar Legislativo · Vali",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─── Logo: leer del disco y embedar como data URI en CSS ────────────────────
# Acepta vali_logo.png, .jpg, .jpeg, .webp o .svg en assets/, en ese orden
# de prioridad. Así podés dropear el logo oficial sin tocar código.
_ASSETS = Path(__file__).resolve().parent / "assets"
_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
_logo_data_uri = ""
for _ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
    _candidate = _ASSETS / f"vali_logo{_ext}"
    if _candidate.exists():
        try:
            _b64 = base64.b64encode(_candidate.read_bytes()).decode()
            _mime = _MIME[_ext]
            _logo_data_uri = f"data:{_mime};base64,{_b64}"
        except Exception:
            pass
        break


# ─── CSS mínimo: logo como background del sidebar header ────────────────────
# (Sin @import, sin :has(), sin selectores experimentales. Solo lo necesario.)
_bg = f'background-image: url("{_logo_data_uri}") !important;' if _logo_data_uri else ""
st.markdown(
    f"""<style>
[data-testid="stSidebarHeader"] {{
  {_bg}
  background-size: contain !important;
  background-repeat: no-repeat !important;
  background-position: center center !important;
  background-color: #0A294D !important;
  height: 220px !important;
  min-height: 220px !important;
  padding: 20px !important;
  box-sizing: border-box !important;
}}
[data-testid="stSidebarHeader"] img,
[data-testid="stLogo"] {{
  display: none !important;
}}
section[data-testid="stSidebar"] {{
  background-color: #0A294D !important;
}}
section[data-testid="stSidebar"] * {{
  color: #FFFFFF !important;
}}
</style>""",
    unsafe_allow_html=True,
)


# ─── Definición de páginas ──────────────────────────────────────────────────
home = st.Page(
    "home.py",
    title="Radar Legislativo",
    icon="🛰️",
    default=True,
    url_path="",
)
peru = st.Page(
    "pages/1_Peru.py",
    title="Perú",
    icon="🇵🇪",
    url_path="peru",
)

nav = st.navigation(
    {
        "Portafolio de herramientas": [home],
        "Países": [peru],
    },
    position="sidebar",
)
nav.run()
