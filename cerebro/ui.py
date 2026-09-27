"""Acceso al cerebro desde las paginas de Streamlit (conexion cacheada)."""
from __future__ import annotations

import streamlit as st


@st.cache_resource(ttl=3 * 3600, show_spinner="Cargando el cerebro...")
def conexion():
    """Conexion a data/cerebro.db (bajado del release, ver
    cerebro.embeddings.descargar_si_falta). None si todavia no esta."""
    from cerebro.embeddings import conectar, descargar_si_falta
    try:
        path = descargar_si_falta()
        return conectar(path) if path else None
    except Exception as e:
        print(f"[cerebro] no disponible: {e}")
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def afinidad_noticias(ids: tuple[int, ...], cliente: str) -> dict[int, float]:
    """{id de noticia: afinidad 0-1 con el perfil del cliente}. {} si el
    cerebro no esta disponible - la pagina sigue igual que antes."""
    conn = conexion()
    if conn is None or not ids:
        return {}
    from cerebro.embeddings import afinidad
    try:
        af = afinidad([f"noticia_{i}" for i in ids], cliente, conn)
    except Exception as e:
        print(f"[cerebro] afinidad fallo: {e}")
        return {}
    return {int(k.split("_", 1)[1]): v for k, v in af.items()}
