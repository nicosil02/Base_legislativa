"""Cargos de cada congresista: mesa directiva de su camara y presidencia,
vicepresidencia o secretaria de comisiones (Peru 2026-2031).

Salen de las paginas de WordPress del Senado y de Diputados: "Mesas directivas y
horarios de sesion de las comisiones" y "Mesa Directiva". Quien preside una
comision decide que dictamenes se agendan, por eso pesa en el tramite.

Ecuador sale de la pagina oficial de comisiones y del CAL de la Asamblea, que
responde 403 a los programas: se bajo con un navegador a data/cargos_ec_oficial.json.
    python -m consultas.cargos   # renueva data/cargos.json
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from core.text import norm

COPIA = Path(__file__).resolve().parent.parent / "data" / "cargos.json"
OFICIAL_EC = COPIA.parent / "cargos_ec_oficial.json"
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


def _filas(h: str):
    """(celdas en texto, html de la fila, nombre de la comision) de la tabla de mesas directivas."""
    for fila in re.findall(r"<tr.*?</tr>", h, re.S):
        celdas = [_texto(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)]
        if len(celdas) < 3 or not celdas[0].strip().isdigit():
            continue
        comision = re.split(r";|\(Fecha|Fecha de|President[ea]\s*:", celdas[1])[0].strip(" ;")
        comision = comision.capitalize() if comision.upper() == comision else comision
        yield celdas, fila, comision if re.match(r"Comisi|Mesa", comision) else f"Comisión de {comision[0].lower()}{comision[1:]}"


def de_comisiones(h: str, gente: list[dict]) -> list[tuple[str, str, str]]:
    """[(id, cargo, comision)] de la tabla de mesas directivas de comisiones."""
    out = []
    for celdas, _, comision in _filas(h):
        for rol, nombre in _ROL.findall(" ".join(celdas[1:3])):
            ident = _quien(nombre, gente)
            if ident:
                out.append((ident, rol, comision))
    return out


def enlaces(h: str) -> list[tuple[str, str]]:
    """[(comision, slug)] de "Ver integrantes" (solo el Senado los tiene; Diputados no
    publica los integrantes de sus comisiones en un formato que se pueda leer)."""
    out = []
    for _, fila, comision in _filas(h):
        m = re.search(r'href="https://senado\.congreso\.gob\.pe/([^/"]+)/?"', fila)
        if m:
            out.append((comision, m.group(1)))
    return out


def de_integrantes(h: str, gente: list[dict], comision: str) -> list[tuple[str, str, str]]:
    """Titulares y suplentes de la pagina de una comision del Senado (la mesa ya sale de de_comisiones)."""
    out = []
    for fila in re.findall(r"<tr.*?</tr>", h, re.S):
        nombre = re.search(r'senate-name-link[^>]*>(.*?)</a>', fila, re.S)
        rol = re.search(r'senate-role[^>]*>\s*(Titular|Suplente)\s*<', fila)
        ident = nombre and rol and _quien(_texto(nombre.group(1)), gente)
        if ident:
            out.append((ident, rol.group(1), comision))
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
                h = r.json()["content"]["rendered"]
                filas += fn(h)
                for comision, slug in enlaces(h) if pid == comisiones else []:
                    x = s.get(f"https://{camara}.congreso.gob.pe/wp-json/wp/v2/pages", params={"slug": slug, "_fields": "content"}, timeout=40)
                    if x.ok and x.json():
                        filas += de_integrantes(x.json()[0]["content"]["rendered"], miembros, comision)
        for ident, cargo, organo in filas:
            if {"cargo": cargo, "organo": organo} not in cargos.setdefault(ident, []):
                cargos[ident].append({"cargo": cargo, "organo": organo})
    ec = [p for p in gente if p["pais"] == "EC"]
    for nombre, cargo, organo in json.loads(OFICIAL_EC.read_text(encoding="utf-8"))["cargos"]:
        ident = _quien(nombre, ec)
        if ident:
            cargos.setdefault(ident, []).append({"cargo": cargo, "organo": organo})
        else:
            print(f"[cargos] sin asambleista para {nombre}")
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
    fila = """<tr class="senate-row"><td><a class="senate-name-link" href="u">Mesía Ramírez, Carlos Fernando</a></td>
              <td><span class="senate-group-span">FP</span></td><td><span class="senate-role-titular">Titular</span></td></tr>"""
    assert de_integrantes(fila, gente, "Comisión X") == [("senado:mesia ramirez", "Titular", "Comisión X")]
    from consultas.integrantes import integrantes
    datos = bajar(integrantes())
    n = sum(len(v) for v in datos.values())
    assert n >= 60, n
    COPIA.write_text(json.dumps(datos, ensure_ascii=False, indent=0), encoding="utf-8")
    from core import store  # en la corrida diaria (GH_TOKEN) queda como commit en main
    if store._cfg():
        store.actualizar("data/cargos.json", lambda d: datos if d != datos else None, "cargos: renovados", {})
    print("ok", len(datos), "personas", n, "cargos")
