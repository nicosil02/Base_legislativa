"""Votaciones de las comisiones del Congreso de Peru (Senado y Diputados, 2026-2031).

Salen de las actas que cada comision sube al visor de sesiones (sesiones.id_alfresco_acta),
por el mismo enlace que usa el boton "ver documento" del visor publico. El acta es prosa y
cada comision escribe el voto a su manera:
  "Quispe Candia Luis Eliseo (a favor), Aguirre Ramos Marlon (en contra)"
  "Adrian Alvaron De La Cruz- A favor Royser Castro Grandez- En contra"
  "Votaron a favor ...: LOPEZ CHAU NAVA, PABLO; ...; y se abstuvo el senador RODRICH ..."
  "Se aprobo por mayoria con 14 votos a favor y 2 en contra" (solo totales)
Se lee con reglas, sin IA. Solo se guardan las votaciones sobre un proyecto de ley, y los
nombres solo si cuadran con los totales del acta; si no, quedan los totales.
ponytail: el proyecto es el ultimo que se nombra antes del voto en el mismo punto de agenda.

    python -m consultas.votos_pe_comisiones   # lee las actas nuevas (refrescar-pe, una vez al dia)
"""
from __future__ import annotations

import json
import re

from core import store
from core.text import norm

PATH = "data/votos_pe_comisiones.json"
DOC = "https://wb2server.congreso.gob.pe/service-alfresco/alfresko/detalle/preview/file?idDocument={}&key=47j6sp1KH2elP2IphiOp78e"

_PL = re.compile(r"(?i)(?:proyectos? de ley|proposici[oó]n(?:es)? legislativas?|\bp\.?l\.?)\s*(?:n[°º.ro]*\s*)?0*(\d{1,5})\s*[/-]\s*2026(?:\s*-\s*2031)?(?:\s*-\s*C([DS]))?")
_VOTO = re.compile(r"(?i)votaron|votos? a favor|votaci[oó]n:|se aprob[oó]|fue aprobad[oa]|aprobad[oa] por (?:unanimidad|mayor[ií]a)")
_SECCION = re.compile(r"(?i)\b(?:[IVX]+\.\s+)?(?:orden del d[ií]a|despacho|informes|pedidos|estaci[oó]n de)\b")
_REEMPLAZO = re.compile(r"(?i)\(?\s*(?:en reemplazo|suplente|en representaci[oó]n)\s+(?:de[l]?\s+)?(?:la |el )?(?:diputad[oa]|senador[a]?|congresista)?[^;:()]{0,60}\)?")
_ETIQUETA = [("SI", r"a favor"), ("NO", r"en contra"), ("ABST", r"abstenci[oó]n|se abstuv|abstuvieron")]


def _num(m: str) -> int:
    pal = {"cero": 0, "un": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
           "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15, "dieciseis": 16,
           "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20, "ningun": 0, "ninguna": 0}
    return int(m) if m.isdigit() else pal.get(norm(m), -1)


def totales(tramo: str) -> dict:
    """{"si": n, "no": n, "abst": n} con lo que el acta dice en cifras o palabras."""
    t, out = norm(tramo), {}
    n = r"(\d+|cero|un|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|dieciseis|diecisiete|dieciocho|diecinueve|veinte|ningun|ninguna)"
    for k, pat in (("si", r"votos? a favor|a favor"), ("no", r"votos? en contra|en contra"), ("abst", r"abstenci\w*|votos? en abstencion")):
        m = (re.search(rf"{n}\s*(?:\(\d+\)\s*)?(?:votos?\s*|(?:senadores|diputad[oa]s|congresistas|miembros)\s*)?(?:{pat})", t)
             or re.search(rf"(?:votaron|votos?)\s*(?:{pat})\s*(?:de\s*)?{n}", t))
        if m:
            out[k] = _num(m.group(1))
    if "unanimidad" in t and "si" in out:
        out.setdefault("no", 0); out.setdefault("abst", 0)
    return out


def nombres(tramo: str, gente: list[dict]) -> dict[str, str]:
    """id -> SI/NO/ABST de los miembros nombrados en el tramo. La etiqueta pegada al nombre
    ("(a favor)", "- En contra") gana; si no hay, vale la ultima seccion ("votaron a favor ...")."""
    t = norm(_REEMPLAZO.sub(" ", tramo))
    pos = []
    for p in gente:
        ape = norm(p["nombre"].split(",")[0]).split()
        if len(ape) < 2:
            continue
        for m in re.finditer(r"\b" + r"\s+".join(map(re.escape, ape[:2])) + r"\b", t):
            pos.append((m.start(), m.end(), p["id"]))
        if not any(x[2] == p["id"] for x in pos):  # "Adrian Alvaron De La Cruz": nombre y luego apellidos
            for m in re.finditer(r"\b" + re.escape(ape[0]) + r"\b", t):
                if norm(p["nombre"].split(",")[-1]).split()[:1] and norm(p["nombre"].split(",")[-1]).split()[0] in t[max(0, m.start() - 40):m.start()]:
                    pos.append((m.start(), m.end(), p["id"]))
                    break
    pos.sort()
    out = {}
    for i, (a, b, ident) in enumerate(pos):
        hasta = pos[i + 1][0] if i + 1 < len(pos) else len(t)
        pegado = t[b:min(hasta, b + 60)]
        voto = next((k for k, pat in _ETIQUETA if re.match(rf"[^;:.]{{0,45}}?\b(?:{pat})", pegado)), None)
        if voto is None:
            antes = [(m.start(), k) for k, pat in _ETIQUETA for m in re.finditer(pat, t[:a])]
            voto = max(antes)[1] if antes else None
        if voto:
            out.setdefault(ident, voto)
    return out


def leer(texto: str, gente: list[dict]) -> list[dict]:
    """Votaciones sobre proyectos de ley de un acta: [{"pl", "camara_pl", "asunto", "si", "no", "abst", "votos"}]."""
    t = re.sub(r"\s+", " ", texto)
    anclas = [m.start() for m in _VOTO.finditer(t)]
    out, fin_previo = [], 0
    for i, a in enumerate(anclas):
        if a < fin_previo:
            continue
        # "Se aprobo con 10 votos a favor... Votaron a favor ...; en contra ..." es una sola votacion
        j = i
        while j + 1 < len(anclas) and anclas[j + 1] - a < 2500 and re.match(r"(?i)votaron|votos? a favor|votaci[oó]n:", t[anclas[j + 1]:]):
            j += 1
        fin = min(anclas[j + 1] if j + 1 < len(anclas) else len(t), a + 2500)
        fin_previo = fin
        corte = re.search(r"•|-{5,}|[IVX]+\.\s+[A-ZÁÉÍÓÚ]{4,}", t[a + 20:fin])  # sigue otro acuerdo o seccion
        fin = a + 20 + corte.start() if corte else fin
        contexto = t[max(0, a - 1200):a]
        corte = list(_SECCION.finditer(contexto))
        if corte and corte[-1].start() < 1200:
            contexto = contexto[corte[-1].end():]
        pls = list(_PL.finditer(contexto))
        if not pls:
            continue
        tramo = t[a:fin]
        tot = totales(tramo)
        if "si" not in tot:
            continue
        votos = nombres(tramo, gente)
        cuenta = dict(zip(("si", "no", "abst"), (sum(v == k for v in votos.values()) for k in ("SI", "NO", "ABST"))))
        if any(tot.get(k, cuenta[k]) != cuenta[k] for k in cuenta):  # lo que el acta no cuenta, lo dan los nombres
            votos, cuenta = {}, {"no": 0, "abst": 0}
        out.append({"pl": pls[-1].group(1), "camara_pl": pls[-1].group(2), "asunto": contexto[-420:].strip(),
                    **cuenta, **tot, "votos": votos})
    return out


def bajar() -> int:
    """Lee las actas que aun no estan en PATH. Devuelve cuantas votaciones sumo."""
    import pymupdf
    from consultas.integrantes import integrantes
    from core.db import connect_ro
    from core.http import session
    s = session()
    s.headers["User-Agent"] = "Mozilla/5.0"
    ya = store.cargar(PATH, {"leidas": [], "votaciones": []}, ttl=0)
    gente = integrantes()
    filas = connect_ro("proyectos.db").execute(
        """SELECT id_sesion, camara, nombre_comision, fecha, id_alfresco_acta FROM sesiones
           WHERE fecha >= '2026-07-27' AND id_alfresco_acta != '' AND camara IN ('Senado', 'Diputados')""").fetchall()
    faltan = [f for f in filas if f[4] not in ya["leidas"]]
    print(f"[votos_pe_comisiones] {len(faltan)} actas por leer", flush=True)
    nuevas, leidas = [], []
    for ids, cam, com, fecha, acta in faltan:
        try:
            r = s.get(DOC.format(acta), timeout=90)
            r.raise_for_status()
            texto = "".join(p.get_text() for p in pymupdf.open(stream=r.content, filetype="pdf"))
        except Exception as e:  # acta caida o rota: se reintenta manana
            print(f"[votos_pe_comisiones] sesion {ids}: {str(e)[:150]}", flush=True)
            continue
        leidas.append(acta)
        if len(texto) < 500:  # escaneada sin texto; ponytail: OCR si hace falta
            continue
        sala = [p for p in gente if p.get("camara") == cam.lower()]
        for v in leer(texto, sala):
            if any(x["pl"] == v["pl"] and x["asunto"] == v["asunto"] for x in ya["votaciones"] + nuevas):
                continue  # la misma acta subida a dos sesiones
            nuevas.append({**v, "fecha": fecha, "camara": cam.lower(), "comision": com, "sesion": ids, "url": DOC.format(acta)})
    if leidas:
        store.actualizar(PATH, lambda d: {"leidas": d.get("leidas", []) + leidas,
                                          "votaciones": sorted(d.get("votaciones", []) + nuevas, key=lambda v: v["fecha"])},
                         f"votos comisiones PE: {len(nuevas)} votaciones", {"leidas": [], "votaciones": []})
    return len(nuevas)


def votaciones() -> list[dict]:
    """Las votaciones guardadas (copia del repo), de la mas vieja a la mas nueva."""
    from core.db import ROOT
    p = ROOT / PATH
    return json.loads(p.read_text(encoding="utf-8"))["votaciones"] if p.exists() else []


if __name__ == "__main__":
    g = [{"id": "d:a", "nombre": "QUISPE CANDIA, LUIS ELISEO"}, {"id": "d:b", "nombre": "AGUIRRE RAMOS, MARLON"},
         {"id": "d:c", "nombre": "ISLA ROJAS, AZUCENA"}, {"id": "d:d", "nombre": "ALVARON DE LA CRUZ, ADRIAN"}]
    assert nombres("Quispe Candia Luis Eliseo (a favor), Aguirre Ramos Marlon (en contra)", g) == {"d:a": "SI", "d:b": "NO"}
    assert nombres("Votaron a favor: Quispe Candia, Luis; Peña, en reemplazo de Isla Rojas, Azucena; en contra Aguirre Ramos, Marlon", g) == {"d:a": "SI", "d:b": "NO"}
    assert totales("aprobado por mayoría con diez (10) votos a favor, un (1) voto en abstención y cero (0) votos en contra") == {"si": 10, "no": 0, "abst": 1}
    assert totales("Se aprobó por mayoría con 14 votos a favor y 2 votos en contra") == {"si": 14, "no": 2}
    acta = ("ORDEN DEL DÍA Se debatió el dictamen del Proyecto de Ley 98/2026-CD. Se aprobó por mayoría con 1 voto a favor "
            "y 1 en contra. Votaron a favor Quispe Candia, Luis; en contra Aguirre Ramos, Marlon.")
    v = leer(acta, g)
    assert len(v) == 1 and v[0]["pl"] == "98" and v[0]["votos"] == {"d:a": "SI", "d:b": "NO"}, v
    assert leer("ORDEN DEL DÍA Plan de trabajo. Se aprobó por unanimidad con 10 votos a favor.", g) == []
    print("ok")
