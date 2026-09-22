"""Polish compartido de UI para toda la app Vali - complementa (no
reemplaza) el bloque de CSS propio de cada pagina (paleta, tipografia,
sidebar). Evita repetir estas reglas en las 9 paginas.

Aplica principios de la skill de diseño de Emil Kowalski (emil-design-eng):
botones con feedback de "press" (scale al :active), curvas de easing
propias en vez de las de CSS por defecto, y transiciones cortas (<300ms)
en vez de "transition: all".
"""
from __future__ import annotations

import streamlit as st

FONT_LINKS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
"""

THEME_CSS = """
:root {
  --ink:        #0A294D;
  --ink-soft:   #435D74;
  --ink-mute:   #5D7286;  /* era #869FB2 (~2.6:1 sobre blanco, falla WCAG
                             AA); critique 2026-09-22. Nuevo valor ~5:1. */
  --line:       #CFD9E0;
  --line-soft:  #E3E9ED;
  --accent:     #0A294D;
  --accent-red: #BF1A1A;
  --gold:       #9C7A2E;  /* sello/registro oficial - solo para Normativa,
                             nunca como color de marca general */
  --bg:         #FBFAF7;  /* antes #FFFFFF puro - blanco calido tipo papel
                             de gaceta, no blanco "SaaS generico". Pase de
                             diseno 2026-09-22 (frontend-design skill). */
  --bg-soft:    #F4F6F8;
}
html, body, [class*="css"], .stApp {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
  color: var(--ink);
  background-color: var(--bg);
}
/* === Numeros de KPI en la misma serif que los titulos de pagina ===
   Pase de diseno 2026-09-22 (frontend-design skill, "vamos mas lejos"):
   los numeros grandes (total de PLs, sesiones, noticias...) SON el
   contenido real de un registro legislativo - tratarlos como cifras de
   un acta/certificado en vez de un numero de dashboard SaaS generico
   conecta la identidad "registro oficial" con lo que el usuario mira
   primero en cada pagina. Una sola regla centralizada: las 6 paginas ya
   fijan color/weight/size en su propio bloque, esto solo agrega la
   tipografia por encima sin tocar esas reglas. */
div[data-testid="stMetricValue"] {
  font-family: Georgia, 'Times New Roman', serif !important;
}
/* === Entrada escalonada de las tarjetas de KPI ===
   Hallazgo real 2026-09-22 (Nicolas: "no se ve nada mejorado, quiero
   animaciones, se siente lenta y fea"): las tarjetas de KPI (lo primero
   que se ve en cada pagina) no tenian ningun movimiento, a diferencia
   de las country-card del Inicio que si tienen entrada escalonada.
   Mismo patron aca, aplicado centralizado para las 6 paginas. */
@keyframes kpiEnter {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
div[data-testid="stMetric"] {
  animation: kpiEnter 380ms cubic-bezier(.16,1,.3,1) both;
}
[data-testid="stColumn"]:nth-child(1) div[data-testid="stMetric"] { animation-delay: 0ms; }
[data-testid="stColumn"]:nth-child(2) div[data-testid="stMetric"] { animation-delay: 40ms; }
[data-testid="stColumn"]:nth-child(3) div[data-testid="stMetric"] { animation-delay: 80ms; }
[data-testid="stColumn"]:nth-child(4) div[data-testid="stMetric"] { animation-delay: 120ms; }
[data-testid="stColumn"]:nth-child(5) div[data-testid="stMetric"] { animation-delay: 160ms; }
[data-testid="stColumn"]:nth-child(6) div[data-testid="stMetric"] { animation-delay: 200ms; }
[data-testid="stColumn"]:nth-child(7) div[data-testid="stMetric"] { animation-delay: 240ms; }
[data-testid="stColumn"]:nth-child(8) div[data-testid="stMetric"] { animation-delay: 280ms; }
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
"""


def inject_theme() -> None:
    """Paleta Vali + tema base + texto del sidebar - antes copy-pasteado
    (con pequeñas variaciones de formato/orden) en las 9 paginas; una
    de esas variaciones tenia una regla vieja que causo el bug real del
    icono duplicado del sidebar (2026-09-22). Una sola fuente ahora.

    La fuente Inter se cargaba con @import DENTRO del <style> - eso
    bloquea la aplicacion de TODO ese bloque (colores de marca, sidebar
    navy, todo) hasta que Google Fonts responde, en cada carga de
    pagina (Streamlit navega con hard-reload del browser entre paginas,
    asi que esto se repetia constantemente). Hallazgo real 2026-09-22
    (Nicolas: "se siente lenta"). <link rel="preconnect"> + <link
    rel="stylesheet"> es el metodo que la propia Google Fonts recomienda
    para produccion en vez de @import - el browser lo descarga en
    paralelo con el resto de la pagina en lugar de bloquearla."""
    st.markdown(FONT_LINKS, unsafe_allow_html=True)
    st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)


BUTTON_POLISH_CSS = """
/* === Polish de botones/checkboxes del area principal (ui_kit.py) ===
   Streamlit los pinta en gris chrome por defecto, sin relacion con la
   marca. Escapado a [data-testid="stMain"] para no pisar el estilo ya
   existente de los botones del sidebar. */
[data-testid="stMain"] [data-testid="stPopoverButton"],
[data-testid="stMain"] button[data-testid="stBaseButton-secondary"] {
  border: 1px solid var(--line) !important;
  border-radius: 8px !important;
  color: var(--ink-soft) !important;
  background: var(--bg) !important;
  font-weight: 700 !important;
  font-size: 12.5px !important;
  transition: transform 140ms cubic-bezier(0.23,1,0.32,1),
              border-color 140ms ease, color 140ms ease !important;
}
[data-testid="stMain"] [data-testid="stPopoverButton"]:hover,
[data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:hover {
  border-color: var(--accent) !important;
  color: var(--ink) !important;
}
[data-testid="stMain"] [data-testid="stPopoverButton"]:active,
[data-testid="stMain"] button[data-testid="stBaseButton-secondary"]:active {
  transform: scale(0.97);
}
/* "primary" es el unico kind que usamos para acciones destructivas/
   principales (ej. Descartar) - rojo Vali en version ligera (outline,
   no bloque solido) para no romper el minimalismo del resto. */
[data-testid="stMain"] button[data-testid="stBaseButton-primary"] {
  background: var(--bg) !important;
  border: 1px solid var(--accent-red) !important;
  color: var(--accent-red) !important;
  border-radius: 8px !important;
  font-weight: 700 !important;
  font-size: 12.5px !important;
  transition: transform 140ms cubic-bezier(0.23,1,0.32,1),
              background-color 140ms ease !important;
}
[data-testid="stMain"] button[data-testid="stBaseButton-primary"]:hover {
  background: #FFF3F3 !important;
}
[data-testid="stMain"] button[data-testid="stBaseButton-primary"]:active {
  transform: scale(0.97);
}
[data-testid="stMain"] [data-testid="stCheckbox"] label p {
  font-size: 12.5px !important;
  color: var(--ink-soft) !important;
  font-weight: 600 !important;
}
/* Inputs de texto/select: borde mas suave, foco con el navy de marca en
   vez del rojo default de Streamlit. */
[data-testid="stMain"] input, [data-testid="stMain"] textarea {
  border-radius: 8px !important;
}
[data-testid="stMain"] div[data-baseweb="select"] > div {
  border-radius: 8px !important;
  transition: border-color 140ms ease !important;
}
"""


def inject_button_polish() -> None:
    st.markdown(f"<style>{BUTTON_POLISH_CSS}</style>", unsafe_allow_html=True)
