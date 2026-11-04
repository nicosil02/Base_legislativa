"""Votos nominales de las comisiones de la Asamblea de Ecuador (periodo 2025-2027).

Cada comision publica un PDF por sesion con el registro de votacion en
asambleanacional.gob.ec/es/comisiones/Votaciones-... (el listado y los PDF se bajan
sin navegador). Casi todos adjuntan el reporte del sistema electronico ("Sesion Nro.",
mocion, "Votacion definitiva", totales y la lista Nro/Curul/Asambleista/Voto); la
Comision de Salud usa una tabla con X por columna. Las dos se leen con reglas, sin IA,
y solo se guarda una votacion si sus votos suman los totales del mismo PDF.

    python -m consultas.votos_ec_comisiones   # lee los PDF nuevos (refrescar-pe, una vez al dia)
"""
from __future__ import annotations

import json
import re

from core import store

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
_BLOQUE = re.compile(r"Sesi[oó]n Nro\.\s*\d+\s*\n(?P<mocion>.*?)\nVotaci[oó]n definitiva\s*\n[^\n]*\n\s*"
                     r"TOTAL\n\d+\nPRESENTE\n\d+\nAUSENTE\n\d+\nSI\n(?P<si>\d+)\nNO\n(?P<no>\d+)\n"
                     r"BLANCO\n(?P<blanco>\d+)\nABSTENCI[OÓ]N\n(?P<abst>\d+)\n", re.S)
_FILA = re.compile(r"\n\d+\n\d+\n([^\n\d]+?)\s*\n(SI|NO|ABSTENCI[OÓ]N|BLANCO|AUSENTE)\s*(?=\n|$)")
_COLS = (("FAVOR", "SI"), ("CONTRA", "NO"), ("ABSTENCI", "ABST"), ("BLANCO", "BLANCO"), ("AUSEN", "AUSENTE"))


def _limpia(m: str) -> str:
    m = re.sub(r"^\s*MOCI[OÓ]N\s*\d*\s*:\s*", "", re.sub(r"\s+", " ", m), flags=re.I).strip(' “”"')
    return m if len(m) <= 300 else m[:300].rsplit(" ", 1)[0] + "…"


def del_sistema(texto: str) -> list[dict]:
    """[{mocion, votos: [(nombre, voto)], certificado}] del reporte del sistema electronico.
    La lista puede seguir en la pagina siguiente: va hasta el proximo bloque."""
    bloques = list(_BLOQUE.finditer(texto))
    out = []
    for b, sig in zip(bloques, bloques[1:] + [None]):
        tramo = texto[b.end() - 1:sig.start() if sig else len(texto)]
        votos = [(n.strip(), "ABST" if v.startswith("ABST") else v) for n, v in _FILA.findall(tramo)]
        mocion = _limpia(b["mocion"])
        if out and len(mocion) < 30 and "RECONSIDERA" in mocion.upper():  # "Reconsideración" a secas
            mocion = f"Reconsideración de: {out[-1]['mocion']}"
        out.append({"mocion": mocion, "votos": votos,
                    "certificado": {k: int(b[k]) for k in ("si", "no", "abst", "blanco")}})
    return out


def de_tabla_x(doc) -> list[dict]:
    """Tabla con columnas A FAVOR / EN CONTRA / ... y una X por fila (Comision de Salud).
    La columna sale de la posicion de la X bajo cada encabezado; los totales, de la fila TOTAL."""
    out, cols, actual, mocion = [], {}, None, ""
    for p in doc:
        lineas: dict = {}
        for x0, y0, x1, y1, w, *_ in p.get_text("words"):
            lineas.setdefault(round(y0 / 4), []).append((x0, x1, w))
        # las X letra por letra: a veces vienen pegadas al nombre ("JOSEBETHX")
        equis = [(ch["bbox"][1] / 4, ch["bbox"][0]) for b in p.get_text("rawdict")["blocks"] for ln in b.get("lines", [])
                 for sp in ln["spans"] for ch in sp["chars"] if ch["c"] in "Xx"]
        filas = []  # (y, nombre, bloque) de esta pagina; la X se empareja al final
        for y, ws in sorted(lineas.items()):
            ws.sort()
            txt = " ".join(w for *_, w in ws)
            up = txt.upper()
            if up.startswith(("MOCIÓN", "MOCION")):
                mocion = txt.split(":", 1)[-1]
            if ("FAVOR" in up and "CONTRA" in up) or ("AFIRMATIV" in up and "NEGATIV" in up):
                if len(txt) > 80:  # prosa del certificado ("votaron, A FAVOR 3...")
                    continue
                # search_for encuentra el encabezado aunque venga pegado ("FAVOREN CONTRA") o con
                # la "A" de A FAVOR en la linea de arriba; la X cae en la columna mas cercana
                cols = {}
                for etiqueta, v in (("favor", "SI"), ("afirmativ", "SI"), ("contra", "NO"), ("negativ", "NO"),
                                    ("abstenci", "ABST"), ("blanco", "BLANCO"), ("ausen", "AUSENTE")):
                    r = [q for q in p.search_for(etiqueta) if abs(q.y0 / 4 - y) < 4]
                    if r:
                        cols[v] = r[0].x0
                # columna "P" (presente): su X no es voto
                cols.update({"P": a for a, _, w in ws if w.upper() == "P"})
                actual = {"mocion": _limpia(("Reconsideración de " if "RECONSIDERACI" in up else "") + mocion),
                          "votos": [], "certificado": {}}
                out.append(actual)
                continue
            if not actual or not cols:
                continue
            if up.startswith("TOTAL"):
                n = [int(w) for *_, w in ws if w.isdigit()]
                actual["certificado"] = dict(zip(("si", "no", "abst", "blanco"), n[1:] if "P" in cols else n))
                actual = None
                continue
            if len(txt) > 90:  # prosa despues de la tabla: la tabla termino
                actual = None
                continue
            nombre = " ".join(w for a, _, w in ws if a < min(cols.values()) - 15 and not w.isdigit())
            if len(nombre.split()) >= 2:
                filas.append((y, re.sub(r"X$", "", nombre).strip(), actual, dict(cols)))
        # cada X va con el nombre mas cercano en altura (a veces cae media linea arriba o abajo)
        columna = lambda cs, ex: min(cs, key=lambda c: abs(cs[c] - ex))
        pares = sorted((abs(ey - f[0]), j, i) for j, f in enumerate(filas) for i, (ey, ex) in enumerate(equis)
                       if abs(ey - f[0]) <= 3 and ex >= min(f[3].values()) - 15 and columna(f[3], ex) != "P")
        con_x: dict = {}
        for _, j, i in pares:
            if j not in con_x and i not in con_x.values():
                con_x[j] = i
        for j, (y, nombre, bloque, cs) in enumerate(filas):
            if j in con_x:
                ex = equis[con_x[j]][1]
                bloque["votos"].append((nombre, columna(cs, ex)))
    prosa = totales_en_prosa("\n".join(p.get_text() for p in doc))
    for v in out:
        if not v["certificado"] and prosa:
            v["certificado"] = prosa.pop(0)
    return out


_CLASES = (("si", r"(?:a favor|afirmativ\w*)"), ("no", r"(?:en contra|negativ\w*)"),
           ("abst", r"abstenci\w*"), ("blanco", r"(?:en )?blanco"))


def _cuenta(tramo: str, pat: str) -> int | None:
    """El numero de una clase de voto, antes ("(10) votos a favor", "10 (diez) votos afirmativos")
    o despues de la palabra ("A FAVOR 9 Asambleistas", "AFIRMATIVO: DIEZ (10)")."""
    antes = re.search(rf"(\d+)\)?\s*(?:\(\w+\)\s*)?(?:votos?\s+)?{pat}", tramo, re.I)
    if antes:
        return int(antes[1])
    despues = re.search(rf"{pat}\s*:?\s*(?:[^\W\d_]+\s*)?\(?(\d+)", tramo, re.I)
    return int(despues[1]) if despues else None


def totales_en_prosa(texto: str) -> list[dict]:
    """Totales que el memo escribe en prosa, en el orden en que aparecen."""
    out = []
    for m in re.finditer(_CLASES[0][1], texto, re.I):
        tramo = texto[max(0, m.start() - 40):m.start() + 260]
        si = _cuenta(tramo, _CLASES[0][1])
        if si is not None:
            out.append({"si": si, **{k: _cuenta(tramo, pat) or 0 for k, pat in _CLASES[1:]}})
    return out


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
    """Los votos leidos suman los totales que el PDF certifica (sin totales no se guarda)."""
    c = v.get("certificado") or {}
    if not v["votos"] or not any(c.values()):
        return False
    n = {k: sum(x == k for _, x in v["votos"]) for k in VOTOS}
    return (n["SI"], n["NO"], n["ABST"], n["BLANCO"]) == (c.get("si", 0), c.get("no", 0), c.get("abst", 0), c.get("blanco", 0))


def leer(fila: dict, pdf: bytes, gente: list[tuple[str, dict]]) -> list[dict]:
    """Votaciones del PDF que cuadran, con los votos por id de asambleista."""
    import pymupdf

    from consultas.posturas import _miembro
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    texto = "\n".join(p.get_text() for p in doc)
    leidas = del_sistema(texto) or de_tabla_x(doc)
    # si la tabla no dice que se voto: la "Mocion: ..." del memo, o el nombre de la sesion
    m = re.search(r"Moci[oó]n\s*\d*\s*:\s*(.{15,400}?)(?:\n\s*\n|$)", texto, re.I | re.S)
    respaldo = _limpia(m[1]) if m else fila.get("sesion", "")
    out = []
    for v in leidas:
        v["mocion"] = v["mocion"].strip(" -–") or respaldo
        if not cuadra(v):
            print(f"[votos_ec_comisiones] no cuadra, se omite: {fila['pdf']} {v['mocion'][:60]}", flush=True)
            continue
        votos = {}
        for nombre, voto in v["votos"]:
            m = _miembro(nombre, gente)
            if m:
                votos[m["id"]] = None if voto == "AUSENTE" else voto
        if len(votos) * 2 >= len(v["votos"]):  # los que faltan suelen ser suplentes (no estan entre los 151)
            out.append({"fecha": fila["fecha"], "asunto": v["mocion"], "comision": fila["comision"], "url": fila["pdf"], "votos": votos})
    return out


def bajar(gente: list[dict]) -> int:
    """Lee los PDF que aun no estan en PATH y los guarda. Devuelve cuantas votaciones sumo."""
    from consultas.personas import id_ec
    from core.http import session
    s = session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    ya = store.cargar(PATH, {"leidos": [], "votaciones": []}, ttl=0)
    pares = [(id_ec(p["nombre"])[3:], p) for p in gente if p["pais"] == "EC"]
    faltan = [f for f in listar(s) if f["pdf"] not in ya["leidos"]]
    print(f"[votos_ec_comisiones] {len(faltan)} PDF por leer", flush=True)
    total, nuevas, leidos = 0, [], []
    for i, fila in enumerate(faltan, 1):
        try:
            r = s.get(fila["pdf"], timeout=90)
            r.raise_for_status()
            nuevas += leer(fila, r.content, pares)
            leidos.append(fila["pdf"])
        except Exception as e:  # PDF caido o roto: se reintenta manana
            print(f"[votos_ec_comisiones] {fila['pdf']}: {str(e)[:150]}", flush=True)
        if leidos and (len(leidos) >= 50 or i == len(faltan)):  # de a poco: si el timeout corta, lo leido queda
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
    v = {"votos": [("a", "SI"), ("b", "NO"), ("c", "AUSENTE")], "certificado": {"si": 1, "no": 1, "abst": 0, "blanco": 0}}
    assert cuadra(v) and not cuadra({**v, "certificado": {"si": 2, "no": 1}}) and not cuadra({**v, "certificado": {}})
    t = ("x\nSesión Nro. 118\nAprobación unificación de proyecto de ley \nVotación definitiva\n2026-08-28 14:52 \nTOTAL\n3\n"
         "PRESENTE\n3\nAUSENTE\n0\nSI\n2\nNO\n0\nBLANCO\n0\nABSTENCION\n1\nNro.\nCurul\nAsambleísta\nVoto\n1\n9\n"
         "SOLANO CALLE ISAAC VLADIMIR\nSI\n2\n10\nPULLEY ITURRALDE CARLOS\nSI\n\nNro.\nCurul\nAsambleísta\nVoto\n3\n6\n"
         "MENDOZA ANDRADE GUIDO\nABSTENCION\n")
    b = del_sistema(t)
    assert len(b) == 1 and b[0]["mocion"] == "Aprobación unificación de proyecto de ley" and cuadra(b[0]), b
    for frase, esperado in (
            ("Con DIEZ (10) votos a favor, CERO (00) votos en contra y CERO (00) ausencias", (10, 0, 0, 0)),
            ("de julio de 2025, votaron, A FAVOR 9 Asambleístas; EN CONTRA 1 Asambleístas; ABSTENCIÓN 0", (9, 1, 0, 0)),
            ("Resumen de votación: AFIRMATIVO: DIEZ (10). NEGATIVO: CERO (0). ABSTENCIÓN: CERO (0).", (10, 0, 0, 0)),
            ("la sesión aprueba con 7 votos afirmativos y 3 abstenciones", (7, 0, 3, 0))):
        t = totales_en_prosa(frase)
        assert t and tuple(t[0].values()) == esperado, (frase, t)
    import sys
    if "probar" not in sys.argv:
        from consultas.integrantes import integrantes
        print("votaciones nuevas", bajar(integrantes()))
    print("ok")
