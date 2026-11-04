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
from scraper.categorias import CATEGORIAS

PATH = "data/posturas.json"
VERSION = "v2"  # cambia si cambia lo que se le pide a Gemini: lo viejo deja de servir
POSTURAS = ["a favor", "en contra", "con observaciones", "pregunta o pide información", "propone", "neutral", "solo lo mencionan"]
TEMAS = sorted(set(CATEGORIAS) - {"Transporte y telecomunicaciones", "Energía y minas", "Control de la actividad privada"}) + [
    "Seguridad y orden interno", "Justicia", "Política y control político", "Presupuesto y gasto público", "Otros"]

_ESQ_DIJO = {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "tema": {"type": "string", "enum": TEMAS}, "postura": {"type": "string", "enum": POSTURAS},
    "piensa": {"type": "string"}}, "required": ["i", "tema", "postura", "piensa"]}}
_ESQ_DEBATE = {"type": "array", "items": {"type": "object", "properties": {
    "i": {"type": "integer"}, "orador": {"type": "string"}, "rol": {"type": "string"},
    "postura": {"type": "string", "enum": POSTURAS[:6]}, "dijo": {"type": "string"}},
    "required": ["i", "orador", "rol", "postura", "dijo"]}}

_COMUN = """Las transcripciones son automaticas y no marcan quien habla. Quien preside da la palabra
("tiene la palabra el congresista X", "adelante asambleista X"); lo que sigue es de esa persona hasta que
se da la palabra a otra. El texto puede venir sin tildes ni enies: tu respuesta va en espanol con tildes,
enies y ortografia correctas (Comisión, Señaló, Niñez), en tercera persona, sin adornos ni dos puntos.
Cuenta solo lo que la persona dijo, sin inventar ni completar."""

PROMPT_DIJO = _COMUN + """

Para cada sesion numerada, lee los fragmentos donde aparece {nombre} y responde
- tema: la categoria que mejor describe lo que se discutia
- postura: que posicion tomo {nombre}. "solo lo mencionan" si no habla en el fragmento
- piensa: UNA oracion de menos de 20 palabras que empiece con un verbo en pasado (Defendió, Cuestionó,
  Pidió, Propuso, Criticó, Respaldó, Rechazó, Preguntó) y diga sobre qué, con lo concreto (cifra, entidad,
  proyecto). Ejemplo "Cuestionó el endeudamiento de 4428 millones para comprar aviones de guerra."

{sesiones}"""

PROMPT_DEBATE = _COMUN + """

Proyecto: {titulo}

Para cada sesion numerada, identifica a cada persona que habla SOBRE ESTE PROYECTO (autor que lo sustenta,
congresistas, ministros o invitados). Si en una sesion no se trata este proyecto, no devuelvas nada de ella.
- orador: nombre o apellido como se dice en la sesion
- rol: autor, presidente de la comision, congresista, ministro, invitado...
- postura: su posicion sobre el proyecto
- dijo: UNA oracion de menos de 25 palabras que empiece con un verbo en pasado (Defendió, Cuestionó, Pidió...)

{sesiones}"""

# "Comision: Energia Y Minas" -> "Comisión de Energía y Minas"
_TILDES = {"comision": "Comisión", "energia": "Energía", "economia": "Economía", "politico": "Político", "gestion": "Gestión",
           "constitucion": "Constitución", "etica": "Ética", "inclusion": "Inclusión", "educacion": "Educación",
           "produccion": "Producción", "fiscalizacion": "Fiscalización", "republica": "República", "camara": "Cámara",
           "agrario": "Agraria", "y": "y", "del": "del", "de": "de", "la": "la"}


def organo(tipo: str) -> str:
    t = tipo.replace(" (EC)", "")
    tipo_, _, nombre = t.partition(": ")
    nombre = " ".join(_TILDES.get(w.lower(), w) for w in nombre.split())
    if tipo_ == "Pleno":
        return {"Asamblea Nacional": "Pleno de la Asamblea", "Diputados": "Pleno de Diputados"}.get(nombre, f"Pleno del {nombre}")
    return nombre if nombre.lower().startswith(("mesa", "comisión", "sesión")) else f"Comisión de {nombre}"


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
    except Exception as e:  # sin cupo o respuesta rota: quedan los fragmentos sin leer
        print(f"[posturas] {e}")
        return None


def _ap(pais: str, ident: str) -> str:
    return ident.split(":", 1)[1] if pais == "PE" else " ".join(ident.split(":", 1)[1].split()[:2])


def _clave(ident: str, vid: str) -> str:
    return f"{VERSION}|{ident}|{vid}"


def leer(pe: sqlite3.Connection, pais: str, ident: str, nombre: str, ya: dict) -> dict:
    """Pasa por Gemini las sesiones de la persona que aun no estan en `ya`. Devuelve lo nuevo."""
    faltan = [s for s in _sesiones(pe, pais, _ap(pais, ident), contexto=True) if _clave(ident, s["video_id"]) not in ya]
    if not faltan:
        return {}
    texto = "\n\n".join(f"[{i}] {s['fecha']} {s['titulo']}\n" + "\n...\n".join(s["contexto"]) for i, s in enumerate(faltan, 1))
    return {_clave(ident, faltan[r["i"] - 1]["video_id"]): {k: r[k] for k in ("tema", "postura", "piensa")}
            for r in _gemini(PROMPT_DIJO.format(nombre=nombre, sesiones=texto), _ESQ_DIJO) or []
            if 1 <= r.get("i", 0) <= len(faltan)}


def precalcular(pe: str, gente: list[dict], hilos: int = 4) -> int:
    """Lee por adelantado lo nuevo de todos y lo guarda de una vez (un commit).
    Corre a diario en refrescar-pe.yml despues de bajar las transcripciones."""
    from concurrent.futures import ThreadPoolExecutor
    ya = dict(_guardado())

    def uno(p):
        nombre = " ".join(p["nombre"].split(",")[::-1]).strip() if p["pais"] == "PE" else p["nombre"]
        try:
            return leer(sqlite3.connect(pe), p["pais"], p["id"], nombre, ya)
        except Exception as e:
            print(f"[posturas] {p['id']}: {e}")
            return {}
    nuevo: dict = {}
    with ThreadPoolExecutor(hilos) as ex:
        for i, r in enumerate(ex.map(uno, gente), 1):
            nuevo.update(r)
            if i % 25 == 0:
                print(f"[posturas] {i}/{len(gente)} personas, {len(nuevo)} sesiones leidas")
    _guardar(nuevo)
    return len(nuevo)


def dijo(pe: sqlite3.Connection, pais: str, ident: str, nombre: str) -> dict:
    """{sesiones, mesas}. No llama a Gemini: lo ya leido sale de data/posturas.json; una
    sesion que aun no se leyo va con sus fragmentos y se lee en la corrida diaria."""
    ap = _ap(pais, ident)
    ya = _guardado()
    if not any(k.startswith(f"{VERSION}|{ident}|") for k in ya):
        # nadie la leyo todavia (antes de la primera corrida diaria): se lee ahora y queda guardada
        nuevo = leer(pe, pais, ident, nombre, ya)
        _guardar(nuevo)
        ya = {**ya, **nuevo}
    ses = _sesiones(pe, pais, ap)
    for s in ses:
        s["organo"] = organo(s["organo"])
        s.update(ya.get(_clave(ident, s["video_id"])) or {})
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
            candidatas.append({"video_id": vid, "fecha": fecha, "organo": organo(tipo), "titulo": tit, "texto": v,
                               "url": url_video(vid) if pais == "EC" else f"https://www.youtube.com/watch?v={vid}"})
        if len(candidatas) == 4:
            break
    if not candidatas:
        return []
    ya = _guardado().get(f"{VERSION}|{clave}")
    leidas = {x["video_id"] for x in ya["sesiones"]} if ya else set()
    if not ya or {c["video_id"] for c in candidatas} - leidas:
        texto = "\n\n".join(f"[{i}] {c['fecha']} {c['titulo']}\n{c['texto']}" for i, c in enumerate(candidatas, 1))
        r = _gemini(PROMPT_DEBATE.format(titulo=titulo, sesiones=texto), _ESQ_DEBATE)
        if r is None:
            return []
        ya = {"sesiones": [{k: c[k] for k in ("video_id", "fecha", "organo", "url")} for c in candidatas],
              "dichos": [x for x in r if 1 <= x.get("i", 0) <= len(candidatas)]}
        _guardar({f"{VERSION}|{clave}": ya})
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
    assert organo("Comision: Energia Y Minas") == "Comisión de Energía y Minas" and organo("Pleno: Senado") == "Pleno del Senado"
    assert organo("Comision: Derecho a la Salud (EC)") == "Comisión de Derecho a la Salud"
    import sys
    if "precalcular" in sys.argv:
        from consultas.integrantes import integrantes
        from core.db import ROOT
        print("leidas", precalcular(str(ROOT / "proyectos.db"), integrantes()))
    print("ok")
