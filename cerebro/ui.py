"""Acceso al cerebro desde las paginas de Streamlit (conexion cacheada)."""
from __future__ import annotations

import sqlite3

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


@st.cache_data(ttl=1800, show_spinner=False)
def le_interesa(ids: tuple[int, ...]) -> dict[int, list[tuple[str, str]]]:
    """{id de noticia: [(cliente, por que)]} segun alerts/filtro.py, solo las
    que SI le interesan a alguien. {} si no hay cerebro o aun no hay veredictos."""
    conn = conexion()
    if conn is None or not ids:
        return {}
    out: dict[int, list[tuple[str, str]]] = {}
    try:
        for i in range(0, len(ids), 900):
            lote = [f"noticia_{x}" for x in ids[i:i + 900]]
            for clave, cliente, por_que in conn.execute(
                    f"SELECT clave, cliente, por_que FROM relevancia WHERE interesa = 1 "
                    f"AND clave IN ({','.join('?' * len(lote))})", lote):
                out.setdefault(int(clave.split("_", 1)[1]), []).append((cliente, por_que))
    except Exception as e:  # tabla todavia no creada en el cerebro.db publicado
        print(f"[cerebro] relevancia no disponible: {e}")
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def historias_noticias(ids: tuple[int, ...], titulos: tuple[str, ...],
                       fuentes: tuple[str, ...]) -> list[int]:
    """Grupo por noticia (noticias/historias.agrupar): las de distintos
    portales que cuentan el mismo hecho comparten numero. Sin cerebro, cada
    una sola."""
    conn = conexion()
    if conn is None or not ids:
        return list(range(len(ids)))
    from cerebro.embeddings import vectores_noticias
    from noticias.historias import UMBRAL_NOTICIAS, agrupar, similitudes_noticias
    pos = {n: k for k, n in enumerate(ids)}
    try:
        vec = vectores_noticias(ids, conn)
    except Exception as e:
        print(f"[cerebro] vectores fallo: {e}")
        return list(range(len(ids)))
    juicios = {}
    lista = ",".join(str(int(i)) for i in ids)
    try:
        for a, b, igual in conn.execute(
                f"SELECT a, b, igual FROM mismo_hecho WHERE a IN ({lista}) AND b IN ({lista})"):
            juicios[(pos[a], pos[b])] = bool(igual)
    except sqlite3.OperationalError:  # cerebro.db sin la tabla mismo_hecho todavia
        pass
    sims = similitudes_noticias([vec.get(i) for i in ids], list(titulos), list(fuentes), juicios)
    return agrupar(list(titulos), sims=sims, umbral=UMBRAL_NOTICIAS)
