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
from scraper.categorias import classify

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


_HOMONIMOS_EC = {"jaramillo zurita"}  # Lucia y Paola, hermanas y ambas asambleistas


def id_ec(nombre: str) -> str:
    """'EC:<dos apellidos>'; si dos asambleistas los comparten, se suma el primer nombre."""
    ap = apellidos("EC", nombre)
    return "EC:" + (" ".join(norm(nombre).split()[:3]) if ap in _HOMONIMOS_EC else ap)


def _patron(ap: str) -> re.Pattern:
    primero = re.escape(ap.split()[0])
    return re.compile(rf"\b{re.escape(ap)}\b|\b{_TITULO}\s+(?:\w+\s+){{0,3}}?{primero}\b")


def _sesiones(pe: sqlite3.Connection, pais: str, ap: str, contexto: bool = False) -> list[dict]:
    """contexto: suma tramos largos (lo que dijo tras darle la palabra) para que Gemini los lea."""
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
                       **({"contexto": [base[max(0, m.start() - 300):m.end() + 2200] for m in mejores]} if contexto else {}),
                       "url": url_video(vid) if pais == "EC" else f"https://www.youtube.com/watch?v={vid}"})
        if len(salida) == MAX_SESIONES:
            break
    return salida


def _mayoria(votos: dict, de: list[str]) -> str | None:
    """Postura de la mayoria de `de` en una votacion; None si empatan o nadie voto."""
    c: dict[str, int] = {}
    for i in de:
        if votos.get(i) in _POSTURAS:
            c[votos[i]] = c.get(votos[i], 0) + 1
    top = sorted(c.values(), reverse=True)
    return max(c, key=c.get) if top and (len(top) == 1 or top[0] > top[1]) else None


def _votos_ec(ident: str, votaciones: list[dict] | None = None, bancadas: dict[str, str] | None = None) -> tuple[list, dict]:
    """Votos de un asambleista (consultas/votos_ec) y cuanto vota con su bancada."""
    if votaciones is None:
        from consultas.integrantes import integrantes
        from consultas.votos_ec import votaciones as _v
        from consultas.votos_ec_comisiones import votaciones as _c
        # Pleno (Observatorio) y comisiones (PDF de la Asamblea), por fecha
        comisiones = [{**v, "asunto": f"{v['comision']} · {v['asunto']}"} for v in _c()]
        votaciones = sorted(_v() + comisiones, key=lambda v: v["fecha"])
        bancadas = {m["id"]: m["bancada"] for m in integrantes() if m["pais"] == "EC"}
    b = bancadas.get(ident)
    companeros = [i for i, x in bancadas.items() if x == b and i != ident] if b and b != "Sin bancada" else []
    lista, iguales, con_postura = [], 0, 0
    for v in reversed(votaciones):
        if ident not in v["votos"]:
            continue
        mio, may = v["votos"][ident], _mayoria(v["votos"], companeros)
        if mio in _POSTURAS and may:
            con_postura += 1
            iguales += mio == may
        lista.append({"fecha": v["fecha"], "asunto": v["asunto"][:240], "voto": mio, "tema": classify(v["asunto"]), "pl": None,
                      "contra_bancada": mio in _POSTURAS and may not in (None, mio)})
    return lista, {"votaciones": len(lista), "ausencias": sum(x["voto"] not in _POSTURAS for x in lista),
                   "pct_alineado": round(100 * iguales / con_postura) if con_postura else None, "bancada": b}


def ficha(pe: sqlite3.Connection, ec: sqlite3.Connection, pais: str, ident: str, seguidos: set[str]) -> dict:
    """ident: el id de personas(). seguidos: claves 'PAIS:pl' de alerts.pls_seguidos."""
    if pais == "PE":
        camara, ap = ident.split(":", 1)
        rx = re.compile(rf"(?:^|;)\s*{re.escape(ap)}\s*,")
        pls = [{"pl": pl, "titulo": t, "estado": e, "fecha": (f or "")[:10], "bancada": g, "primero": norm(a).startswith(ap), "tema": tm}
               for pl, t, e, f, g, a, tm in pe.execute(
                   """SELECT proyecto_ley, titulo, estado, fec_presentacion, grupo_parlamentario, autores_raw, tema
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
        lista_votos = [{"fecha": v["fecha"], "asunto": (v["asunto"] or "")[:240], "voto": v["voto"], "tema": classify(v["asunto"]),
                        "pl": f"{v['pley_num']}" if v["pley_num"] else None,
                        "contra_bancada": v["voto"] in _POSTURAS and mayoria.get((v["id"], v["bancada"])) not in (None, v["voto"])}
                       for v in reversed(votos)]
        d = next((x for x in disciplina(pe, camara) if clave_congresista(x["camara"], x["congresista"]) == ident), None)
        resumen = {"votaciones": len(votos), "ausencias": sum(v["voto"] not in _POSTURAS for v in votos),
                   "pct_alineado": d["pct_alineado"] if d else None,
                   "bancada": votos[-1]["bancada"] if votos else None}
    else:
        ap = " ".join(ident.split(":", 1)[1].split()[:2])
        pls = []
        for pl, t, e, f, nombre, orden, tm in ec.execute(
                """SELECT x.n_tramite, x.titulo, x.estado, x.fec_presentacion, p.nombre, p.orden, x.tema FROM proponentes p
                   JOIN proyectos x ON x.n_tramite = p.n_tramite WHERE x.periodo = ? ORDER BY x.fec_presentacion DESC""",
                (PERIODO_EC,)):
            if id_ec(nombre) == ident:
                pls.append({"pl": pl, "titulo": t, "estado": e, "fecha": (f or "")[:10], "bancada": None, "primero": orden in (0, 1), "tema": tm})
        lista_votos, resumen = _votos_ec(ident)
    for p in pls:
        p["seguido"] = f"{pais}:{p['pl']}" in seguidos
    # lo que dijo en las sesiones va aparte (consultas/posturas.dijo): leerlo tarda
    return {**resumen, "pls": pls, "votos": lista_votos}


def por_tema(pe: sqlite3.Connection, ec: sqlite3.Connection, pais: str, camara: str, q: str,
             miembros: list[dict]) -> dict:
    """Que se voto y quien presento proyectos sobre `q` (palabras o un tema de
    scraper/categorias) en una camara. miembros: los de integrantes() de esa camara.
    votaciones[i].votos va por id de persona ('senado:matute charun') para pintar el hemiciclo."""
    palabras = norm(q).split()
    def toca(texto: str | None, tema: str | None = None) -> bool:
        return bool(palabras) and (tema == q or all(w in norm(texto or "") for w in palabras))
    votaciones = []
    if pais == "PE":
        filas = pe.execute("""SELECT id, fecha, asunto FROM votacion_pleno WHERE tipo = 'votacion' AND camara = ?
                              ORDER BY fecha DESC, hora DESC""", (camara,)).fetchall()
        elegidas = [r for r in filas if toca(r[2], classify(r[2]))][:20]
        for vid, fecha, asunto in elegidas:
            votos = {clave_congresista(camara, n): v for n, v in pe.execute(
                "SELECT congresista, voto FROM voto_pleno_nominal WHERE votacion_id = ?", (vid,))}
            votaciones.append({"fecha": fecha, "asunto": (asunto or "")[:300], "votos": votos})
        sufijo = {"senado": "S", "diputados": "CD"}[camara]
        pls = [(pl, t, f, a) for pl, t, f, a, tm in pe.execute(
            "SELECT proyecto_ley, titulo, fec_presentacion, autores_raw, tema FROM proyectos WHERE per_par_id = ? AND proyecto_ley LIKE ?",
            (PER_PE, f"%-{sufijo}")) if toca(t, tm)]
        autores = lambda a: [apellidos("PE", x) for x in (a or "").split(";") if x.strip()]  # noqa: E731
    else:
        props: dict[str, list[str]] = {}
        for n, nombre in ec.execute("SELECT n_tramite, nombre FROM proponentes WHERE tipo = 'ASAMBLEÍSTA'"):
            props.setdefault(n, []).append(id_ec(nombre).split(":", 1)[1])
        pls = [(n, t, f, props.get(n, [])) for n, t, f, tm in ec.execute(
            "SELECT n_tramite, titulo, fec_presentacion, tema FROM proyectos WHERE periodo = ?", (PERIODO_EC,)) if toca(t, tm)]
        autores = lambda a: a  # noqa: E731
        from consultas.votos_ec import votaciones as votos_ec
        votaciones = [{"fecha": v["fecha"], "asunto": v["asunto"][:300], "votos": v["votos"]}
                      for v in reversed(votos_ec()) if toca(v["asunto"], classify(v["asunto"]))][:20]
    cuantos: dict[str, int] = {}
    for _, _, _, a in pls:
        for ap in set(autores(a)):
            cuantos[ap] = cuantos.get(ap, 0) + 1
    impulsan = sorted(({"id": m["id"], "n": cuantos[m["id"].split(":", 1)[1]]} for m in miembros
                       if cuantos.get(m["id"].split(":", 1)[1])), key=lambda x: -x["n"])
    return {"votaciones": votaciones, "impulsan": impulsan[:30], "proyectos": len(pls),
            "ejemplos": [{"pl": pl, "titulo": t, "fecha": (f or "")[:10]} for pl, t, f, _ in sorted(pls, key=lambda x: x[2] or "", reverse=True)[:8]]}


if __name__ == "__main__":  # chequeo sobre una base minima en memoria
    pe = sqlite3.connect(":memory:")
    pe.executescript("""
        CREATE TABLE votacion_pleno (id INT, camara TEXT, fecha TEXT, hora TEXT, tipo TEXT, asunto TEXT, pl_cod_tipo_parl TEXT, pley_num INT);
        CREATE TABLE voto_pleno_nominal (votacion_id INT, congresista TEXT, bancada TEXT, voto TEXT);
        INSERT INTO votacion_pleno VALUES (1,'senado','2026-10-01','10','votacion','PL 5',NULL,5);
        INSERT INTO voto_pleno_nominal VALUES (1,'MATUTE CHARUN, SUSANA','APP','NO'),(1,'MATUTE CHARUN, S','APP','NO'),
          (1,'PEREZ, A','APP','NO'),(1,'LOPEZ, B','APP','SI');
        CREATE TABLE proyectos (per_par_id INT, proyecto_ley TEXT, titulo TEXT, estado TEXT, fec_presentacion TEXT, grupo_parlamentario TEXT, autores_raw TEXT, tema TEXT);
        INSERT INTO proyectos VALUES (2026,'00001-2026-2031-CS','Ley A','En comision','2026-09-01','APP','Matute Charún, Susana; Pérez, Ana', 'Otros'),
          (2026,'00002-2026-2031-CS','Ley B','En comision','2026-09-02','APP','Pérez, Ana; Matute Rojas, Luis', 'Otros');
        CREATE TABLE mesas_tecnicas (fecha TEXT, titulo TEXT, url TEXT, congresista TEXT);
        INSERT INTO mesas_tecnicas VALUES ('2026-10-02','Mesa X','u','Senadora Susana Matute Charún');
        CREATE TABLE sesiones_transcripciones (video_id TEXT, tipo TEXT, titulo TEXT, fecha TEXT, texto TEXT);
        INSERT INTO sesiones_transcripciones VALUES ('v1','Comision: Salud','S','2026-10-03','Tiene la palabra la senadora Matúte para su pregunta.'),('v3','Comision: Salud','S','2026-10-05','Senador Ruiz, presente. Senadora Matute, presente. Senador Paz, presente.'),
          ('v2','Comision: Salud','S','2026-10-04','El señor Matute de la empresa.');
    """)
    ec = sqlite3.connect(":memory:")
    ec.executescript("""CREATE TABLE proyectos (n_tramite TEXT, titulo TEXT, estado TEXT, fec_presentacion TEXT, periodo TEXT, tema TEXT);
        CREATE TABLE proponentes (n_tramite TEXT, nombre TEXT, tipo TEXT, orden INT);""")
    f = ficha(pe, ec, "PE", "senado:matute charun", {"PE:00001-2026-2031-CS"})
    assert [p["pl"] for p in f["pls"]] == ["00001-2026-2031-CS"] and f["pls"][0]["seguido"] and f["pls"][0]["primero"], f["pls"]
    assert f["votos"][0]["contra_bancada"] is False, f
    assert [s["video_id"] for s in _sesiones(pe, "PE", "matute charun", contexto=True)] == ["v1"]
    t = por_tema(pe, ec, "PE", "senado", "pl 5", [{"id": "senado:matute charun"}, {"id": "senado:perez"}])
    assert t["votaciones"][0]["votos"]["senado:matute charun"] == "NO", t
    t = por_tema(pe, ec, "PE", "senado", "ley", [{"id": "senado:matute charun"}, {"id": "senado:perez"}])
    assert t["proyectos"] == 0 and t["impulsan"] == [], t  # los PL de prueba son -CS, no -S
    vs = [{"fecha": "2026-01-01", "asunto": "Ley A", "votos": {"EC:a b": "NO", "EC:c d": "SI", "EC:e f": "SI", "EC:g h": None}}]
    lista, r = _votos_ec("EC:a b", vs, {"EC:a b": "ADN", "EC:c d": "ADN", "EC:e f": "ADN", "EC:g h": "RC"})
    assert lista[0]["contra_bancada"] and r["pct_alineado"] == 0 and r["votaciones"] == 1, (lista, r)
    print("ok")
