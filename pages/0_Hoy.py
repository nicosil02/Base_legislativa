"""Vali Intelligence: toda la interfaz vive en un componente (front/). Esta
pagina solo lo monta y atiende lo que el navegador le pide."""
from __future__ import annotations

import streamlit as st

from alerts import historial
from clientes import config
from front import SIN_MARCO, app
from front.vistas import almacen, atender
from ui_kit import inject_theme

inject_theme()
st.markdown(SIN_MARCO, unsafe_allow_html=True)
almacen()  # arranca el armado por detras desde la primera visita

# Proyectos, agenda y noticias van sin pais: el selector de arriba elige _pe o _ec
MENU = [["", [["Panel", "panel", "inicio"], ["Transcripciones", "transcripciones", "micro"], ["Proyectos de ley", "proyectos", "doc"],
              ["Agenda", "agenda", "cal"], ["Noticias", "noticias", "diario"]]],
        ["Trabajo", [["Redactar alerta", "alertas", "pluma"], ["Resumen del día", "resumen", "lista"], ["Buscar en todo", "buscar", "buscar"]]]]
BASE = {"menu": MENU, "usuario": st.user.get("email"),
        "clientes": {s: {"nombre": config.todos()[s]["nombre"], "paises": list(config.todos()[s]["paises"])}
                     for s in historial.clientes()}}


def _al_pedir() -> None:
    """Corre antes de volver a montar: la respuesta sale en ese mismo montaje."""
    a = st.session_state["vali"].get("accion")
    if not a:
        return
    if a["tipo"] == "salir":
        st.session_state["vali_salir"] = True
        return
    try:
        salida = {"id": a["id"], "datos": atender(a, st.user.get("email"))}
    except Exception as e:
        print(f"[front] {a['tipo']}: {type(e).__name__}: {e}")
        salida = {"id": a["id"], "error": str(e)}
    st.session_state.setdefault("vali_salidas", []).append(salida)


@st.fragment
def _app() -> None:
    if st.session_state.pop("vali_salir", False):
        st.logout()
    # se manda cada respuesta una sola vez: reenviarlas pesaria megas en cada ida y vuelta
    salidas = st.session_state.pop("vali_salidas", [])
    app(data={**BASE, "salidas": salidas}, key="vali", on_accion_change=_al_pedir)


_app()
