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
import streamlit.components.v1 as _components


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

nav = st.navigation(
    {
        "Portafolio de herramientas": [home],
        "Países": [peru],
    },
    position="sidebar",
)
nav.run()


# ─── JS para ocultar texto crudo de íconos Material Symbols ──────────────────
# Cuando la fuente Material Symbols Rounded no carga, los nombres de los íconos
# (expand_more, keyboard_double_arrow_left, etc.) aparecen como texto crudo
# al lado de "Portafolio de herramientas" y "Países".
#
# CSS solo no es suficiente porque no podemos targetear elementos por su
# textContent. Necesitamos JavaScript. Lo inyectamos via components.html
# (iframe de 1×1 px que pusheamos fuera de la pantalla con CSS).
#
# El script accede a window.parent.document, busca leaf spans/i/div cuyo
# texto matchee patrón de nombre de Material Symbol y los oculta inline.
# Re-corre via MutationObserver cuando Streamlit re-renderiza.
try:
    _components.html(
        """
        <script>
        (function () {
          const ICON_RE = /^[a-z][a-z0-9_]{3,40}$/;
          const KNOWN = new Set([
            "expand_more","expand_less","chevron_right","chevron_left",
            "keyboard_arrow_down","keyboard_arrow_up","unfold_more","unfold_less",
            "keyboard_double_arrow_left","keyboard_double_arrow_right",
            "arrow_drop_down","arrow_drop_up","navigate_before","navigate_next"
          ]);
          function hide(el){
            el.style.setProperty("font-size","0","important");
            el.style.setProperty("line-height","0","important");
            el.style.setProperty("opacity","0","important");
            el.style.setProperty("width","0","important");
            el.style.setProperty("height","0","important");
            el.style.setProperty("overflow","hidden","important");
            el.style.setProperty("color","transparent","important");
            el.style.setProperty("visibility","hidden","important");
          }
          function tick(){
            try {
              const doc = window.parent.document;
              const sb = doc.querySelector('[data-testid="stSidebar"]');
              if (!sb) return;
              sb.querySelectorAll("span, i, div").forEach(el => {
                if (el.children.length !== 0) return;
                const t = (el.textContent || "").trim();
                if (!t) return;
                if (KNOWN.has(t) || (ICON_RE.test(t) && t.includes("_"))) hide(el);
              });
            } catch(e){}
          }
          tick();
          setInterval(tick, 300);
          try {
            const doc = window.parent.document;
            const sb = doc.querySelector('[data-testid="stSidebar"]');
            if (sb && window.MutationObserver) {
              new MutationObserver(tick).observe(sb, {childList:true, subtree:true, characterData:true});
            }
          } catch(e){}
        })();
        </script>
        """,
        height=1,
    )
except Exception:
    pass

# CSS para sacar el iframe vacío de la vista (lo pusheamos off-screen).
st.markdown(
    """<style>
iframe[title="streamlit_components.v1.html.html"],
[data-testid="stIFrame"] {
    position: absolute !important;
    left: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    visibility: hidden !important;
}
</style>""",
    unsafe_allow_html=True,
)
