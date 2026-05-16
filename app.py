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


# ── Logo Vali ────────────────────────────────────────────────────────────────
# st.logo() internamente limita el alto de la imagen a ~44 px, por eso el logo
# salía diminuto y con la "v" cortada. Solución: injectamos el SVG como
# background-image del header del sidebar (tamaño controlado 100%) y ocultamos
# el <img> que genera st.logo() para que el hueco de cabecera siga existiendo.
_logo_path = Path(__file__).resolve().parent / "assets" / "vali_logo.svg"
_logo_css_extra = ""
if _logo_path.exists():
    try:
        _b64 = base64.b64encode(_logo_path.read_bytes()).decode()
        _logo_css_extra = (
            f'background-image: url("data:image/svg+xml;base64,{_b64}") !important;'
        )
        st.logo(str(_logo_path), size="large", link=None)
    except Exception:
        pass

# CSS global: logo como fondo del sidebar header + ocultar Material Symbols.
# Se inyecta en app.py para que aplique en TODAS las páginas del sitio.
st.markdown(
    f"""<style>
/* ── Logo: fondo SVG de 175 px centrado ── */
[data-testid="stSidebarHeader"] {{
  {_logo_css_extra}
  background-size: 175px 175px !important;
  background-repeat: no-repeat !important;
  background-position: center center !important;
  min-height: 215px !important;
  background-color: #0A294D !important;
  padding: 20px 16px !important;
}}
/* Ocultar la miniatura que genera st.logo() */
[data-testid="stLogo"] {{
  display: none !important;
  visibility: hidden !important;
  width: 0 !important;
  height: 0 !important;
}}

/* ── Material Symbols: ocultar texto cuando la fuente no carga ──
   El sidebar usa Material Symbols Rounded para los chevrons de las secciones
   de navegación (expand_more, keyboard_double_arrow_left, etc.).
   Cuando la fuente no se descarga a tiempo el texto crudo aparece.
   Solución: font-size 0 + opacity 0 + color transparent + overflow hidden
   para los elementos que podrían contenerlos. */
[data-testid="stSidebar"] .material-symbols-rounded,
[data-testid="stSidebar"] .material-symbols-outlined,
[data-testid="stSidebar"] .material-symbols-sharp,
[data-testid="stSidebar"] .material-icons-round,
[data-testid="stSidebar"] .material-icons,
[data-testid="stSidebar"] [class*="material-symbols"],
[data-testid="stSidebar"] [class*="material-icons"],
[data-testid="stSidebar"] [class*="MaterialSymbols"],
[data-testid="stSidebar"] [class*="MaterialIcons"],
[data-testid="stSidebar"] span[aria-hidden="true"],
[data-testid="stSidebar"] i[aria-hidden="true"] {{
  font-size: 0 !important;
  line-height: 0 !important;
  color: transparent !important;
  opacity: 0 !important;
  overflow: hidden !important;
  width: 0 !important;
  display: inline-block !important;
  pointer-events: none !important;
}}
/* Botones del header (collapse/expand sidebar) */
[data-testid="stSidebarHeader"] button,
[data-testid="stSidebarHeader"] button *,
button[data-testid="stExpandSidebarButton"],
button[data-testid="stExpandSidebarButton"] *,
button[data-testid="stSidebarCollapsedControl"],
button[data-testid="stSidebarCollapsedControl"] * {{
  font-size: 0 !important;
  color: transparent !important;
  line-height: 0 !important;
}}
[data-testid="stSidebarHeader"] button::before,
button[data-testid="stExpandSidebarButton"]::before {{
  content: "‹" !important;
  font-size: 18px !important;
  color: #FFFFFF !important;
  visibility: visible !important;
  display: inline-block !important;
  font-family: 'Inter', sans-serif !important;
}}
</style>""",
    unsafe_allow_html=True,
)


# Definir páginas explícitamente. Esto deshabilita la auto-detección de
# `pages/` y nos da control total sobre los nombres en el sidebar.
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
