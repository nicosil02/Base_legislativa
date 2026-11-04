"""Que piensa cada quien, leido por Gemini en las sesiones transcritas.

dijo():   la postura de un congresista en cada sesion donde hablo.
debate(): quien hablo de un proyecto cuando se sustento o debatio, con su bancada.

Las transcripciones no dicen quien habla: Gemini lo deduce de "tiene la palabra
el congresista X". Lo leido se guarda en data/posturas.json (GitHub, ver
core/store) para no volver a pagarlo; una sesion ya leida no cambia.
"""
from __future__ import annotations

import json
import re
import sqlite3

from consultas.personas import _sesiones, apellidos, id_ec
from core import llm, store
from core.text import norm

PATH = "data/posturas.json"
POSTURAS = ["a favor", "en contra", "con observaciones", "pregunta o pide información", "propone", "neutral", "solo lo mencionan"]

_ESQ_DIJO = {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "tema": {"type": "string"}, "postura": {"type": "string", "enum": POSTURAS},
    "piensa": {"type": "string"}}, "required": ["i", "tema", "postura", "piensa"]}}
_ESQ_DEBATE = {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "orador": {"type": "string"}, "rol": {"type": "string"},
    "postura": {"type": "string", "enum": POSTURAS[:6]}, "dijo": {"type": "string"}},
    "required": ["i", "orador", "rol", "postura", "dijo"]}}

_COMUN = """Las transcripciones son automaticas y no marcan quien habla. Quien preside da la palabra
("tiene la palabra el congresista X", "adelante asambleista X"); lo que sigue es de esa persona hasta que
se da la palabra a otra. El texto puede venir sin tildes: tu respuesta va en espanol llano CON tildes y
ortografia normal, en tercera persona, sin adornos ni dos puntos.
Cuenta solo lo que la persona dijo, sin inventar ni completar."""

PROMPT_DIJO = _COMUN + """

Para cada sesion numerada, lee los fragmentos donde aparece {nombre} y responde
- tema: de que se discutia, en menos de 12 palabras
- postura: que posicion tomo {nombre} sobre ese tema. "solo lo mencionan" si no habla en el fragmento
- piensa: una o dos oraciones con lo que piensa o pidio, concreto (cifras, entidades, proyectos)

{sesiones}"""

PROMPT_DEBATE = _COMUN + """

Proyecto: {titulo}

Para cada sesion numerada, identifica a cada persona que habla SOBRE ESTE PROYECTO (autor que lo sustenta,
congresistas, ministros o invitados). Si en una sesion no se trata este proyecto, no devuelvas nada de ella.
- orador: nombre o apellido como se dice en la sesion
- rol: autor, presidente de la comision, congresista, ministro, invitado...
- postura: su posicion sobre el proyecto
- dijo: una o dos oraciones con lo que planteo

{sesiones}"""


def _guardado() -> dict:
    return store.cargar(PATH, {}, ttl=120)


def _guardar(nuevo: dict) -> None:
    if nuevo:
        store.actualizar(PATH, lambda d: {**d, **nuevo}, f"posturas: {len(nuevo)} lecturas", {})


def _gemini(prompt: str, esquema: dict) -> list[dict] | None:
    if not llm.disponible():
        return None
    try:
        return json.loads(llm.generar(prompt, modelo=llm.LITE, json=True, schema=esquema) or "[]")
    except Exception as e:  # sin cupo o respuesta rota: se muestran los fragmentos sin leer
        print(f"[posturas] {e}")
        return None


def dijo(pe: sqlite3.Connection, pais: str, ident: str, nombre: str) -> dict:
    """{sesiones: [...con tema, postura, piensa si Gemini las leyo], mesas: [...]}"""
    ap = ident.split(":", 1)[1] if pais == "PE" else " ".join(ident.split(":", 1)[1].split()[:2])
    ses = _sesiones(pe, pais, ap, contexto=True)
    ya = _guardado()
    faltan = [s for s in ses if f"{ident}|{s['video_id']}" not in ya]
    nuevo = {}
    if faltan:
        texto = "\n\n".join(f"[{i}] {s['fecha']} {s['titulo']}\n" + "\n...\n".join(s["contexto"]) for i, s in enumerate(faltan, 1))
        for r in _gemini(PROMPT_DIJO.format(nombre=nombre, sesiones=texto), _ESQ_DIJO) or []:
            if 1 <= r.get("i", 0) <= len(faltan):
                nuevo[f"{ident}|{faltan[r['i'] - 1]['video_id']}"] = {k: r[k] for k in ("tema", "postura", "piensa")}
        _guardar(nuevo)
    for s in ses:
        s.pop("contexto")
        s.update(ya.get(f"{ident}|{s['video_id']}") or nuevo.get(f"{ident}|{s['video_id']}") or {})
    mesas = []
    if pais == "PE":
        mesas = [{"fecha": f, "titulo": t, "url": u} for f, t, u, c in pe.execute(
                    "SELECT fecha, titulo, url, congresista FROM mesas_tecnicas WHERE congresista IS NOT NULL ORDER BY fecha DESC")
                 if ap in norm(c)][:15]
    return {"sesiones": ses, "mesas": mesas}


_RX_PL = r"proyectos? de (?:ley|resoluci\w+ legislativa)\s*(?:n[uú]mero|n\.?\s*°?|nro\.?)?\s*{n}\b"


def _ventana(texto: str, num: str | None, titulo: str) -> str | None:
    """El tramo de la sesion donde se trata el proyecto: donde se dice su numero o,
    si no, donde mas se repiten las palabras largas de su titulo."""
    m = re.search(_RX_PL.format(n=re.escape(num)), texto, re.I) if num else None
    if m:
        ini = m.start()
    else:
        pal = {w for w in norm(titulo).split() if len(w) >= 7}
        plano = norm(texto)
        mejor = max(range(0, max(1, len(plano) - 3000), 1500), key=lambda i: sum(w in plano[i:i + 3000] for w in pal), default=0)
        if len(pal) < 2 or sum(w in plano[mejor:mejor + 3000] for w in pal) < min(3, len(pal)):
            return None
        ini = mejor
    return texto[max(0, ini - 1500):ini + 14000]


def _bancada(orador: str, gente: list[tuple[str, dict]]) -> dict | None:
    """Miembro (de pares (apellidos, miembro)) cuyo apellido se dice; None si no hay uno
    solo (ministro, invitado, apellido repetido)."""
    pal = set(norm(orador).split())
    for minimo in (2, 1):
        c = [p for ap, p in gente if len(pal & set(ap.split())) >= minimo]
        if len(c) == 1:
            return c[0]
    return None


def debate(pe: sqlite3.Connection, ec: sqlite3.Connection, pais: str, pl: str, gente: list[dict]) -> list[dict]:
    """[{fecha, organo, url, orador, rol, postura, dijo, bancada, id}] de las sesiones transcritas
    en que se trato el proyecto, de la mas nueva a la mas vieja."""
    from congreso_live.facebook_ec import url_video
    clave = f"debate|{pais}:{pl}"
    if pais == "PE":
        fila = pe.execute("SELECT pley_num, per_par_id, titulo, fec_presentacion FROM proyectos WHERE proyecto_ley = ?", (pl,)).fetchone()
        if not fila:
            return []
        num, per, titulo, desde = str(fila[0]), fila[1], fila[2] or "", (fila[3] or "")[:10]
        agenda = {(f[:10], norm(c).split()[0]) for f, c in pe.execute(
            """SELECT s.fecha, s.nombre_comision FROM sesion_pl_referenciado r JOIN sesiones s ON s.id_sesion = r.id_sesion
               WHERE r.pley_num = ? AND r.per_par_id = ?""", (fila[0], per)) if c}
        filtro = "NOT LIKE '%(EC)'"
    else:
        fila = ec.execute("SELECT titulo, fec_presentacion FROM proyectos WHERE n_tramite = ?", (pl,)).fetchone()
        if not fila:
            return []
        num, titulo, desde = None, fila[0] or "", (fila[1] or "")[:10]
        agenda = {((f or "")[:10], norm(c).split()[0]) for f, c in ec.execute(
            """SELECT s.fecha, s.nombre_comision FROM sesion_ec_pl_referenciado r JOIN sesiones_ec s ON s.uid = r.uid
               WHERE r.n_tramite = ?""", (pl,)) if c}
        filtro = "LIKE '%(EC)'"
    candidatas = []
    for vid, tipo, tit, fecha, texto in pe.execute(
            f"""SELECT video_id, tipo, titulo, fecha, texto FROM sesiones_transcripciones
                WHERE tipo {filtro} AND tipo NOT LIKE 'Entrevista:%' AND fecha >= ? ORDER BY fecha DESC""", (desde,)):
        organo = norm(tipo.split(":", 1)[-1].replace("(EC)", ""))
        en_agenda = any(f == fecha and (w in organo or "pleno" in organo) for f, w in agenda)
        if not (en_agenda or (num and re.search(_RX_PL.format(n=num), texto or "", re.I))):
            continue
        v = _ventana(texto or "", num, titulo)
        if v:
            candidatas.append({"video_id": vid, "fecha": fecha, "organo": tipo.replace(" (EC)", ""), "titulo": tit, "texto": v,
                               "url": url_video(vid) if pais == "EC" else f"https://www.youtube.com/watch?v={vid}"})
        if len(candidatas) == 4:
            break
    if not candidatas:
        return []
    ya = _guardado().get(clave)
    leidas = {x["video_id"] for x in ya["sesiones"]} if ya else set()
    if not ya or {c["video_id"] for c in candidatas} - leidas:
        texto = "\n\n".join(f"[{i}] {c['fecha']} {c['titulo']}\n{c['texto']}" for i, c in enumerate(candidatas, 1))
        r = _gemini(PROMPT_DEBATE.format(titulo=titulo, sesiones=texto), _ESQ_DEBATE)
        if r is None:
            return []
        ya = {"sesiones": [{k: c[k] for k in ("video_id", "fecha", "organo", "url")} for c in candidatas],
              "dichos": [x for x in r if 1 <= x.get("i", 0) <= len(candidatas)]}
        _guardar({clave: ya})
    pares = [(apellidos(pais, p["nombre"]) if pais == "PE" else id_ec(p["nombre"])[3:], p) for p in gente if p["pais"] == pais]
    out = []
    for x in ya["dichos"]:
        s, m = ya["sesiones"][x["i"] - 1], _bancada(x["orador"], pares)
        out.append({**{k: s[k] for k in ("fecha", "organo", "url")}, **{k: x[k] for k in ("orador", "rol", "postura", "dijo")},
                    "bancada": m["bancada"] if m else None, "id": m["id"] if m else None, "nombre": m["nombre"] if m else None})
    return out


if __name__ == "__main__":
    t = "x " * 900 + "Pasamos al proyecto de ley número 230 que propone la ley de agua potable rural" + " y" * 50
    assert _ventana(t, "230", "").strip().startswith("x x") and "230" in _ventana(t, "230", "")
    assert _ventana("nada que ver " * 400, None, "Ley que promueve la inversión hidráulica agraria") is None
    g = [("flores ruiz", {"id": "a"}), ("flores vilchez", {"id": "b"}), ("matute charun", {"id": "c"})]
    assert _bancada("congresista Matute", g)["id"] == "c" and _bancada("Flores", g) is None and _bancada("Víctor Flores Ruiz", g)["id"] == "a"
    print("ok")
