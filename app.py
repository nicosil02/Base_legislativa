"""Radar Legislativo — Punto de entrada (router de navegación).

Define las páginas vía `st.navigation` para que el sidebar muestre los
nombres correctos ("Radar Legislativo" y "Perú") en lugar de los nombres
de archivo (`app`, `1_Peru`).

Corre con:
    python -m streamlit run app.py
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st


# Logo Vali grande en el tope del sidebar.
# (se hace ANTES de la nav para que aparezca arriba de los links.)
# Busca vali_logo.png > .jpg > .jpeg > .webp > .svg en assets/ (primero que
# encuentre, ese usa). Permite dropear el logo oficial en cualquier formato.
_assets_dir = Path(__file__).resolve().parent / "assets"
_logo_path = None
for _ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
    _candidate = _assets_dir / f"vali_logo{_ext}"
    if _candidate.exists():
        _logo_path = _candidate
        break
if _logo_path is not None:
    try:
        st.logo(str(_logo_path), size="large", link=None)
    except Exception:
        # Fallback en versiones viejas de Streamlit
        pass


# ─── CSS adicional: logo más grande + ocultar texto de íconos Material ─────
# Aplica en todas las páginas (app.py se ejecuta antes de cada st.Page).
# Mínimo, defensivo, sin @import ni :has() ni JS — para no romper nada.
st.markdown(
    """<style>
/* Logo grande: forzar el <img> generado por st.logo() a ~140px de alto.
   Streamlit le aplica un max-height chico por default; lo sobreescribimos. */
[data-testid="stSidebarHeader"] {
    min-height: 180px !important;
    padding: 20px 16px !important;
    background-color: #0A294D !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
[data-testid="stSidebarHeader"] [data-testid="stLogo"],
[data-testid="stSidebarHeader"] a[data-testid="stLogo"] {
    margin: 0 auto !important;
    display: block !important;
    max-width: 100% !important;
}
[data-testid="stSidebarHeader"] [data-testid="stLogo"] img,
[data-testid="stSidebarHeader"] img {
    max-height: 140px !important;
    height: 140px !important;
    width: auto !important;
    max-width: 100% !important;
    object-fit: contain !important;
}

/* Ocultar el texto crudo "expand_more" / "keyboard_double_arrow_left" / etc.
   que aparece cuando la fuente Material Symbols Rounded de Streamlit no
   carga. Selectores múltiples para cubrir todas las versiones de DOM. */
[data-testid="stSidebar"] [class*="material-symbols"],
[data-testid="stSidebar"] [class*="material-icons"],
[data-testid="stSidebar"] [class*="MaterialSymbols"],
[data-testid="stSidebar"] [class*="MaterialIcons"],
[data-testid="stSidebar"] span.material-symbols-rounded,
[data-testid="stSidebar"] span.material-symbols-outlined,
[data-testid="stSidebar"] span.material-icons-round,
[data-testid="stSidebar"] [aria-hidden="true"]:not([class*="emoji"]):not([class*="flag"]),
/* Por inline style: a veces Streamlit setea font-family directamente */
[data-testid="stSidebar"] [style*="Material Symbols"],
[data-testid="stSidebar"] [style*="material-symbols"],
[data-testid="stSidebar"] [style*="Material Icons"],
/* Por posición DOM: el ícono toggle suele ser el último hijo de un expander */
[data-testid="stSidebarNav"] [aria-expanded] > span:last-child,
[data-testid="stSidebarNav"] [aria-expanded] > div:last-child,
[data-testid="stSidebarNav"] button[aria-expanded] > span:last-child,
[data-testid="stSidebarNav"] [role="button"] > span:last-child,
/* Específicamente nav section headers (Streamlit moderno) */
[data-testid="stSidebarNav"] li > div > span:last-child,
[data-testid="stSidebarNav"] [data-testid*="stSidebarNavSection"] span:last-child {
    font-size: 0 !important;
    line-height: 0 !important;
    color: transparent !important;
    visibility: hidden !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    opacity: 0 !important;
}

/* ─── Transición suave entre páginas ─────────────────────────────────────
   Fade-in del contenedor principal cuando se navega entre páginas.
   Streamlit re-renderiza todo el main al cambiar de página, así que
   esta animación dispara en cada navegación. Sutil, 220ms, sin distraer. */
[data-testid="stMain"] .block-container,
section[data-testid="stMain"] > div {
    animation: pageFadeIn 220ms ease-out;
}
@keyframes pageFadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* Hover sutil sobre los links del sidebar nav (feedback antes del click) */
[data-testid="stSidebarNav"] a {
    transition: background-color 150ms ease-out, padding-left 150ms ease-out !important;
}
[data-testid="stSidebarNav"] a:hover {
    padding-left: 18px !important;
}
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

# Navegación con secciones colapsables (Portafolio de herramientas / Países).
# Los chevrons "expand_more" se rendean como texto porque la fuente Material
# Symbols Rounded de Streamlit no carga. Truco: en el CSS de abajo escondemos
# el texto crudo (font-size: 0) y le inyectamos "▼" en un ::before. La
# rotación que Streamlit aplica al toggle al expandir/colapsar se hereda al
# pseudo-elemento → la flecha apunta abajo cuando está abierto y a un lado
# cuando está cerrado, naturalmente.
nav = st.navigation(
    {
        "Portafolio de herramientas": [home],
        "Países": [peru],
    },
    position="sidebar",
)
nav.run()

# Reemplazo del chevron Material Symbols por una flecha unicode "▼".
#
# Estructura DOM real en Streamlit 1.57 (encontrada inspeccionando el código
# fuente del frontend):
#
#   <button aria-expanded="true|false">                       ← StyledSidebarNavSectionHeader
#       <div class="css-XYZ-StyledChevronContainer">          ← chevron container (1er hijo!)
#           <DynamicIcon iconValue=":material/expand_more:"/> ← acá vive el texto roto
#       </div>
#       <span>Portafolio de herramientas</span>               ← título
#   </button>
#
# El chevron es el PRIMER hijo (no último). Streamlit aplica
# transform: rotate(0deg) cuando expandido y rotate(-90deg) cuando colapsado
# sobre el StyledChevronContainer. Si escondemos el contenido interno y
# le ponemos un ::before, la rotación se hereda al pseudo-elemento.
st.markdown(
    """<style>
/* 1. El contenedor del chevron es el primer div hijo de [aria-expanded].
      Hacemos que NO muestre el contenido roto, pero conservamos su rotación. */
[data-testid="stSidebar"] [aria-expanded] > div:first-child,
[data-testid="stSidebarNav"] [aria-expanded] > div:first-child {
    font-size: 0 !important;
    line-height: 0 !important;
    position: relative !important;
    width: 18px !important;
    height: 18px !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    visibility: visible !important;
    opacity: 1 !important;
}

/* 2. Ocultar el DynamicIcon (o lo que sea) que vive adentro y renderea
      ":material/expand_more:" como texto crudo. */
[data-testid="stSidebar"] [aria-expanded] > div:first-child > *,
[data-testid="stSidebarNav"] [aria-expanded] > div:first-child > * {
    display: none !important;
    visibility: hidden !important;
}

/* 3. Inyectar la flecha unicode en el ::before del contenedor. La
      rotación del padre se aplica naturalmente al pseudo-elemento. */
[data-testid="stSidebar"] [aria-expanded] > div:first-child::before,
[data-testid="stSidebarNav"] [aria-expanded] > div:first-child::before {
    content: "▼" !important;
    font-size: 11px !important;
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif !important;
    color: rgba(255,255,255,0.7) !important;
    line-height: 1 !important;
    display: inline-block !important;
    visibility: visible !important;
    opacity: 1 !important;
}

/* 4. Como fallback defensivo, también ocultamos cualquier span con clases
      tipo material-symbols por las dudas que en otras versiones el icono
      esté en otro lugar del DOM. */
[data-testid="stSidebar"] .material-symbols-rounded,
[data-testid="stSidebar"] [class*="material-symbols"] {
    font-size: 0 !important;
    line-height: 0 !important;
    width: 0 !important;
    overflow: hidden !important;
    visibility: hidden !important;
}
</style>""",
    unsafe_allow_html=True,
)
