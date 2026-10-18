"""Votaciones nominales del Pleno bicameral (tablas de votaciones/pleno_bicameral.py):
como voto cada uno en un PL o un congresista, y disciplina de bancada.

Los PDF truncan nombres distinto segun la pagina ("FLORES RUIZ, VICTOR" vs
"FLORES RUIZ, VICTOR SEFERINO"): se identifica al congresista por camara +
apellidos (lo que va antes de la coma), sin tildes.
"""
from __future__ import annotations

import collections
import sqlite3

from core.text import norm

_POSTURAS = ("SI", "NO", "ABST")  # lo demas (AUS, licencias, SINRESP) no es postura


def clave_congresista(camara: str, nombre: str) -> str:
    # ponytail: dos congresistas con los mismos dos apellidos en la misma camara se juntan
    return f"{camara}:{norm(nombre.split(',')[0])}"


def _votos(conn: sqlite3.Connection, where: str = "", params=()) -> list[dict]:
    sql = ("SELECT v.id, v.camara, v.fecha, v.hora, v.asunto, v.pl_cod_tipo_parl, v.pley_num, "
           "n.congresista, n.bancada, n.voto FROM votacion_pleno v "
           "JOIN voto_pleno_nominal n ON n.votacion_id = v.id WHERE v.tipo = 'votacion' " + where +
           " ORDER BY v.fecha, v.hora, n.congresista")
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def votos_de_pl(conn: sqlite3.Connection, pley_num: int, cod_tipo_parl: str | None = None) -> list[dict]:
    """Todas las votaciones del Pleno que mencionan el PL, con el voto de cada uno."""
    if cod_tipo_parl:
        return _votos(conn, "AND v.pley_num = ? AND v.pl_cod_tipo_parl = ?", (pley_num, cod_tipo_parl))
    return _votos(conn, "AND v.pley_num = ?", (pley_num,))


def votos_de_congresista(conn: sqlite3.Connection, nombre: str) -> list[dict]:
    """Votos de quien tenga `nombre` (sin tildes ni mayusculas) en su nombre."""
    q = norm(nombre)
    return [v for v in _votos(conn) if q in norm(v["congresista"])]


def disciplina(conn: sqlite3.Connection, camara: str | None = None) -> list[dict]:
    """Por congresista: votaciones con postura (SI/NO/ABST) y % en que voto
    igual que la mayoria de su bancada en esa votacion. Si la bancada empata
    no hay mayoria y esa votacion no cuenta. Ordenado del menos alineado."""
    votos = [v for v in _votos(conn) if v["voto"] in _POSTURAS and (camara is None or v["camara"] == camara)]
    por_bancada = collections.defaultdict(collections.Counter)
    for v in votos:
        por_bancada[(v["id"], v["bancada"])][v["voto"]] += 1
    acc = {}
    for v in votos:
        top = por_bancada[(v["id"], v["bancada"])].most_common(2)
        if len(top) == 2 and top[0][1] == top[1][1]:
            continue
        k = clave_congresista(v["camara"], v["congresista"])
        a = acc.setdefault(k, {"camara": v["camara"], "congresista": v["congresista"], "bancada": v["bancada"],
                               "votaciones": 0, "alineado": 0})
        if len(v["congresista"]) > len(a["congresista"]):
            a["congresista"] = v["congresista"]
        a["votaciones"] += 1
        a["alineado"] += v["voto"] == top[0][0]
    for a in acc.values():
        a["pct_alineado"] = round(100 * a["alineado"] / a["votaciones"], 1)
    return sorted(acc.values(), key=lambda a: (a["pct_alineado"], a["congresista"]))
