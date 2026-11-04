"""Ficha de un congresista (PE, periodo bicameral 2026-2031) o asambleista (EC,
2025-2029): bancada, proyectos que firmo, como voto en el Pleno, que dijo en
las sesiones transcritas y las mesas que organizo.

Se identifica a la persona por sus dos apellidos sin tildes: es lo unico que
coincide entre los PDF de votacion ("FLORES RUIZ, VICTOR"), los autores de un PL
("Flores Ruiz, Víctor Seferino") y el habla de una sesion ("el congresista Flores").
"""
from __future__ import annotations

import re
import sqlite3

from consultas.votaciones import _POSTURAS, _votos, clave_congresista, disciplina
from core.text import norm, sin_tildes

PER_PE = 2026
PERIODO_EC = "2025-2029"
# en el habla rara vez se dicen los dos apellidos: "la congresista Matute", "asambleista Duran"
_TITULO = r"(?:congresista|diputad[oa]|senador[a]?|asambleista|legislador[a]?|colega)"
MAX_SESIONES = 12
# pasar lista o votar nombre por nombre ("X, presente. Y, a favor. Z, si.")
_LISTA = re.compile(r"\b(?:presente|a favor|en contra|abstencion|si|no)\b\s*[.,]")


def apellidos(pais: str, nombre: str) -> str:
    """'MATUTE CHARUN, SUSANA' -> 'matute charun' (PE); EC trae 'ABAD MOROCHO MERCEDES LUZMILA'."""
    if pais == "PE":
        return norm(nombre.split(",")[0])
    return " ".join(norm(nombre).split()[:2])


def _patron(ap: str) -> re.Pattern:
    primero = re.escape(ap.split()[0])
    return re.compile(rf"\b{re.escape(ap)}\b|\b{_TITULO}\s+(?:\w+\s+){{0,3}}?{primero}\b")


def _sesiones(pe: sqlite3.Connection, pais: str, ap: str) -> list[dict]:
    from congreso_live.facebook_ec import url_video
    patron = _patron(ap)
    # SQLite no ignora tildes: las letras que pueden llevarla van como comodin ("n_nez" halla "Núñez")
    comodin = "%" + re.sub(r"[aeioun]", "_", ap.split()[0]) + "%"
    filtro = "LIKE '%(EC)'" if pais == "EC" else "NOT LIKE '%(EC)'"
    salida = []
    for vid, tipo, titulo, fecha, texto in pe.execute(
            f"""SELECT video_id, tipo, titulo, fecha, texto FROM sesiones_transcripciones
                WHERE tipo {filtro} AND tipo NOT LIKE 'Entrevista:%' AND texto LIKE ?
                ORDER BY fecha DESC""", (comodin,)):
        plano = sin_tildes((texto or "").lower())
        # en una lista o votacion nominal el nombre va rodeado de "presente", "si", "a favor"...
        hallados = [m for m in patron.finditer(plano)
                    if len(_LISTA.findall(plano, max(0, m.start() - 150), m.end() + 150)) < 3]
        if not hallados:
            continue
        # las posiciones valen en el original si quitar tildes no cambio el largo (texto en NFC)
        base = texto if len(texto) == len(plano) else plano
        # primero cuando le dan la palabra: lo que sigue es lo que dijo
        mejores = sorted(hallados, key=lambda m: "palabra" not in plano[max(0, m.start() - 80):m.end() + 40])[:2]
        trozos = [re.sub(r"\s+", " ", base[max(0, m.start() - 80):m.end() + 360]).strip() for m in sorted(mejores, key=lambda m: m.start())]
        salida.append({"fecha": fecha, "organo": tipo, "titulo": titulo, "video_id": vid, "menciones": len(hallados),
                       "trozos": trozos,
                       "url": url_video(vid) if pais == "EC" else f"https://www.youtube.com/watch?v={vid}"})
        if len(salida) == MAX_SESIONES:
            break
    return salida


def ficha(pe: sqlite3.Connection, ec: sqlite3.Connection, pais: str, ident: str, seguidos: set[str]) -> dict:
    """ident: el id de personas(). seguidos: claves 'PAIS:pl' de alerts.pls_seguidos."""
    if pais == "PE":
        camara, ap = ident.split(":", 1)
        rx = re.compile(rf"(?:^|;)\s*{re.escape(ap)}\s*,")
        pls = [{"pl": pl, "titulo": t, "estado": e, "fecha": (f or "")[:10], "bancada": g, "primero": norm(a).startswith(ap)}
               for pl, t, e, f, g, a in pe.execute(
                   """SELECT proyecto_ley, titulo, estado, fec_presentacion, grupo_parlamentario, autores_raw
                      FROM proyectos WHERE per_par_id = ? AND instr(lower(autores_raw), ?) > 0
                      ORDER BY fec_presentacion DESC""", (PER_PE, ap.split()[0]))
               if rx.search(norm(a))]
        votos = [v for v in _votos(pe, "AND v.camara = ?", (camara,)) if clave_congresista(v["camara"], v["congresista"]) == ident]
        # con quien voto la mayoria de su bancada en cada votacion
        cuenta: dict[tuple, dict] = {}
        for vid, b, voto, n in pe.execute("""SELECT votacion_id, bancada, voto, count(*) FROM voto_pleno_nominal
                                              WHERE voto IN ('SI', 'NO', 'ABST') GROUP BY 1, 2, 3"""):
            cuenta.setdefault((vid, b), {})[voto] = n
        mayoria = {}
        for k, c in cuenta.items():
            top = sorted(c.values(), reverse=True)
            if len(top) == 1 or top[0] > top[1]:  # empate: no hay mayoria, no cuenta
                mayoria[k] = max(c, key=c.get)
        lista_votos = [{"fecha": v["fecha"], "asunto": (v["asunto"] or "")[:240], "voto": v["voto"],
                        "pl": f"{v['pley_num']}" if v["pley_num"] else None,
                        "contra_bancada": v["voto"] in _POSTURAS and mayoria.get((v["id"], v["bancada"])) not in (None, v["voto"])}
                       for v in reversed(votos)]
        d = next((x for x in disciplina(pe, camara) if clave_congresista(x["camara"], x["congresista"]) == ident), None)
        mesas = [{"fecha": f, "titulo": t, "url": u} for f, t, u, c in pe.execute(
                    "SELECT fecha, titulo, url, congresista FROM mesas_tecnicas WHERE congresista IS NOT NULL ORDER BY fecha DESC")
                 if ap in norm(c)][:15]
        resumen = {"votaciones": len(votos), "ausencias": sum(v["voto"] not in _POSTURAS for v in votos),
                   "pct_alineado": d["pct_alineado"] if d else None,
                   "bancada": votos[-1]["bancada"] if votos else None}
    else:
        ap = ident.split(":", 1)[1]
        pls = []
        for pl, t, e, f, nombre, orden in ec.execute(
                """SELECT x.n_tramite, x.titulo, x.estado, x.fec_presentacion, p.nombre, p.orden FROM proponentes p
                   JOIN proyectos x ON x.n_tramite = p.n_tramite WHERE x.periodo = ? ORDER BY x.fec_presentacion DESC""",
                (PERIODO_EC,)):
            if apellidos("EC", nombre) == ap:
                pls.append({"pl": pl, "titulo": t, "estado": e, "fecha": (f or "")[:10], "bancada": None, "primero": orden in (0, 1)})
        lista_votos, mesas = [], []
        resumen = {"votaciones": None, "ausencias": None, "pct_alineado": None, "bancada": None}
    for p in pls:
        p["seguido"] = f"{pais}:{p['pl']}" in seguidos
    return {**resumen, "pls": pls, "votos": lista_votos, "mesas": mesas, "sesiones": _sesiones(pe, pais, ap)}


if __name__ == "__main__":  # chequeo sobre una base minima en memoria
    pe = sqlite3.connect(":memory:")
    pe.executescript("""
        CREATE TABLE votacion_pleno (id INT, camara TEXT, fecha TEXT, hora TEXT, tipo TEXT, asunto TEXT, pl_cod_tipo_parl TEXT, pley_num INT);
        CREATE TABLE voto_pleno_nominal (votacion_id INT, congresista TEXT, bancada TEXT, voto TEXT);
        INSERT INTO votacion_pleno VALUES (1,'senado','2026-10-01','10','votacion','PL 5',NULL,5);
        INSERT INTO voto_pleno_nominal VALUES (1,'MATUTE CHARUN, SUSANA','APP','NO'),(1,'MATUTE CHARUN, S','APP','NO'),
          (1,'PEREZ, A','APP','NO'),(1,'LOPEZ, B','APP','SI');
        CREATE TABLE proyectos (per_par_id INT, proyecto_ley TEXT, titulo TEXT, estado TEXT, fec_presentacion TEXT, grupo_parlamentario TEXT, autores_raw TEXT);
        INSERT INTO proyectos VALUES (2026,'00001-2026-2031-CS','Ley A','En comision','2026-09-01','APP','Matute Charún, Susana; Pérez, Ana'),
          (2026,'00002-2026-2031-CS','Ley B','En comision','2026-09-02','APP','Pérez, Ana; Matute Rojas, Luis');
        CREATE TABLE mesas_tecnicas (fecha TEXT, titulo TEXT, url TEXT, congresista TEXT);
        INSERT INTO mesas_tecnicas VALUES ('2026-10-02','Mesa X','u','Senadora Susana Matute Charún');
        CREATE TABLE sesiones_transcripciones (video_id TEXT, tipo TEXT, titulo TEXT, fecha TEXT, texto TEXT);
        INSERT INTO sesiones_transcripciones VALUES ('v1','Comision: Salud','S','2026-10-03','Tiene la palabra la senadora Matúte para su pregunta.'),('v3','Comision: Salud','S','2026-10-05','Senador Ruiz, presente. Senadora Matute, presente. Senador Paz, presente.'),
          ('v2','Comision: Salud','S','2026-10-04','El señor Matute de la empresa.');
    """)
    ec = sqlite3.connect(":memory:")
    ec.executescript("""CREATE TABLE proyectos (n_tramite TEXT, titulo TEXT, estado TEXT, fec_presentacion TEXT, periodo TEXT);
        CREATE TABLE proponentes (n_tramite TEXT, nombre TEXT, tipo TEXT, orden INT);""")
    f = ficha(pe, ec, "PE", "senado:matute charun", {"PE:00001-2026-2031-CS"})
    assert [p["pl"] for p in f["pls"]] == ["00001-2026-2031-CS"] and f["pls"][0]["seguido"] and f["pls"][0]["primero"], f["pls"]
    assert f["votos"][0]["contra_bancada"] is False and f["mesas"] and [s["video_id"] for s in f["sesiones"]] == ["v1"], f
    print("ok")
