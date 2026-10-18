"""Consultas de datos de las paginas de Streamlit: cada pagina solo dibuja.

Un modulo por pagina (peru, ecuador, agenda_pe, agenda_ec); aca lo que
comparten: la conexion de solo lectura, la matriz de PL de clientes y la
hora del Congreso pasada a minutos.
"""
from __future__ import annotations

import sqlite3

import streamlit as st

from core.db import db_path


def conexion(nombre: str, ayuda: str) -> sqlite3.Connection:
    """Conexion fresca de solo lectura. No se cachea con cache_resource: un
    handle viejo entre reruns daba 'disk I/O error'. Sin base, `ayuda` y stop."""
    db = db_path(nombre)
    if not db.exists() or db.stat().st_size == 0:
        st.error(f"No encontré `{nombre}`. {ayuda}")
        st.stop()
    conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=60)
def matriz_pls(pais: str) -> dict[str, set[str]]:
    """{cliente: numeros de PL de su matriz puntual en pais} ("matriz_pl" de
    clientes/<slug>/cliente.json). La matriz PE de Incode quedo vieja con el
    Congreso bicameral; en EC su estado puede estar viejo, solo vale el numero."""
    from clientes import config
    out = {s: {f["pl_numero"] for f in config.matriz(s, pais)} for s in config.slugs()}
    return {s: v for s, v in out.items() if v}


def hora_a_minutos(hora: str | None) -> int:
    """"9:00AM", "2:30PM" (PE) o "14:30" (EC) a minutos desde medianoche, para
    ordenar. Vacio o raro: -1."""
    if not hora or not isinstance(hora, str):
        return -1
    s = hora.strip().upper()
    pm, am = s.endswith("PM"), s.endswith("AM")
    if pm or am:
        s = s[:-2].strip()
    try:
        h, m = (int(x) for x in s.split(":"))
    except ValueError:
        return -1
    if am and h == 12:
        h = 0
    elif pm and h != 12:
        h += 12
    return h * 60 + m


def base(nombre: str):
    """Path de la base si existe y no esta vacia, si no None (para escribir
    desde la pagina, ej. el sync en vivo)."""
    db = db_path(nombre)
    return db if db.exists() and db.stat().st_size > 0 else None
