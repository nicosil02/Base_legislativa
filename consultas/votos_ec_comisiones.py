"""Votos nominales de las comisiones de la Asamblea de Ecuador (periodo 2025-2027).

Cada comision publica un PDF por sesion con el registro de votacion en
asambleanacional.gob.ec/es/comisiones/Votaciones-... (el listado y los PDF se bajan
sin navegador). Cada comision arma el PDF a su manera (reporte del sistema, tabla
con X, memo con adjuntos), asi que el texto lo lee Gemini (lite) y solo se guarda
una votacion si sus votos suman lo que el mismo PDF certifica.

    python -m consultas.votos_ec_comisiones   # lee los PDF nuevos (refrescar-pe, una vez al dia)
"""
from __future__ import annotations

import json
import re

from core import llm, store

PATH = "data/votos_ec_comisiones.json"
DESDE = "2025-05-14"
BASE = "https://www.asambleanacional.gob.ec/es/comisiones/"
COMISIONES = {  # slug del listado -> nombre
    "votaciones-comision-justicia-estructura-estado-2021-2025": "Comisión de Justicia y Estructura del Estado",
    "Votacion-Comision-del-Derecho-al-Trabajo-y-a-la-Seguridad-Social-2021-2025": "Comisión del Derecho al Trabajo y a la Seguridad Social",
    "Votacion-Comision-del-Regimen-Economico-y-Tributario-y-su-Regulacion-y-Control-2021-2025": "Comisión de Régimen Económico y Tributario",
    "Votaciones-Comision-del-Desarrollo-Economico-Productivo-y-la-Microempresa-2021-2025": "Comisión de Desarrollo Económico",
    "Votaciones-Comision-Relaciones-Internacionales-y-Movilidad-Humana-2021-2025": "Comisión de Relaciones Internacionales y Movilidad Humana",
    "Votaciones-Comision-Biodiversidad-y-Recursos-Naturales-2021-2025": "Comisión de Biodiversidad y Recursos Naturales",
    "Votaciones-Comision-Soberania-Alimentaria-y-Desarrollo-del-Sector-Agropecuario-y-Pesquero-2021-2025": "Comisión de Soberanía Alimentaria",
    "Votaciones-Comision-Gobiernos-Autonomos-Descentralizacion-Competencias-Organizacion-Territorio-2021-2025": "Comisión de Gobiernos Autónomos",
    "Votaciones-Comision-Educacion-Cultura-Ciencia-Tecnologia-Innovacion-Saberes-Ancestrales-2021-2025": "Comisión de Educación y Cultura",
    "Votaciones-Comision-Derecho-Salud-y-Deporte-AN": "Comisión del Derecho a la Salud y Deporte",
    "Votaciones-Comision-Transparencia-Participacion-Ciudadana-Control-Social-AN": "Comisión de Transparencia y Participación Ciudadana",
    "Votaciones-Comision-Garantias-Constitucionales-Derechos-Humanos-Derechos-Colectivos-Intercultural-AN": "Comisión de Garantías Constitucionales",
    "Votaciones-Comision-Soberania-Integracion-Seguridad-Integral-AN": "Comisión de Soberanía y Seguridad Integral",
    "Votaciones-Comision-Proteccion-Integral-Ninas-Ninos-Adolescentes-AN": "Comisión de Niñas, Niños y Adolescentes",
    "Votaciones-Comision-Fiscalizacion-Control-Politico-AN": "Comisión de Fiscalización y Control Político",
}
VOTOS = ["SI", "NO", "ABST", "BLANCO", "AUSENTE"]
_ESQ = {"type": "array", "items": {"type": "object", "properties": {
    "mocion": {"type": "string"},
    "votos": {"type": "array", "items": {"type": "object", "properties": {
        "nombre": {"type": "string"}, "voto": {"type": "string", "enum": VOTOS}}, "required": ["nombre", "voto"]}},
    "certificado": {"type": "object", "properties": {k: {"type": "integer"} for k in ("si", "no", "abst", "blanco")}}},
    "required": ["mocion", "votos", "certificado"]}}
PROMPT = """Registro de votacion de una comision de la Asamblea Nacional de Ecuador ({comision}).
Lista cada votacion del documento (mocion, reconsideracion...):
- mocion: que se voto, en una oracion corta en espanol con tildes (por ejemplo "Aprobar el informe para
  primer debate del Proyecto de Ley Organica de ..."). Sin "Mociono" ni nombres de quien la presenta.
- votos: cada asambleista con su voto (SI, NO, ABST, BLANCO o AUSENTE), tal como figura en la tabla.
  En tablas con columnas A FAVOR / EN CONTRA / ABSTENCION / BLANCO la X marca la columna.
- certificado: los totales que el documento declara (a favor, en contra, abstenciones, blanco).
Si el documento no trae la lista nombre por nombre de una votacion, no la incluyas.

DOCUMENTO
{texto}"""


def listar(s) -> list[dict]:
    """[{comision, fecha, sesion, pdf}] del periodo actual, de todas las comisiones."""
    out = []
    for slug, comision in COMISIONES.items():
        primera = None
        for pg in range(30):
            h = s.get(BASE + slug, params={"page": pg}, timeout=60).text
            filas = []
            for f in re.findall(r"<tr.*?</tr>", h, re.S)[1:]:
                t, m = re.sub(r"<[^>]+>", " ", f).split(), re.search(r'href="([^"]+\.pdf)"', f)
                if t and m:
                    filas.append({"comision": comision, "fecha": t[0], "sesion": " ".join(t[1:])[:80], "pdf": m.group(1)})
            if not filas or filas[0] == primera:
                break
            primera = primera or filas[0]
            out += [x for x in filas if DESDE <= x["fecha"] <= "2027-12-31"]
            if all(x["fecha"] < DESDE for x in filas):
                break
    return out


def cuadra(v: dict) -> bool:
    """Los votos leidos suman lo que el PDF certifica (si no certifica nada, no se guarda)."""
    c = v.get("certificado") or {}
    if not any(c.values()):
        return False
    n = {k: sum(x["voto"] == k for x in v["votos"]) for k in VOTOS}
    return (n["SI"], n["NO"], n["ABST"], n["BLANCO"]) == (c.get("si", 0), c.get("no", 0), c.get("abst", 0), c.get("blanco", 0))


def leer(fila: dict, pdf: bytes, gente: list[tuple[str, dict]], generar=None) -> list[dict]:
    """Votaciones del PDF que cuadran, con los votos por id de asambleista."""
    import pymupdf

    from consultas.posturas import _miembro
    texto = "\n".join(p.get_text() for p in pymupdf.open(stream=pdf, filetype="pdf"))
    if len(texto) < 300:  # escaneado: no trae texto
        return []
    generar = generar or (lambda p: llm.generar(p, modelo=llm.LITE, json=True, schema=_ESQ))
    out = []
    for v in json.loads(generar(PROMPT.format(comision=fila["comision"], texto=texto[:60_000])) or "[]"):
        if not cuadra(v):
            continue
        votos = {}
        for x in v["votos"]:
            m = _miembro(x["nombre"], gente)
            if m:
                votos[m["id"]] = None if x["voto"] == "AUSENTE" else x["voto"]
        if len(votos) >= len(v["votos"]) - 1:  # a lo mas un nombre sin reconocer
            out.append({"fecha": fila["fecha"], "asunto": v["mocion"], "comision": fila["comision"], "url": fila["pdf"], "votos": votos})
    return out


def bajar(gente: list[dict], maximo: int = 60) -> int:
    """Lee los PDF que aun no estan en PATH y los guarda. Devuelve cuantas votaciones sumo."""
    from consultas.personas import id_ec
    from core.http import session
    s = session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    ya = store.cargar(PATH, {"leidos": [], "votaciones": []}, ttl=0)
    pares = [(id_ec(p["nombre"])[3:], p) for p in gente if p["pais"] == "EC"]
    # tope por corrida: cuida el cupo diario de Gemini (ver posturas.precalcular)
    faltan = sorted((f for f in listar(s) if f["pdf"] not in ya["leidos"]), key=lambda f: f["fecha"], reverse=True)[:maximo]
    print(f"[votos_ec_comisiones] {len(faltan)} PDF por leer", flush=True)
    total, nuevas, leidos = 0, [], []
    for i, fila in enumerate(faltan, 1):
        try:
            r = s.get(fila["pdf"], timeout=90)
            r.raise_for_status()
            nuevas += leer(fila, r.content, pares)
            leidos.append(fila["pdf"])
        except Exception as e:  # sin cupo o PDF roto: se reintenta manana
            print(f"[votos_ec_comisiones] {fila['pdf']}: {str(e)[:150]}", flush=True)
        if leidos and (len(leidos) >= 20 or i == len(faltan)):  # de a poco: si el timeout corta, lo leido queda
            store.actualizar(PATH, lambda d, l=leidos, n=nuevas: {
                "leidos": d.get("leidos", []) + l, "votaciones": sorted(d.get("votaciones", []) + n, key=lambda v: v["fecha"])},
                f"votos comisiones EC: {len(nuevas)} votaciones", {"leidos": [], "votaciones": []})
            total += len(nuevas)
            print(f"[votos_ec_comisiones] {i}/{len(faltan)} PDF, {total} votaciones", flush=True)
            nuevas, leidos = [], []
    return total


def votaciones() -> list[dict]:
    """Las votaciones guardadas (copia del repo), de la mas vieja a la mas nueva."""
    from core.db import ROOT
    p = ROOT / PATH
    return json.loads(p.read_text(encoding="utf-8"))["votaciones"] if p.exists() else []


if __name__ == "__main__":
    v = {"votos": [{"nombre": "a", "voto": "SI"}, {"nombre": "b", "voto": "NO"}, {"nombre": "c", "voto": "AUSENTE"}],
         "certificado": {"si": 1, "no": 1, "abst": 0, "blanco": 0}}
    assert cuadra(v) and not cuadra({**v, "certificado": {"si": 2, "no": 1}}) and not cuadra({**v, "certificado": {}})
    import sys
    if "probar" not in sys.argv:
        from consultas.integrantes import integrantes
        print("votaciones nuevas", bajar(integrantes()))
    print("ok")
