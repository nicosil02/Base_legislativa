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


@st.cache_data(ttl=1800, show_spinner=False)
def afinidad_claves(claves: tuple[str, ...], cliente: str) -> dict[str, float]:
    """{clave del cerebro: afinidad con el cliente} (PLs: pl_PE_<proyecto_ley>,
    pl_EC_<n_tramite>). {} si el cerebro no esta disponible."""
    conn = conexion()
    if conn is None or not claves:
        return {}
    from cerebro.embeddings import afinidad
    try:
        return afinidad(list(claves), cliente, conn)
    except Exception as e:
        print(f"[cerebro] afinidad fallo: {e}")
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def afinidad_tema_noticias(ids: tuple[int, ...], tema: str) -> dict[int, float]:
    """{id de noticia: afinidad con el tema/sector}. {} si no hay cerebro.
    El vector del tema viene precalculado del workflow (cerebro.db, meta):
    la app nunca carga el modelo de embeddings (~600 MB de RAM)."""
    conn = conexion()
    if conn is None or not ids:
        return {}
    from cerebro.embeddings import afinidad_vector, vector_tema
    try:
        v = vector_tema(tema, conn)
        if v is None:
            return {}
        af = afinidad_vector([f"noticia_{i}" for i in ids], v, conn)
    except Exception as e:
        print(f"[cerebro] afinidad de tema fallo: {e}")
        return {}
    return {int(k.split("_", 1)[1]): v for k, v in af.items()}
