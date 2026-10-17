"""Boton "Armar alerta": lleva lo elegido (noticia, PL, video) al chat de la
pagina Alertas, con el cliente ya elegido."""
from __future__ import annotations

import streamlit as st

SEMILLA = "alerta_semilla"
PAGINA = "pages/7_Alertas.py"


def item(titulo: str, url: str | None = None, resumen: str | None = None, pais: str | None = None,
         fuente: str | None = None, fecha: str | None = None, tipo: str = "noticia") -> dict:
    return {"titulo": titulo, "url": url, "resumen": resumen, "pais": pais,
            "fuente": fuente, "fecha": (fecha or "")[:10] or None, "tipo": tipo}


def ir_al_chat(items: list[dict], cliente: str, por_que: str | None = None) -> None:
    st.session_state[SEMILLA] = {"cliente": cliente, "items": items, "por_que": por_que}
    st.switch_page(PAGINA)


def boton(items: list[dict], clientes: list[str], key: str, contenedor=None,
          cliente: str | None = None, por_que: str | None = None) -> None:
    """Popover con el cliente y el boton que abre el chat."""
    with (contenedor or st).popover("✍️ Armar alerta", help="Abre el chat de Alertas con esto cargado"):
        idx = clientes.index(cliente) if cliente in clientes else None
        cli = st.selectbox("¿Para qué cliente?", clientes, index=idx,
                           placeholder="Elige el cliente", key=f"armar_cli_{key}")
        if st.button("Armar", key=f"armar_btn_{key}", disabled=not cli, type="primary"):
            ir_al_chat(items, cli, por_que)
