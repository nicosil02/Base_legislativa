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

THEME_CSS = """
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
"""


def inject_theme() -> None:
    """Paleta Vali + tema base + texto del sidebar - antes copy-pasteado
    (con pequeñas variaciones de formato/orden) en las 9 paginas; una
    de esas variaciones tenia una regla vieja que causo el bug real del
    icono duplicado del sidebar (2026-09-22). Una sola fuente ahora."""
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
