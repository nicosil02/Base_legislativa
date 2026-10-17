"""Puntos de agenda de HOY para una sesion detectada EN VIVO, para el aviso
inicial (sale de la agenda que ya tenemos, no de la transcripcion).

  - Comisiones: tablas `sesiones` + `sesion_agenda_punto`.
  - Pleno: `pleno_agenda_pdf` (no `pleno_sesiones`/`pleno_tema`, que son de
    la API unicameral y ya no reciben filas). El PDF no trae puntos
    estructurados: se parsea su seccion "ÍNDICE".
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta

from core.text import norm as _norm
from core.tiempo import LIMA

MAX_PUNTOS = 4
MAX_CHARS_PUNTO = 140


def _camara_de_titulo(titulo: str | None) -> str | None:
    t = _norm(titulo)
    if "diputados" in t:
        return "Diputados"
    if "senado" in t:
        return "Senado"
    return None


_RE_FECHA_TITULO = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")


def _fecha_del_titulo(titulo: str | None) -> str | None:
    """Fecha del titulo de YouTube ("...| 09/09/2026"); suele ser mas
    confiable que la fecha UTC de captura. None si no hay o no es valida."""
    m = _RE_FECHA_TITULO.search(titulo or "")
    if not m:
        return None
    dia, mes, anio = m.groups()
    anio = anio if len(anio) == 4 else f"20{anio}"
    try:
        return datetime(int(anio), int(mes), int(dia)).date().isoformat()
    except ValueError:
        return None


def camara_de_agenda(db: sqlite3.Connection, tipo: str, titulo: str | None,
                     fecha: str | None) -> str | None:
    """Camara de una Comision cuyo titulo no la dice (hay comisiones con el
    mismo nombre en ambas camaras), segun quien tenia sesion agendada ese
    dia. Prueba la fecha del titulo y `fecha` (UTC de captura) y el dia
    anterior. None si no hay match o es ambiguo: no adivina."""
    if not tipo.startswith("Comision:"):
        return None
    kw = _norm(tipo.split(":", 1)[-1].strip())
    candidatas: set[str] = set()
    del_titulo = _fecha_del_titulo(titulo)
    if del_titulo:
        candidatas.add(del_titulo)
    if fecha:
        try:
            d = datetime.fromisoformat(fecha).date()
            candidatas.add(d.isoformat())
            candidatas.add((d - timedelta(days=1)).isoformat())
        except ValueError:
            pass
    if not candidatas:
        return None
    fechas = tuple(candidatas)
    rows = db.execute(
        f"SELECT nombre_comision, camara FROM sesiones WHERE fecha IN "
        f"({','.join('?' * len(fechas))})", fechas,
    ).fetchall()
    camaras = {_norm(camara) for nombre, camara in rows if camara and kw in _norm(nombre)}
    if camaras == {"senado"}:
        return "Senado"
    if camaras == {"diputados"}:
        return "Diputados"
    return None


def puntos_agenda_comision(db: sqlite3.Connection, tipo: str, titulo: str,
                           max_puntos: int = MAX_PUNTOS) -> list[str]:
    """tipo: 'Comision: <kw>'. Busca la sesion de HOY (hora Lima) que matchea
    por keyword y camara del titulo. Si hay 0 o mas de 1 match devuelve []
    antes que mostrar la agenda de otra comision."""
    if not tipo.startswith("Comision:"):
        return []
    kw = _norm(tipo.split(":", 1)[-1].strip())
    camara = _camara_de_titulo(titulo)
    hoy_lima = datetime.now(LIMA).date().isoformat()

    rows = db.execute(
        "SELECT id_sesion, nombre_comision, camara FROM sesiones WHERE fecha = ?",
        (hoy_lima,),
    ).fetchall()
    candidatas = [
        r for r in rows
        if kw in _norm(r[1])
        and (camara is None or not r[2] or _norm(r[2]) == _norm(camara))
    ]
    if len(candidatas) != 1:
        return []

    puntos = db.execute(
        """SELECT descripcion_texto FROM sesion_agenda_punto
           WHERE id_sesion=? ORDER BY orden LIMIT ?""",
        (candidatas[0][0], max_puntos),
    ).fetchall()
    return [_una_linea_corta(p[0]) for p in puntos if p[0] and p[0].strip()]


_RE_ROMANO = re.compile(r"[IVXLC]+\.?$")
_RE_HEADER_PAGINA = re.compile(
    r"(agenda del pleno|agenda de la sesi[oó]n del pleno|"
    r"c[aá]mara de diputados|senado de la rep[uú]blica)",
    re.IGNORECASE,
)


def _extraer_indice(texto: str, max_items: int = MAX_PUNTOS) -> list[str]:
    """Items de la seccion "ÍNDICE" del PDF de agenda: texto entre "ÍNDICE"
    y el siguiente encabezado de pagina, sin numeros de pagina, pegando
    cada numeral romano suelto ("I.") al titulo que le sigue."""
    m = re.search(r"índice", texto, re.IGNORECASE)
    if not m:
        return []
    resto = texto[m.end():]
    m2 = _RE_HEADER_PAGINA.search(resto)
    bloque = resto[:m2.start()] if m2 else resto[:800]

    crudas = [l.strip() for l in bloque.splitlines() if l.strip()]
    crudas = [
        l for l in crudas
        if not re.fullmatch(r"\d+", l)
        and not re.fullmatch(r"p[aá]g\.?", l, re.IGNORECASE)
        and not re.fullmatch(r"índice", l, re.IGNORECASE)
    ]

    out: list[str] = []
    pendiente = ""
    for l in crudas:
        if _RE_ROMANO.fullmatch(l):
            pendiente = l.rstrip(".")
            continue
        out.append(f"{pendiente}. {l}" if pendiente else l)
        pendiente = ""
        if len(out) >= max_items:
            break
    return out


def puntos_agenda_pleno(db: sqlite3.Connection, tipo: str,
                        max_puntos: int = MAX_PUNTOS) -> list[str]:
    """tipo: 'Pleno: Senado'/'Pleno: Diputados'. [] para 'Pleno: Congreso'
    (no hay camara para elegir el PDF) o si el PDF de hoy aun no esta."""
    camara = {"Pleno: Senado": "senado", "Pleno: Diputados": "diputados"}.get(tipo)
    if not camara:
        return []
    hoy_lima = datetime.now(LIMA).date().isoformat()
    row = db.execute(
        "SELECT texto FROM pleno_agenda_pdf WHERE camara=? AND fecha=? "
        "ORDER BY length(texto) DESC LIMIT 1",
        (camara, hoy_lima),
    ).fetchone()
    if not row:
        return []
    return _extraer_indice(row[0], max_puntos)


def puntos_agenda(db: sqlite3.Connection, tipo: str, titulo: str) -> list[str]:
    """Despacha a comision o Pleno segun el prefijo de `tipo`."""
    if tipo.startswith("Pleno:"):
        return puntos_agenda_pleno(db, tipo)
    return puntos_agenda_comision(db, tipo, titulo)


def _una_linea_corta(texto: str, max_chars: int = MAX_CHARS_PUNTO) -> str:
    """Primera linea no vacia, recortada a max_chars (los puntos reales son
    parrafos largos)."""
    primera = next((l.strip() for l in texto.splitlines() if l.strip()), "")
    if len(primera) > max_chars:
        primera = primera[:max_chars - 1].rstrip() + "…"
    return primera


def agenda_extra_para(v: dict) -> str:
    """Bloque de agenda para el aviso de esta sesion, o '' si no hay DB,
    no hay match o hay cualquier error: nunca debe romper el aviso."""
    from congreso_live.transcripciones import _find_db_path

    try:
        db_path = _find_db_path()
        if not db_path.exists():
            return ""
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            puntos = puntos_agenda(conn, v["tipo"], v["titulo"])
        finally:
            conn.close()
        return formatear_para_whatsapp(puntos)
    except Exception:
        return ""


def formatear_para_whatsapp(puntos: list[str]) -> str:
    """'' si no hay puntos, o un bloque tipo:
    \\n\\nPuntos de agenda:\\n- Punto 1\\n- Punto 2"""
    if not puntos:
        return ""
    lineas = "\n".join(f"- {p}" for p in puntos)
    return f"\n\nPuntos de agenda:\n{lineas}"
