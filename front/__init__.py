"""Interfaz propia: corre en el navegador dentro de un componente de Streamlit.
Filtros, pestanas y detalle no pasan por el servidor; Python solo entrega los
datos y recibe las acciones que si escriben algo."""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

_AQUI = Path(__file__).parent


def _leer(nombre: str) -> str:
    return (_AQUI / nombre).read_text(encoding="utf8")


_LOGO = base64.b64encode((_AQUI.parent / "assets" / "vali_logo.jpg").read_bytes()).decode()
_JS = ("nucleo.js", "v_panel.js", "v_noticias.js", "v_proyectos.js", "v_agenda.js", "v_transcripciones.js", "v_redaccion.js", "v_clientes.js", "v_personas.js")
_hecho: dict = {}


def app(*args, **kwargs):
    """El componente se vuelve a registrar si cambio un .js o el .css: Streamlit Cloud
    recarga los modulos .py que cambian, no estos archivos, y un push que solo tocaba
    el front seguia sirviendo el codigo viejo."""
    firma = tuple((_AQUI / f).stat().st_mtime_ns for f in (*_JS, "app.css"))
    if _hecho.get("firma") != firma:
        _hecho["comp"] = st.components.v2.component(
            "vali_app", html='<div class="app"></div>', css=_leer("app.css") + f'.logo{{background-image:url("data:image/jpeg;base64,{_LOGO}")}}',
            js=chr(10).join(_leer(f) for f in _JS))
        _hecho["firma"] = firma
    return _hecho["comp"](*args, **kwargs)

# Quita el marco de Streamlit en las paginas que usan la interfaz propia
# Inter para app.css; <link> y no @import, que frena el resto del estilo
SIN_MARCO = """<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400..700&display=swap" rel="stylesheet">
<style>
[data-testid="stSidebar"], [data-testid="stHeader"], footer { display:none !important; }
[data-testid="stMain"] { overflow:hidden !important; }
[data-testid="stMain"] .block-container { padding:0 !important; max-width:none !important; animation:none !important; }
[data-testid="stMainBlockContainer"] > div { gap:0 !important; }
</style>"""
