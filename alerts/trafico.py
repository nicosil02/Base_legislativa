"""Espacio por cliente: lo que marco el analista en la bandeja, lo ya enviado
(para no repetir) y los PL que sigue, y el Word del trafico semanal con el
formato de cada cliente (Syngenta: titulo + parrafo + enlaces, como
clientes/syngenta/031126_Alertas_Syngenta_EC.docx; Bayer: titulo + 2-3
vinetas, ver memoria trafico-bayer). Syngenta tambien recibe el TTW (Topics
to Watch): un bullet de 2-3 lineas en ingles por tema para su equipo global
(clientes/syngenta/formato_alertas.md, seccion 2)."""
from __future__ import annotations

import io
import re
import json

from alerts import bandeja, historial, pls_seguidos
from clientes import config

PAISES = {"PE": "PERÚ", "EC": "ECUADOR"}
PAISES_EN = {"PE": "PERU", "EC": "ECUADOR"}
VINETAS = {"bayer"}  # el resto: parrafo corto
TTW = {"syngenta"}

ESTILO = {
    "parrafo": "un parrafo corto de lectura rapida (3 a 5 oraciones): que paso, cuando, quien y que cambia para el sector",
    "vinetas": "2 o 3 vinetas cortas (una oracion cada una): el hecho, el dato clave y lo que sigue",
}
PROMPT = """Redactas el trafico semanal de noticias para {cliente}. Para cada item escribe un titulo
directo y {estilo}. Espanol llano, sin metaforas, sin dos puntos ni guiones largos como conectores,
sin consejos al cliente y sin nombrarlo. Cifras en numeros como en la fuente (USD 17,3 millones,
133 items), nunca en letras. El titulo nombra a la persona, entidad o norma concreta. Usa solo lo que dice el material; si el texto de la pagina
no se pudo leer, quedate en lo que dicen el titulo y el resumen y no inventes cifras ni fechas.

Perfil del cliente (para elegir el angulo):
{notas}

ITEMS:
{items}"""
PROMPT_TTW = """You write "Topics to Watch (Andean countries)" for {cliente}'s global team. For each item
write a short English title and ONE bullet of 2-3 lines, brief and professional: what happened, who,
and why it could matter for an agrochemicals (crop protection) business in that country. Plain
English, figures as digits exactly as in the source, no advice, do not name the client. Use only the
material; if the page text could not be read, stick to the title and summary.

Client profile (for the angle):
{notas}

ITEMS:
{items}"""
ESQUEMA = {"type": "array", "items": {"type": "object", "properties": {
    "n": {"type": "integer"}, "titulo": {"type": "string"}, "texto": {"type": "array", "items": {"type": "string"}}},
    "required": ["n", "titulo", "texto"]}}


def _de_cliente(slug: str, item: dict) -> bool:
    return slug in (item.get("porque") or {})


def _enviada(e: dict) -> dict:
    """Entrada del historial con la forma de un item: titulo en **negrita**,
    pais al final del encabezado y el primer enlace del cuerpo."""
    titulo = re.search(r"\*\*(.+?)\*\*", e["cuerpo"])
    url = re.search(r"https?://\S+", e["cuerpo"])
    ultimo = e["encabezado"].rsplit("—", 1)[-1].strip()
    pais = {"Perú": "PE", "Peru": "PE", "Ecuador": "EC"}.get(ultimo, ultimo)
    return {**e, "titulo": titulo[1] if titulo else e["encabezado"], "url": url[0].rstrip(").,") if url else None,
            "pais": pais if pais in PAISES else None,
            "resumen": re.sub(r"\*\*.+?\*\*\n?", "", e["cuerpo"], count=1).strip()[:1500]}


def _en_agenda(slug: str, seguidos: list[dict], agenda: list[dict]) -> list[dict]:
    """Sesiones proximas que tocan al cliente: el juez de agenda nombro al
    cliente en un punto (alerts/agenda_interes.py) o el texto trae un PL que sigue."""
    nombre = config.todos().get(slug, {}).get("nombre", slug).lower()
    pls = []
    for p in seguidos:
        if p["pais"] == "EC":
            pls.append((p, re.compile(rf"\b{re.escape(p['pl'])}\b")))
        else:  # 00011-2026-2031-CD sale en las agendas como 11/2026-CD o 00011/2026
            num, anio = p["pl"].split("-")[:2]
            pls.append((p, re.compile(rf"\b0*{int(num)}\s*/\s*{anio}\b")))
    out = []
    for a in agenda:
        puntos = [x for x in a.get("puntos", []) if nombre in x.lower() or slug in x.lower()]
        suyos = [f"{p['pais']} {p['pl']}" for p, rx in pls if p["pais"] == a["pais"] and rx.search(a.get("texto") or "")]
        if puntos or suyos:
            out.append({"nombre": a["nombre"], "pais": a["pais"], "cuando": a.get("cuando") or a["fecha"],
                        "puntos": puntos, "pls": suyos})
    return out


def datos(slug: str, desde: str, agenda: list[dict] | None = None) -> dict:
    """desde: AAAA-MM-DD. Marcadas = Interesante o Alertar en la bandeja.
    agenda: las sesiones proximas del Panel (front/vistas._agenda), con sus puntos."""
    marcadas = [{"clave": k, "estado": v["estado"], "fecha": v["fecha"][:10], **v["item"]}
                for k, v in bandeja.estados().items()
                if v.get("estado") in ("interesante", "alertar") and v.get("item")
                and v["fecha"][:10] >= desde and _de_cliente(slug, v["item"])]
    enviadas = [_enviada(e) for e in historial.entradas(slug, historial.leer(slug)) if e["fecha"] >= desde]
    seguidos = [v for v in pls_seguidos.lista().values() if slug in (v.get("por") or "")]
    return {"marcadas": sorted(marcadas, key=lambda m: m["fecha"], reverse=True),
            "enviadas": enviadas[::-1], "seguidos": seguidos, "agenda": _en_agenda(slug, seguidos, agenda or []),
            "ttw": slug in TTW}


def _notas(slug: str) -> str:
    from alerts.chat import CLIENTES_DIR, _leer
    return (_leer(CLIENTES_DIR / slug / "notas.md") or "")[:6000]


def redactar(slug: str, items: list[dict], generar=None, formato: str = "trafico") -> list[dict]:
    """[{titulo, texto: [str], url, pais}] en el orden recibido. Si Gemini
    falla o se salta un item, queda el titulo y el resumen tal cual."""
    from alerts.chat import leer_enlace
    if generar is None:
        from core.llm import LITE, generar as g
        generar = lambda p: g(p, modelo=LITE, json=True, schema=ESQUEMA)  # noqa: E731
    bloques = []
    for i, it in enumerate(items):
        pagina = leer_enlace(it["url"])[:5000] if it.get("url") else ""
        bloques.append(f"[{i}] {it['titulo']}\nResumen: {it.get('resumen') or '-'}\nTexto de la pagina: {pagina or '-'}")
    prompt = PROMPT.format(cliente=config.todos().get(slug, {}).get("nombre", slug), notas=_notas(slug),
                           estilo=ESTILO["vinetas" if slug in VINETAS else "parrafo"], items="\n\n".join(bloques))
    try:
        hechos = {r["n"]: r for r in json.loads(generar(prompt) or "[]") if isinstance(r, dict)}
    except Exception as e:  # sin Gemini sale igual, con lo que hay
        print(f"[trafico] redaccion fallo: {e}")
        hechos = {}
    out = []
    for i, it in enumerate(items):
        h = hechos.get(i) or {}
        texto = [t.strip() for t in h.get("texto") or [] if t.strip()] or [it.get("resumen") or ""]
        out.append({"titulo": (h.get("titulo") or it["titulo"]).strip(), "texto": texto,
                    "url": it.get("url"), "pais": it.get("pais") or ""})
    return out


def word(slug: str, redactados: list[dict], formato: str = "trafico") -> bytes:
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    doc.styles["Normal"].font.name = "Arial"
    doc.styles["Normal"].font.size = Pt(10)
    vinetas = slug in VINETAS
    ttw = formato == "ttw"
    if ttw:
        doc.add_paragraph().add_run("TOPICS TO WATCH – ANDEAN COUNTRIES").bold = True
    for pais in [p for p in PAISES if any(r["pais"] == p for r in redactados)] + [""]:
        grupo = [r for r in redactados if (r["pais"] or "") == pais]
        if not grupo:
            continue
        if ttw:
            doc.add_paragraph().add_run(PAISES_EN.get(pais, "OTHER")).bold = True
            for r in grupo:
                par = doc.add_paragraph("• ")
                par.add_run(r["titulo"].rstrip(".") + ". ").bold = True
                par.add_run(" ".join(r["texto"]) + (f" {r['url']}" if r["url"] else ""))
            continue
        doc.add_paragraph().add_run(f"{PAISES.get(pais, 'OTROS')} – ALERTAS DE INTERÉS").bold = True
        for r in grupo:
            doc.add_paragraph().add_run(r["titulo"]).bold = True
            for t in r["texto"]:
                doc.add_paragraph(f"• {t}" if vinetas else t)
            if r["url"]:
                doc.add_paragraph(r["url"])
            doc.add_paragraph()
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


if __name__ == "__main__":  # chequeo sin Gemini ni GitHub
    from docx import Document
    falso = lambda p: json.dumps([{"n": 0, "titulo": "T0", "texto": ["a", "b"]}])  # noqa: E731
    import alerts.chat as ch
    ch.leer_enlace = lambda u: "pagina"
    r = redactar("syngenta", [{"titulo": "x", "url": "http://a", "pais": "EC"}, {"titulo": "y", "resumen": "r", "pais": "PE"}], falso)
    assert r[0]["titulo"] == "T0" and r[0]["texto"] == ["a", "b"] and r[1]["texto"] == ["r"], r
    textos = [p.text for p in Document(io.BytesIO(word("bayer", r))).paragraphs]
    assert "PERÚ – ALERTAS DE INTERÉS" in textos and "• a" in textos and "http://a" in textos, textos
    textos = [p.text for p in Document(io.BytesIO(word("syngenta", r, "ttw"))).paragraphs]
    assert textos[0] == "TOPICS TO WATCH – ANDEAN COUNTRIES" and "• T0. a b http://a" in textos, textos
    seg = [{"pais": "PE", "pl": "00011-2026-2031-CD"}, {"pais": "EC", "pl": "474456"}]
    ag = [{"nombre": "Agraria", "pais": "PE", "fecha": "2026-11-05", "texto": "Predictamen PL 11/2026-CD", "puntos": []},
          {"nombre": "Educacion", "pais": "EC", "fecha": "2026-11-05", "texto": "proyectos 474456, 4744567", "puntos": ["Voz humana (Incode)"]},
          {"nombre": "Otra", "pais": "PE", "fecha": "2026-11-05", "texto": "PL 110/2026", "puntos": []}]
    en = _en_agenda("incode", seg, ag)
    assert [a["nombre"] for a in en] == ["Agraria", "Educacion"] and en[1]["puntos"] and en[1]["pls"] == ["EC 474456"], en
    print("ok")
