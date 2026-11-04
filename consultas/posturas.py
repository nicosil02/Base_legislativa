"""Posturas en el Congreso: quien dijo que en cada sesion transcrita, leido por Gemini.

Cada sesion se lee UNA vez y de esa lectura salen todos los que hablaron, sobre que,
con que postura y si hablaban de un proyecto. De ahi salen:
  dijo():   las posturas de un congresista o asambleista (sin limite de sesiones)
  debate(): quien hablo de un proyecto cuando se sustento o debatio, por bancada
Ninguna de las dos llama a Gemini: solo leen lo guardado.

precalcular() lee las sesiones que faltan; corre en refrescar-pe.yml (13-14 y 23 UTC).
Se guarda por mes en data/posturas/AAAA-MM.json (core/store: commit en main), para
que ningun archivo pase el limite de 1 MB de la API de GitHub.
"""
from __future__ import annotations

import json
import re
import sqlite3

from consultas.personas import apellidos, id_ec
from core import llm, store
from core.text import norm
from scraper.categorias import CATEGORIAS

CARPETA = "data/posturas"
VERSION = 4  # sube si cambia lo que se le pide a Gemini: lo leido con otra version se vuelve a leer
DESDE = {"PE": "2026-07-26", "EC": "2025-05-14"}  # inicio de cada periodo
POSTURAS = ["a favor", "en contra", "con observaciones", "pregunta", "propone", "comenta"]
TEMAS = sorted(set(CATEGORIAS) - {"Transporte y telecomunicaciones", "Energía y minas", "Control de la actividad privada"}) + [
    "Seguridad y orden interno", "Justicia", "Política y control político", "Presupuesto y gasto público", "Otros"]

_ESQ = {"type": "array", "items": {"type": "object", "properties": {
    "orador": {"type": "string"}, "cargo": {"type": "string", "enum": ["legislador", "ministro o autoridad", "invitado"]},
    "sobre": {"type": "string"}, "postura": {"type": "string", "enum": POSTURAS},
    "tema": {"type": "string", "enum": TEMAS}, "dijo": {"type": "string"}, "proyecto": {"type": "string"}},
    "required": ["orador", "cargo", "sobre", "postura", "tema", "dijo", "proyecto"]}}

PROMPT = """Transcripción automática de una sesión del {lugar}: {titulo} ({fecha}).
No marca quién habla. Quien preside da la palabra ("tiene la palabra el congresista X", "adelante
asambleísta X", "senadora X, por favor"); lo que sigue es de esa persona hasta que se da la palabra a otra.
La transcripción puede venir sin tildes; tú escribes siempre con tildes y eñes correctas.

Lista cada intervención con contenido (una por persona y por asunto; ignora saludos, lista de asistencia,
votaciones nombre por nombre y frases de trámite de quien preside):
- orador: nombre y apellidos como se dicen en la sesión
- cargo: legislador (congresista, senador, diputado, asambleísta), ministro o autoridad, invitado
- sobre: el asunto concreto en menos de 8 palabras (un proyecto, un decreto, la gestión de un ministro,
  el presupuesto de un sector...)
- postura: su posición frente a "sobre"
  "a favor": lo apoya o lo defiende de forma explícita
  "en contra": lo rechaza, lo critica, lo cuestiona o denuncia un problema en él
  "con observaciones": lo apoya pero pide cambios o pone reparos
  "pregunta": solo pide información, sin juzgar
  "propone": plantea algo nuevo (una medida, un cambio, una citación)
  "comenta": informa o describe sin tomar posición
  Ejemplos: "Cuestionó la baja ejecución" es en contra. "Informó sobre la situación de Piura" es comenta.
  "Pidió citar al ministro" es propone.
- tema: la categoría del asunto (beneficios tributarios es Tributos, no Trabajo)
- dijo: UNA oración de menos de 22 palabras, en tercera persona, que empiece con un verbo en pasado
  (Defendió, Cuestionó, Pidió, Propuso, Rechazó, Preguntó, Denunció, Respaldó) y diga lo concreto
  (cifra, entidad, proyecto), con tildes: número, ejecución, aprobación, público
- proyecto: si habla de un proyecto de ley específico, su número ("PL 230") o su nombre corto; si no, ""

No inventes: si no se entiende quién habla, no lo incluyas.

TRANSCRIPCION
{texto}"""

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


def _miembro(orador: str, gente: list[tuple[str, dict]]) -> dict | None:
    """Miembro (de pares (apellidos, miembro)) cuyos apellidos se dicen; None si no hay uno
    solo (ministro, invitado, apellido repetido)."""
    pal = set(norm(orador).split())
    for minimo in (2, 1):
        c = [p for ap, p in gente if len(pal & set(ap.split())) >= minimo]
        if len(c) == 1:
            return c[0]
    return None


def _pares(gente: list[dict], pais: str, camara: str | None = None) -> list[tuple[str, dict]]:
    return [(apellidos(pais, p["nombre"]) if pais == "PE" else id_ec(p["nombre"])[3:], p)
            for p in gente if p["pais"] == pais and (not camara or p["camara"] == camara)]


def _camara(tipo: str) -> str | None:
    """Del Pleno se sabe la camara; una comision puede ser bicameral."""
    return {"Pleno: Senado": "senado", "Pleno: Diputados": "diputados"}.get(tipo)


# ---- guardado por mes ----
def _mes(fecha: str) -> str:
    return f"{CARPETA}/{fecha[:7]}.json"


_leido: dict = {}


def guardado() -> dict:
    """{video_id: sesion leida} de todos los meses. Lee la copia del repo (la app en la nube se
    actualiza con cada push a main); se relee solo si cambio algun archivo."""
    from core.db import ROOT
    archivos = sorted((ROOT / CARPETA).glob("*.json"))
    firma = tuple((a.name, a.stat().st_mtime_ns) for a in archivos)
    if _leido.get("firma") != firma:
        datos: dict = {}
        for a in archivos:
            datos.update(json.loads(a.read_text(encoding="utf-8")))
        _leido.update(firma=firma, datos=datos)
    return _leido["datos"]


def _guardar(nuevas: dict) -> None:
    por_mes: dict = {}
    for vid, s in nuevas.items():
        por_mes.setdefault(_mes(s["fecha"]), {})[vid] = s
    for path, xs in por_mes.items():
        store.actualizar(path, lambda d, xs=xs: {**d, **xs}, f"posturas: {len(xs)} sesiones leidas", {})


# ---- lectura con Gemini ----
def leer(vid: str, tipo: str, titulo: str, fecha: str, texto: str, gente: list[dict], generar=None) -> dict:
    """Una sesion leida: {fecha, organo, url, pais, v, dichos: [...]}. Los legisladores llevan su id."""
    from congreso_live.facebook_ec import url_video
    pais = "EC" if tipo.endswith("(EC)") else "PE"
    if generar is None:
        generar = lambda p: llm.generar(p, modelo=llm.LITE, json=True, schema=_ESQ, respaldo=False)  # gemma no aguanta sesiones largas
    lugar = "Asamblea Nacional de Ecuador" if pais == "EC" else "Congreso de Peru"
    crudo = json.loads(generar(PROMPT.format(lugar=lugar, titulo=titulo, fecha=fecha, texto=texto[:400_000])) or "[]")
    pares = _pares(gente, pais, _camara(tipo)) or _pares(gente, pais)
    dichos = []
    for x in crudo:
        m = _miembro(x["orador"], pares) if x.get("cargo") == "legislador" else None
        dichos.append({k: x.get(k, "") for k in ("orador", "cargo", "sobre", "postura", "tema", "dijo", "proyecto")}
                      | {"id": m["id"] if m else None})
    return {"fecha": fecha, "organo": organo(tipo), "pais": pais, "v": VERSION, "dichos": dichos,
            "url": url_video(vid) if pais == "EC" else f"https://www.youtube.com/watch?v={vid}"}


def precalcular(db: str, gente: list[dict], hilos: int = 3, maximo: int | None = None) -> int:
    """Lee las sesiones que faltan (o leidas con otra VERSION), de la mas nueva, y guarda de a 10.
    ponytail: el tope por corrida cuida el cupo gratis de flash-lite (500 al dia, compartido con
    toda la app); el atraso se pone al dia en unos dias. Con cupo pagado se puede quitar."""
    from concurrent.futures import ThreadPoolExecutor
    ya = guardado()
    c = sqlite3.connect(db)
    faltan = [r for r in c.execute(
        """SELECT video_id, tipo, titulo, fecha FROM sesiones_transcripciones
           WHERE tipo NOT LIKE 'Entrevista:%' AND length(texto) > 2000
             AND ((tipo LIKE '%(EC)' AND fecha >= ?) OR (tipo NOT LIKE '%(EC)' AND fecha >= ?))
           ORDER BY fecha DESC""", (DESDE["EC"], DESDE["PE"]))
              if (ya.get(r[0]) or {}).get("v") != VERSION][:maximo]
    print(f"[posturas] {len(faltan)} sesiones por leer", flush=True)

    def una(fila):
        vid, tipo, titulo, fecha = fila
        try:
            texto = sqlite3.connect(db).execute("SELECT texto FROM sesiones_transcripciones WHERE video_id = ?", (vid,)).fetchone()[0]
            return vid, leer(vid, tipo, titulo or "", fecha, texto, gente)
        except Exception as e:  # sin cupo o respuesta rota: se reintenta en la proxima corrida
            print(f"[posturas] {vid}: {str(e)[:150]}", flush=True)
            return vid, None
    total, lote = 0, {}
    with ThreadPoolExecutor(hilos) as ex:
        for i, (vid, s) in enumerate(ex.map(una, faltan), 1):
            if s:
                lote[vid] = s
            if len(lote) >= 10 or (i == len(faltan) and lote):  # de a poco: si el timeout corta, lo leido queda
                _guardar(lote)
                total += len(lote)
                lote = {}
                print(f"[posturas] {i}/{len(faltan)} sesiones, {total} guardadas", flush=True)
    return total


# ---- consultas (sin Gemini) ----
def dijo(pe: sqlite3.Connection, pais: str, ident: str, nombre: str = "") -> dict:
    """{sesiones: [{fecha, organo, url, sobre, postura, tema, piensa}], mesas: [...]}, de la mas nueva."""
    sesiones = []
    for vid, s in guardado().items():
        for x in s["dichos"]:
            if x.get("id") == ident:
                sesiones.append({"video_id": vid, "fecha": s["fecha"], "organo": s["organo"], "url": s["url"], "sobre": x["sobre"],
                                 "postura": x["postura"], "tema": x["tema"], "piensa": x["dijo"], "proyecto": x["proyecto"]})
    sesiones.sort(key=lambda x: x["fecha"], reverse=True)
    mesas = []
    if pais == "PE":
        ap = ident.split(":", 1)[1]
        mesas = [{"fecha": f, "titulo": t, "url": u} for f, t, u, c in pe.execute(
                    "SELECT fecha, titulo, url, congresista FROM mesas_tecnicas WHERE congresista IS NOT NULL ORDER BY fecha DESC")
                 if ap in norm(c)][:15]
    return {"sesiones": sesiones, "mesas": mesas}


def _es_el_proyecto(dicho: str, num: str | None, titulo: str) -> bool:
    """El 'proyecto' que anoto Gemini es este PL: por numero (PE) o por palabras del titulo (EC)."""
    if not dicho:
        return False
    if num:
        return len(num.lstrip("0")) >= 2 and num.lstrip("0") in {d.lstrip("0") for d in re.findall(r"\d+", dicho.replace(".", ""))}
    pal = {w for w in norm(titulo).split() if len(w) >= 6}
    return len(pal & set(norm(dicho).split())) >= min(3, max(2, len(pal) // 2))


def debate(pe: sqlite3.Connection, ec: sqlite3.Connection, pais: str, pl: str, gente: list[dict]) -> list[dict]:
    """[{fecha, organo, url, orador, rol, postura, dijo, bancada, id, nombre}] de quien hablo del
    proyecto en las sesiones leidas, de la mas nueva a la mas vieja."""
    if pais == "PE":
        fila = pe.execute("SELECT pley_num, titulo, fec_presentacion FROM proyectos WHERE proyecto_ley = ?", (pl,)).fetchone()
        num, titulo = (str(fila[0]), fila[1] or "") if fila else (None, "")
    else:
        fila = ec.execute("SELECT titulo, fec_presentacion FROM proyectos WHERE n_tramite = ?", (pl,)).fetchone()
        num, titulo = None, (fila[0] or "") if fila else ""
    if not fila:
        return []
    por_id = {p["id"]: p for p in gente}
    out = []
    for s in guardado().values():
        if s["pais"] != pais or s["fecha"] < (fila[-1] or "")[:10]:  # un numero de PL se repite entre periodos
            continue
        for x in s["dichos"]:
            if _es_el_proyecto(x["proyecto"], num, titulo):
                m = por_id.get(x["id"])
                out.append({"fecha": s["fecha"], "organo": s["organo"], "url": s["url"], "orador": x["orador"],
                            "rol": x["cargo"] if not m else "", "postura": x["postura"], "dijo": x["dijo"],
                            "bancada": m["bancada"] if m else None, "id": m["id"] if m else None, "nombre": m["nombre"] if m else None})
    return sorted(out, key=lambda x: x["fecha"], reverse=True)


if __name__ == "__main__":
    import sys
    g = [("flores ruiz", {"id": "a"}), ("flores vilchez", {"id": "b"}), ("matute charun", {"id": "c"})]
    assert _miembro("congresista Matute", g)["id"] == "c" and _miembro("Flores", g) is None and _miembro("Víctor Flores Ruiz", g)["id"] == "a"
    assert organo("Comision: Energia Y Minas") == "Comisión de Energía y Minas" and organo("Pleno: Senado") == "Pleno del Senado"
    assert organo("Comision: Derecho a la Salud (EC)") == "Comisión de Derecho a la Salud"
    assert _es_el_proyecto("PL 230", "230", "") and _es_el_proyecto("PL 00230-2026", "230", "") and not _es_el_proyecto("PL 2301", "230", "") and not _es_el_proyecto("", "230", "")
    assert _es_el_proyecto("Ley de Gestión Costera Integrada", None, "Ley Orgánica de Gestión Costera Integrada")
    gente = [{"pais": "PE", "camara": "senado", "id": "senado:matute charun", "nombre": "MATUTE CHARUN, SUSANA", "bancada": "FP"}]
    falso = lambda p: json.dumps([{"orador": "senadora Matute", "cargo": "legislador", "sobre": "PL 5", "postura": "a favor",
                                   "tema": "Salud", "dijo": "Defendió el PL 5.", "proyecto": "PL 5"},
                                  {"orador": "ministro Pérez", "cargo": "ministro o autoridad", "sobre": "x", "postura": "comenta",
                                   "tema": "Salud", "dijo": "Explicó.", "proyecto": ""}])
    s = leer("v1", "Pleno: Senado", "t", "2026-10-01", "texto", gente, falso)
    assert [d["id"] for d in s["dichos"]] == ["senado:matute charun", None] and s["organo"] == "Pleno del Senado", s
    if "precalcular" in sys.argv:
        from consultas.integrantes import integrantes
        from core.db import ROOT
        maximo = int(sys.argv[sys.argv.index("precalcular") + 1]) if len(sys.argv) > sys.argv.index("precalcular") + 1 else None
        print("leidas", precalcular(str(ROOT / "proyectos.db"), integrantes(), maximo=maximo))
    print("ok")
