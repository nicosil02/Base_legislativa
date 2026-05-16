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
# Estrategia: inyectar el SVG como background-image del header del sidebar.
# NO llamamos a st.logo() porque internamente genera un <img> de ~44 px que
# Streamlit no deja sobreescribir por CSS y se veía superpuesto al fondo
# (logo grande + "vali" chiquito encima). Con solo background-image tenemos
# control total del tamaño y no hay imagen duplicada.
_logo_path = Path(__file__).resolve().parent / "assets" / "vali_logo.svg"
_logo_css_extra = ""
if _logo_path.exists():
    try:
        _b64 = base64.b64encode(_logo_path.read_bytes()).decode()
        _logo_css_extra = (
            f'background-image: url("data:image/svg+xml;base64,{_b64}") !important;'
        )
    except Exception:
        pass

# CSS global: forzar carga de Material Symbols Rounded (para que los chevrons
# de st.navigation se rendericen como ícono y NO como texto "expand_more"),
# logo como background del sidebar header, y ocultar cualquier <img> residual.
# Se inyecta en app.py para que aplique en TODAS las páginas del sitio.
st.markdown(
    f"""<style>
/* ── Forzar carga de Material Symbols (resuelve "expand_more" text leak) ──
   Si Streamlit no logra cargar su propia copia de la fuente, el navegador
   muestra el nombre del ícono como texto crudo. Cargándola desde Google Fonts
   con display:block, garantizamos que el glifo se renderice. */
@import url("https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,300..700,0..1,-50..200&display=block");
@import url("https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,300..700,0..1,-50..200&display=block");

/* ── Logo: fondo SVG centrado en el header del sidebar ── */
[data-testid="stSidebarHeader"] {{
  {_logo_css_extra}
  background-size: 180px 180px !important;
  background-repeat: no-repeat !important;
  background-position: center center !important;
  height: 230px !important;
  min-height: 230px !important;
  max-height: 230px !important;
  background-color: #0A294D !important;
  padding: 0 !important;
  margin: 0 !important;
  display: block !important;
  overflow: hidden !important;
}}
/* Ocultar CUALQUIER <img> o <a> residual dentro del header del sidebar
   (st.logo() podría seguir generándolos en alguna versión). El background
   queda intacto porque vive en el div padre. */
[data-testid="stSidebarHeader"] img,
[data-testid="stSidebarHeader"] a,
[data-testid="stSidebarHeader"] [data-testid="stLogo"],
[data-testid="stLogo"],
[data-testid="stLogoSpacer"],
[data-testid="stSidebarLogo"] {{
  display: none !important;
  visibility: hidden !important;
  width: 0 !important;
  height: 0 !important;
  opacity: 0 !important;
}}

/* ── Material Symbols: por si el @import no carga a tiempo, ocultar texto ── */
[data-testid="stSidebar"] .material-symbols-rounded,
[data-testid="stSidebar"] .material-symbols-outlined,
[data-testid="stSidebar"] .material-symbols-sharp,
[data-testid="stSidebar"] .material-icons-round,
[data-testid="stSidebar"] .material-icons,
[data-testid="stSidebar"] [class*="material-symbols"],
[data-testid="stSidebar"] [class*="material-icons"],
[data-testid="stSidebar"] [class*="MaterialSymbols"],
[data-testid="stSidebar"] [class*="MaterialIcons"] {{
  /* Si la fuente carga via @import: los íconos se ven correctos.
     Si no: estos elementos quedan invisibles (sin "expand_more" text). */
  font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
  font-feature-settings: 'liga' !important;
  -webkit-font-feature-settings: 'liga' !important;
  color: rgba(255,255,255,0.7) !important;
}}
/* Si la fuente Material Symbols falla, asegurar que el TEXTO crudo no
   se vea (font-size 0 mata el fallback). Pero font-feature-settings: 'liga'
   con la fuente cargada sigue renderizando el ícono porque el ligature
   se aplica con cualquier font-size > 0. Combinamos: keep size > 0 cuando
   font carga, hide cuando no. Como no podemos detectar eso desde CSS,
   apelamos a font-display:block (arriba) que bloquea el render hasta
   3s y luego o muestra el ícono o nada. */

/* Botones del header (collapse/expand sidebar) */
[data-testid="stSidebarHeader"] button,
button[data-testid="stExpandSidebarButton"],
button[data-testid="stSidebarCollapsedControl"] {{
  position: absolute !important;
  top: 8px !important;
  right: 8px !important;
  z-index: 10 !important;
  background: transparent !important;
}}
[data-testid="stSidebarHeader"] button *,
button[data-testid="stExpandSidebarButton"] *,
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
