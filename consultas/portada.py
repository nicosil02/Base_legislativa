"""Numeros de la portada (home.py). Todo devuelve None donde la base no esta
o la consulta falla, y la portada muestra "—"."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date

import streamlit as st

from consultas import base
from scraper.sync import PER_PAR_ID_ACTUAL

def _abrir(nombre: str) -> sqlite3.Connection | None:
    db = base(nombre)
    return sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True) if db else None


def _uno(conn: sqlite3.Connection, sql: str, params=()):
    try:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None
    except sqlite3.OperationalError:
        return None


def _tiene(conn: sqlite3.Connection, tabla: str) -> bool:
    return _uno(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,)) is not None


def _contar(nombre: str, claves: tuple[str, ...], tabla: str | None, sqls: list[tuple[str, tuple]]) -> dict:
    """Corre los COUNT de `sqls` en la base `nombre`. Sin la tabla `tabla`, 0."""
    vacio = dict.fromkeys(claves)
    conn = _abrir(nombre)
    if conn is None:
        return vacio
    try:
        with closing(conn):
            if tabla and not _tiene(conn, tabla):
                return dict.fromkeys(claves, 0)
            return {k: conn.execute(sql, p).fetchone()[0] for k, (sql, p) in zip(claves, sqls)}
    except Exception:
        return vacio


@st.cache_data(ttl=60)
def stats_peru() -> dict:
    """Solo el periodo vigente (per_par_id actual), igual que la pagina Perú:
    el 2021-2026 unicameral quedo aparte por pedido de Nicolas (2026-09-16)."""
    return _contar("proyectos.db", ("total", "leyes"), None, [
        ("SELECT COUNT(*) FROM proyectos WHERE per_par_id=?", (PER_PAR_ID_ACTUAL,)),
        ("SELECT COUNT(*) FROM proyectos WHERE per_par_id=? AND "
         "(UPPER(estado) LIKE '%PUBLIC%PERUANO%' OR UPPER(estado) LIKE '%LEY PUBLICADA%')", (PER_PAR_ID_ACTUAL,))])


@st.cache_data(ttl=60)
def stats_ecuador() -> dict:
    return _contar("proyectos_ec.db", ("total", "publicados"), None, [
        ("SELECT COUNT(*) FROM proyectos", ()),
        ("SELECT COUNT(*) FROM proyectos WHERE UPPER(estado) = 'REGISTRO OFICIAL'", ())])


@st.cache_data(ttl=60)
def stats_agenda() -> dict:
    """Sesiones PE de hoy (comisiones + pleno) y proximas convocadas."""
    hoy = date.today().isoformat()
    return _contar("proyectos.db", ("hoy", "proximas"), "sesiones", [
        ("SELECT COUNT(*) FROM sesiones WHERE fecha = ?", (hoy,)),
        ("SELECT COUNT(*) FROM sesiones WHERE UPPER(estado)='CONVOCADA' AND fecha >= ?", (hoy,))])


@st.cache_data(ttl=60)
def stats_agenda_ec() -> dict:
    """Sesiones EC de hoy y proximas (sesiones_ec, del ICS de Zimbra)."""
    hoy = date.today().isoformat()
    return _contar("proyectos_ec.db", ("hoy", "proximas"), "sesiones_ec", [
        ("SELECT COUNT(*) FROM sesiones_ec WHERE fecha = ?", (hoy,)),
        ("SELECT COUNT(*) FROM sesiones_ec WHERE fecha >= ?", (hoy,))])


@st.cache_data(ttl=60)
def stats_noticias(pais: str) -> dict:
    """Fuentes activas y noticias capturadas del pais."""
    return _contar("proyectos.db", ("fuentes", "noticias"), "noticias_fuentes", [
        ("SELECT COUNT(*) FROM noticias_fuentes WHERE pais=? AND activa=1", (pais,)),
        ("SELECT COUNT(n.id) FROM noticias n JOIN noticias_fuentes f ON f.id=n.fuente_id WHERE f.pais=?", (pais,))])
