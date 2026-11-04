"""Quienes integran hoy el Senado y la Camara de Diputados (Peru, 2026-2031) y la
Asamblea Nacional (Ecuador, 2025-2029), con bancada, region, foto y una reseña.
Las fotos que faltan en Wikipedia salen del Observatorio Legislativo (consultas/votos_ec).

Peru sale de las paginas oficiales de cada camara (WordPress, /wp-json/wp/v2/senador
y /diputado). Ecuador sale del anexo de Wikipedia de la Asamblea: el sitio oficial
(asambleanacional.gob.ec) responde 503 desde el 4/11/2026 y Wikipedia trae bancada,
provincia, foto y fecha de salida de cada uno.

Se baja una vez al dia en la app; si falla queda la copia data/integrantes.json.
    python -m consultas.integrantes   # renueva la copia
"""
from __future__ import annotations

import functools
import html
import json
import re
import threading
import time
from pathlib import Path

from consultas.personas import apellidos, id_ec

COPIA = Path(__file__).resolve().parent.parent / "data" / "integrantes.json"
CADA_SEG = 24 * 3600
_WIKI_EC = ("https://es.wikipedia.org/w/api.php?action=parse&format=json&prop=wikitext&page="
            "Anexo:Asambleístas_del_quinto_período_legislativo_de_la_Asamblea_Nacional_del_Ecuador")
_BANCADA_PE = {"fuerza-popular": "Fuerza Popular", "juntos-por-el-peru": "Juntos por el Perú",
               "renovacion-popular": "Renovación Popular", "partido-del-buen-gobierno": "Partido del Buen Gobierno",
               "partido-civico-obras": "Partido Cívico Obras", "ahora-nacion": "Ahora Nación"}
_REGION_PE = {"ancash": "Áncash", "apurimac": "Apurímac", "huanuco": "Huánuco", "junin": "Junín",
              "san-martin": "San Martín", "peruanos-en-el-exterior": "Peruanos en el exterior",
              "lima-metropolitana": "Lima Metropolitana", "lima-provincias": "Lima Provincias",
              "madre-de-dios": "Madre de Dios", "la-libertad": "La Libertad", "distrito-nacional": "Distrito único nacional"}
_BANCADA_EC = {"ADN": "Acción Democrática Nacional", "BC": "Revolución Ciudadana", "MUPP": "Pachakutik",
               "PSC": "Partido Social Cristiano", "Sin bancada": "Sin bancada"}
# {{ECU|X}} de Wikipedia: codigo ISO 3166-2:EC de la provincia
_PROV_EC = {"A": "Azuay", "B": "Bolívar", "C": "Carchi", "D": "Orellana", "E": "Esmeraldas", "F": "Cañar",
            "G": "Guayas", "H": "Chimborazo", "I": "Imbabura", "L": "Loja", "M": "Manabí", "N": "Napo",
            "O": "El Oro", "P": "Pichincha", "R": "Los Ríos", "S": "Morona Santiago", "SD": "Santo Domingo",
            "SE": "Santa Elena", "T": "Tungurahua", "U": "Sucumbíos", "W": "Galápagos", "X": "Cotopaxi",
            "Y": "Pastaza", "Z": "Zamora Chinchipe"}


def _texto(h: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def _tax(x: dict, pref: str) -> str | None:
    return next((c[len(pref) + 1:] for c in x.get("class_list", []) if c.startswith(pref + "-")), None)


def _peru(sesion, camara: str) -> list[dict]:
    sitio, tipo = ("senado", "senador") if camara == "senado" else ("diputados", "diputado")
    filas = []
    for pagina in (1, 2):
        r = sesion.get(f"https://{sitio}.congreso.gob.pe/wp-json/wp/v2/{tipo}", params={"per_page": 100, "page": pagina, "_embed": "wp:featuredmedia",
                                   "_fields": "title,link,content,class_list,_links,_embedded"}, timeout=60)
        if r.status_code == 400:  # ya no hay pagina 2
            break
        r.raise_for_status()
        filas += r.json()
    out = []
    for x in filas:
        nombre = html.unescape(x["title"]["rendered"])  # "Velásquez García, Miguel Angel"
        b, reg = _tax(x, "grupo_parlamentario"), _tax(x, "distrito_electoral")
        # la de 300 px: la original pesa ~400 KB y en el hemiciclo se piden muchas
        tam = ((x.get("_embedded", {}).get("wp:featuredmedia") or [{}])[0].get("media_details") or {}).get("sizes", {})
        foto = (tam.get("medium") or tam.get("full") or {}).get("source_url")
        out.append({"pais": "PE", "camara": camara, "id": f"{camara}:{apellidos('PE', nombre)}", "nombre": nombre,
                    "bancada": _BANCADA_PE.get(b, (b or "Sin bancada").replace("-", " ").capitalize()),
                    "region": _REGION_PE.get(reg, (reg or "").replace("-", " ").title() or None),
                    "condicion": (_tax(x, "condicion") or "").replace("-", " ") or None,
                    "foto": foto, "url": x["link"], "resena": _texto(x["content"]["rendered"])[:1500]})
    return out


def _celdas(fila: str) -> list[str]:
    """Celdas de una fila de tabla wiki: una por linea que empieza con '|'."""
    return [re.sub(r"^\s*\|", "", c) for c in re.split(r"\n(?=\s*\|)", "\n" + fila) if c.strip().startswith("|")]


def _limpio(celda: str) -> str:
    c = re.sub(r"^[^|\[]*?=\"[^\"]*\"\s*\|", "", celda)  # quita align="center" |
    c = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", c)
    return re.sub(r"<[^>]+>|''+", "", c).strip()


def ecuador_de_wiki(wikitexto: str) -> list[dict]:
    """Asambleistas en funciones: las 4 primeras tablas del anexo, filas sin fecha de salida."""
    out = []
    for tabla in re.findall(r"\{\|.*?\n\|\}", wikitexto, re.S)[:4]:
        provincia = None
        for fila in re.split(r"\n\|-[^\n]*", tabla)[1:]:
            cs = _celdas(fila)
            if (m := re.search(r"\{\{ECU\|(\w+)\}\}", cs[0] if cs else "")):
                provincia, cs = _PROV_EC.get(m[1], m[1]), cs[1:]
            # color, [foto], nombre, bancada, #, lista, partido, [distrito], inicio, fin
            foto = next((i for i, c in enumerate(cs) if "Archivo:" in c), None)
            i = foto + 1 if foto is not None else 1  # sin foto el nombre ocupa dos columnas
            if len(cs) < i + 6 or _limpio(cs[-1]):  # cabecera, o ya dejo la curul
                continue
            nombre, bancada = _limpio(cs[i]), _limpio(cs[i + 1])
            archivo = re.search(r"Archivo:([^|\]]+)", cs[foto])[1].strip().replace(" ", "_") if foto is not None else None
            extra = _limpio(cs[-3]) if len(cs) == i + 8 else ""  # distrito o circunscripcion del exterior
            region = provincia or ("Nacional" if not extra else f"Exterior, {extra}")
            if provincia and extra.isdigit():
                region = f"{provincia}, distrito {extra}"
            out.append({"pais": "EC", "camara": "asamblea", "id": id_ec(nombre), "nombre": nombre,
                        "bancada": _BANCADA_EC.get(bancada, bancada or "Sin bancada"), "region": region, "condicion": None,
                        "foto": f"https://commons.wikimedia.org/wiki/Special:FilePath/{archivo}?width=240" if archivo else None,
                        "url": None, "resena": None})
    return out


def _observatorio(sesion) -> dict[str, dict]:
    """Foto y perfil de cada asambleista actual en el Observatorio Legislativo
    (los que tienen bancada asignada son los del periodo 2025-2029)."""
    out = {}
    for pagina in (1, 2):
        r = sesion.get("https://observatoriolegislativo.ec/wp-json/wp/v2/perfil", timeout=90, params={
            "per_page": 100, "page": pagina, "bancada": "428,431,438,465,466", "_embed": "wp:featuredmedia",
            "_fields": "title,link,_links,_embedded"})
        if r.status_code == 400:
            break
        r.raise_for_status()
        for x in r.json():
            m = (x.get("_embedded", {}).get("wp:featuredmedia") or [{}])[0]
            tam = (m.get("media_details") or {}).get("sizes", {})
            out[id_ec(html.unescape(x["title"]["rendered"]))] = {
                "foto": (tam.get("medium") or tam.get("full") or {}).get("source_url"), "url": x["link"]}
    return out


def bajar() -> list[dict]:
    from core.http import session
    s = session()
    ec = s.get(_WIKI_EC, timeout=40)
    ec.raise_for_status()
    asamblea = ecuador_de_wiki(ec.json()["parse"]["wikitext"]["*"])
    try:  # foto que falte en Wikipedia y enlace al perfil con su trayectoria
        obs = _observatorio(s)
        for p in asamblea:
            o = obs.get(p["id"], {})
            p["foto"], p["url"] = p["foto"] or o.get("foto"), o.get("url")
    except Exception as e:
        print(f"[integrantes] observatorio: {e}")
    return _peru(s, "senado") + _peru(s, "diputados") + asamblea


_estado: dict = {"datos": None, "hora": 0.0}
_CANDADO = threading.Lock()


def _renovar() -> None:
    try:
        _estado["datos"] = bajar()
    except Exception as e:  # queda lo que habia; se reintenta en un dia
        print(f"[integrantes] sigo con la copia: {e}")


def integrantes() -> list[dict]:
    """Responde al tiro con lo que hay (la copia del repo al arrancar) y, una vez
    al dia, baja la lista nueva por detras."""
    with _CANDADO:
        if _estado["datos"] is None:
            _estado["datos"] = json.loads(COPIA.read_text(encoding="utf-8"))
        if time.time() - _estado["hora"] > CADA_SEG:
            _estado["hora"] = time.time()
            threading.Thread(target=_renovar, daemon=True, name="vali-integrantes").start()
        return _estado["datos"]


_POLITICO = re.compile(r"congres|senad|diputad|asamble|parlament|politic|alcalde|ministr|gobernador|consejer")


@functools.lru_cache(maxsize=512)
def resena_wiki(pais: str, nombre: str) -> dict | None:
    """Primer parrafo de su articulo en Wikipedia, solo si el titulo lleva su
    primer apellido y el texto habla de politica (evita homonimos)."""
    from core.http import session
    from core.text import norm
    ap = apellidos(pais, nombre).split()[0]
    # nombre de pila: tras la coma en Peru, la tercera palabra en Ecuador
    pila = norm(nombre.split(",")[1]).split()[0] if pais == "PE" and "," in nombre else (norm(nombre).split() + [""] * 3)[2]
    buscado = " ".join(reversed(nombre.split(","))) if pais == "PE" else nombre
    api = "https://es.wikipedia.org/w/api.php"
    try:
        s = session(reintentos=1)
        hits = s.get(api, params={"action": "query", "list": "search", "srsearch": buscado, "srlimit": 3, "format": "json"},
                     timeout=15).json()["query"]["search"]
        for h in hits:
            if ap not in norm(h["title"]):
                continue
            pag = next(iter(s.get(api, params={"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
                                               "titles": h["title"], "format": "json"}, timeout=15).json()["query"]["pages"].values()))
            texto = (pag.get("extract") or "").strip()
            if texto and pila and pila in norm(texto[:200]) and _POLITICO.search(norm(texto)):
                return {"texto": texto[:1500], "url": f"https://es.wikipedia.org/wiki/{h['title'].replace(' ', '_')}"}
    except Exception as e:
        print(f"[integrantes] wikipedia {nombre}: {e}")
    return None


if __name__ == "__main__":
    fila = """
| rowspan="6" |'''{{ECU|A}}'''
| style="color:white" |
| align="center" |[[Archivo:Camila León (cropped).jpg|40px]]
| align="center" |<small>León Cueva Camila</small>
| align="center" |<small>[[Acción Democrática Nacional (Ecuador)|ADN]]</small>
| align="center" |<small>107</small>
| align="center" |<small>[[x|ADN]]</small>
| align="center" |<small>[[x|ADN]]</small>
| align="center" |<small>14 de mayo de 2025</small>
| align="center" |
|-
| style="color:white" |
| align="center" |[[Archivo:X.jpg|40px]]
| align="center" |<small>Paz Ruiz Ana</small>
| align="center" |<small>[[y|BC]]</small>
| align="center" |<small>1</small>
| align="center" |<small>RC</small>
| align="center" |<small>RC</small>
| align="center" |<small>14 de mayo de 2025</small>
| align="center" |<small>8 de junio de 2026</small>
|}"""
    gente = ecuador_de_wiki("{| class=x\n! a\n|-" + fila)
    assert [(p["nombre"], p["bancada"], p["region"], p["id"]) for p in gente] == [
        ("León Cueva Camila", "Acción Democrática Nacional", "Azuay", "EC:leon cueva")], gente
    datos = bajar()
    cuenta = {c: sum(p["camara"] == c for p in datos) for c in ("senado", "diputados", "asamblea")}
    assert cuenta["senado"] == 60 and cuenta["diputados"] == 130 and 140 <= cuenta["asamblea"] <= 151, cuenta
    COPIA.write_text(json.dumps(datos, ensure_ascii=False, indent=0), encoding="utf-8")
    print("ok", cuenta)
