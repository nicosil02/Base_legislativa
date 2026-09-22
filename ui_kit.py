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
