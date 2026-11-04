"""Cargos de cada congresista: mesa directiva de su camara y presidencia,
vicepresidencia o secretaria de comisiones (Peru 2026-2031).

Salen de las paginas de WordPress del Senado y de Diputados: "Mesas directivas y
horarios de sesion de las comisiones" y "Mesa Directiva". Quien preside una
comision decide que dictamenes se agendan, por eso pesa en el tramite.

Ecuador no tiene esta tabla en un formato que se pueda leer (el sitio de la
Asamblea responde 403 a los programas).
    python -m consultas.cargos   # renueva data/cargos.json
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from core.text import norm

COPIA = Path(__file__).resolve().parent.parent / "data" / "cargos.json"
# (camara, id de pagina de comisiones, id de pagina de mesa directiva)
_PAGINAS = [("senado", 1744, 1542), ("diputados", 2269, 1478)]
_ROL = re.compile(r"(President[ea]|Vicepresident[ea]|Secretari[oa])\s*:\s*(.*?)(?=(?:President[ea]|Vicepresident[ea]|Secretari[oa])\s*:|$)", re.S)


def _texto(h: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<br ?/?>", " ; ", re.sub(r"<(?!br)[^>]+>", " ", h)))).strip()


def _quien(nombre: str, gente: list[dict]) -> str | None:
    """Id del miembro cuyo nombre comparte mas palabras (minimo los dos apellidos)."""
    pal = set(norm(re.sub(r"\(.*?\)|–|-|,|;|Senador[a]?|Diputad[oa]", " ", nombre)).split())
    mejor = max(gente, key=lambda p: len(pal & set(norm(p["nombre"].replace(",", " ")).split())), default=None)
    return mejor["id"] if mejor and len(pal & set(norm(mejor["nombre"].replace(",", " ")).split())) >= 2 else None


def de_comisiones(h: str, gente: list[dict]) -> list[tuple[str, str, str]]:
    """[(id, cargo, comision)] de la tabla de mesas directivas de comisiones."""
    out = []
    for fila in re.findall(r"<tr.*?</tr>", h, re.S):
        celdas = [_texto(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)]
        if len(celdas) < 3 or not celdas[0].strip().isdigit():
            continue
        cuerpo = " ".join(celdas[1:3])
        comision = re.split(r";|\(Fecha|Fecha de|President[ea]\s*:", celdas[1])[0].strip(" ;")
        comision = comision.capitalize() if comision.upper() == comision else comision
        for rol, nombre in _ROL.findall(cuerpo):
            ident = _quien(nombre, gente)
            if ident:
                out.append((ident, rol, comision if re.match(r"Comisi|Mesa", comision) else f"Comisión de {comision[0].lower()}{comision[1:]}"))
    return out


def de_mesa(h: str, camara: str, gente: list[dict]) -> list[tuple[str, str, str]]:
    """Mesa directiva: el texto alterna 'Apellidos, Nombres' y el cargo."""
    partes = [re.sub(r"\s+", " ", html.unescape(x)).strip() for x in re.split(r"<[^>]+>", h)]
    partes = [x for x in partes if x]
    out = []
    for i, x in enumerate(partes[:-1]):
        cargo = partes[i + 1]
        if "," in x and re.match(r"(Primer|Segund|Tercer)?\w*\s*(Vice)?[Pp]resident", cargo):
            ident = _quien(x, gente)
            if ident:
                out.append((ident, cargo, "Mesa Directiva " + ("del Senado" if camara == "senado" else "de la Cámara de Diputados")))
    return out


def bajar(gente: list[dict]) -> dict[str, list[dict]]:
    from core.http import session
    s, cargos = session(), {}
    for camara, comisiones, mesa in _PAGINAS:
        miembros = [p for p in gente if p["pais"] == "PE"]  # las bicamerales mezclan senadores y diputados
        filas = []
        for pid, fn in ((comisiones, lambda h: de_comisiones(h, miembros)), (mesa, lambda h: de_mesa(h, camara, [p for p in miembros if p["camara"] == camara]))):
            r = s.get(f"https://{camara}.congreso.gob.pe/wp-json/wp/v2/pages/{pid}", params={"_fields": "content"}, timeout=40)
            if r.ok:
                filas += fn(r.json()["content"]["rendered"])
        for ident, cargo, organo in filas:
            if {"cargo": cargo, "organo": organo} not in cargos.setdefault(ident, []):
                cargos[ident].append({"cargo": cargo, "organo": organo})
    return cargos


def cargos() -> dict[str, list[dict]]:
    return json.loads(COPIA.read_text(encoding="utf-8")) if COPIA.exists() else {}


if __name__ == "__main__":
    gente = [{"pais": "PE", "camara": "senado", "id": "senado:mesia ramirez", "nombre": "Mesía Ramírez, Carlos Fernando"},
             {"pais": "PE", "camara": "diputados", "id": "diputados:avendano vilca", "nombre": "Avendaño Vilca, Giannina Iris"}]
    h = """<tr><td>1</td><td>COMISIÓN DE CONSTITUCIÓN<br>(Fecha de instalación: 12-08-2026)</td>
           <td>Presidente: Mesía Ramírez Carlos Fernando (Fuerza Popular)<br>Vicepresidente: Otro Nombre X (RP)</td></tr>
           <tr><td>2</td><td>CONSTITUCIÓN Presidente: <br>Giannina Iris Avendaño Vilca (JPP)</td><td>Edificio</td></tr>"""
    assert de_comisiones(h, gente) == [("senado:mesia ramirez", "Presidente", "Comisión de constitución"),
                                       ("diputados:avendano vilca", "Presidente", "Comisión de constitución")], de_comisiones(h, gente)
    from consultas.integrantes import integrantes
    datos = bajar(integrantes())
    n = sum(len(v) for v in datos.values())
    assert n >= 60, n
    COPIA.write_text(json.dumps(datos, ensure_ascii=False, indent=0), encoding="utf-8")
    print("ok", len(datos), "personas", n, "cargos")
