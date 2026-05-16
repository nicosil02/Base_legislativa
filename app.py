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
