"""Interfaz propia: corre en el navegador dentro de un componente de Streamlit.
Filtros, pestanas y detalle no pasan por el servidor; Python solo entrega los
datos y recibe las acciones que si escriben algo."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_AQUI = Path(__file__).parent


def _leer(nombre: str) -> str:
    return (_AQUI / nombre).read_text(encoding="utf8")


_JS = ("nucleo.js", "v_panel.js", "v_noticias.js", "v_proyectos.js", "v_agenda.js", "v_redaccion.js")
app = st.components.v2.component("vali_app", html='<div class="app"></div>', css=_leer("app.css"),
                                 js=chr(10).join(_leer(f) for f in _JS))

# Quita el marco de Streamlit en las paginas que usan la interfaz propia
SIN_MARCO = """<style>
[data-testid="stSidebar"], [data-testid="stHeader"], footer { display:none !important; }
[data-testid="stMain"] { overflow:hidden !important; }
[data-testid="stMain"] .block-container { padding:0 !important; max-width:none !important; animation:none !important; }
[data-testid="stMainBlockContainer"] > div { gap:0 !important; }
</style>"""
