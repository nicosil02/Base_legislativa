"""Scraper del Registro Oficial de Ecuador.

Cada suplemento/edición se publica como post de WordPress en
registroficial.gob.ec. El índice completo del PDF (la "página 2") se
transcribe como texto plano dentro del <article> del post. Estructura:

    FUNCIÓN X               <- header (mayúscula)
    RESOLUCIONES:           <- subtipo (opcional)
    ENTIDAD EMISORA:        <- entidad (mayúscula, termina en ':')
    CODIGO-XX Título de la norma...

Este scraper:
  1) Lee el feed WP con las ediciones recientes.
  2) Abre cada post, extrae el índice.
  3) Parsea cada norma (entidad + código + título).
  4) Clasifica con noticias/temas.py: si matchea Salud/Agro/Digital/etc.
     la persiste como noticia en la tabla `noticias`.

Uso:
    python -m noticias.registro_oficial_ec sync
"""
from __future__ import annotations

import base64
import html as _html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from noticias.scraper import HEADERS, _make_session, parse_rss_feed
from noticias.temas import clasificar

log = logging.getLogger(__name__)

FEED_URL = "https://www.registroficial.gob.ec/feed/"
FUENTE_NOMBRE = "Registro Oficial EC (índice)"

# ============================================================
# PDFs reales por edición + anexos (Suplementos)
# ============================================================
# El post WP de cada edición (el que ya itera fetch_recent_editions) NUNCA
# trae su propio PDF inline - solo un link genérico al "Manual de Documentos
# a Publicarse" (mismo uuid en TODOS los posts del sitio, verificado
# 2026-09-12 en 3 posts reales distintos). Los PDFs reales por edición solo
# aparecen en 2 páginas de categoría fijas ("widget" de últimas ediciones,
# ~12 items, se actualiza en cada carga de página):
PDF_LANDING_PRINCIPAL = "https://www.registroficial.gob.ec/245427-2/"  # ediciones "Registro Oficial"
PDF_LANDING_SUPLEMENTO = "https://www.registroficial.gob.ec/255776-2/"  # "Suplemento" = los anexos

_PDF_LINK_RE = re.compile(
    r'<a[^>]*href=["\'](https://esacc\.corteconstitucional\.gob\.ec/storage/'
    r'api/v1/10_DWL_FL/[^"\']+)["\'][^>]*>Descargar</a>',
    re.IGNORECASE,
)
_PDF_NUMERO_RE = re.compile(r"N[º°o]\.?\s*(\d+)", re.IGNORECASE)  # cubre "Nº 367" (widget) y "No. 367" (titulo del post)
_PDF_PAGINAS_RE = re.compile(r"(\d+)\s*P[ÁA]GINAS", re.IGNORECASE)
_PDF_MANUAL_MARKER = "wbprov2023"  # carpeta del PDF generico "Manual de Documentos a Publicarse", no es una edicion real


def _decode_pdf_token(url: str) -> str:
    """El link de descarga trae un JSON (o JS-literal sin comillas en las
    keys, visto en vivo) en base64 al final del path - solo lo usamos para
    filtrar el Manual generico, no hace falta parsearlo como JSON real."""
    token = url.rstrip("/").rsplit("/", 1)[-1]
    padded = token + "=" * (-len(token) % 4)
    try:
        return base64.b64decode(padded).decode("utf-8", "replace")
    except Exception:
        return ""


def _parse_pdf_widget(html_text: str) -> list[dict]:
    """Extrae {numero, paginas, url} del widget de últimas ediciones (páginas
    de categoría PDF_LANDING_*). Descarta el ítem genérico del Manual."""
    out = []
    for m in _PDF_LINK_RE.finditer(html_text):
        url = m.group(1)
        if _PDF_MANUAL_MARKER in _decode_pdf_token(url):
            continue
        ctx = re.sub(r"<[^>]+>", " ", html_text[max(0, m.start() - 400):m.start()])
        ctx = _html.unescape(ctx)
        # OJO: tomar el ULTIMO match en la ventana, no el primero (.search) -
        # varios items del widget caen dentro de la misma ventana de 400
        # chars y .search() devolvía el numero/paginas del item ANTERIOR,
        # no el mas cercano al link actual (bug real, atrapado por el propio
        # self-check con 2 items sinteticos consecutivos).
        nums = _PDF_NUMERO_RE.findall(ctx)
        if not nums:
            continue
        pags = _PDF_PAGINAS_RE.findall(ctx)
        out.append({
            "numero": nums[-1],
            "paginas": int(pags[-1]) if pags else None,
            "url": url,
        })
    return out


def fetch_pdf_index(session) -> dict:
    """{'principal': {numero: [urls]}, 'suplemento': {numero: [urls]}}.
    ponytail: solo cubre las ~12 ediciones más recientes de cada tipo (lo que
    el widget expone en vivo) - sin backfill de archivo histórico (el
    selector de año/mes del sitio es un widget AJAX propio del tema, su
    endpoint no está confirmado; no se intentó reversear, fuera de alcance de
    esta pasada)."""
    idx = {"principal": {}, "suplemento": {}}
    for tipo, url in (("principal", PDF_LANDING_PRINCIPAL),
                       ("suplemento", PDF_LANDING_SUPLEMENTO)):
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
        except Exception as e:
            log.warning("RO widget PDF (%s) fallo: %s", tipo, e)
            continue
        for item in _parse_pdf_widget(r.text):
            idx[tipo].setdefault(item["numero"], []).append(item["url"])
    return idx


OCR_MIN_CHARS = 20  # ponytail: umbral heuristico "pagina sin texto = escaneada". Subir si aparecen falsos negativos (paginas con poco texto real, ej. solo un titulo corto).


def _ocr_page(page) -> str:
    """OCR de UNA página via pytesseract - nunca corre sobre el doc entero.
    Requiere el binario tesseract-ocr instalado aparte (no viene con pip);
    si falta, falla silencioso (logueado) y se sigue sin ese texto."""
    try:
        import pytesseract
        from PIL import Image
        import io
        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang="spa").strip()
    except Exception as e:
        log.warning("OCR de pagina fallo: %s", e)
        return ""


def extract_pdf_text(pdf_bytes: bytes, max_chars: int = 4000) -> str:
    """Texto de un PDF pagina por pagina, con OCR puntual (no del doc
    completo) en las paginas que PyMuPDF no puede leer (imagen/escaneo)."""
    import pymupdf as fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        parts = []
        total = 0
        for page in doc:
            text = page.get_text().strip()
            if len(text) < OCR_MIN_CHARS:
                text = _ocr_page(page) or text
            if text:
                parts.append(text)
                total += len(text)
            if total >= max_chars:
                break
        return "\n".join(parts)[:max_chars]
    finally:
        doc.close()

# Líneas del post que son metadata del WordPress, no del índice del RO.
_METADATA_LINES = {
    "por", "|", "suplemento", "edición jurídica", "edicion juridica",
    "edición especial", "edicion especial", "edición constitucional",
    "edicion constitucional", "registro oficial", "índice mensual",
    "indice mensual",
}


def fetch_recent_editions(session, max_editions: int = 20) -> list[dict]:
    """Últimas ediciones del RO desde el feed WP."""
    r = session.get(FEED_URL, timeout=20)
    r.raise_for_status()
    return parse_rss_feed(r.text)[:max_editions]


def _extract_article_text(html: str) -> list[str]:
    m = re.search(r"<article\b[^>]*>(.*?)</article>", html, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    text = re.sub(r"<[^>]+>", "\n", m.group(1))
    text = _html.unescape(text)
    return [l.strip() for l in text.splitlines() if l.strip()]


def parse_norms(lines: list[str]) -> list[dict]:
    """Convierte líneas del índice en items estructurados.

    Devuelve dicts con keys: funcion, entidad, codigo, titulo.
    Solo produce items que tienen código de norma reconocible."""
    norms: list[dict] = []
    funcion: str | None = None
    entidad: str | None = None

    for line in lines:
        low = line.lower().strip("| :,.")
        if low in _METADATA_LINES:
            continue
        # ponytail: descartar líneas 100% mayúsculas cortas — son headers
        # "FUNCIÓN X" o subtipos "RESOLUCIONES:". Las guardamos como
        # contexto.
        if line.isupper() or line.endswith(":"):
            if line.startswith("FUNCIÓN") or line.startswith("FUNCION"):
                funcion = line.rstrip(":")
                entidad = None
            elif line.endswith(":") and len(line) > 3:
                entidad = line.rstrip(":")
            continue
        # Norma: patrón código + espacio + descripción.
        # Códigos vistos: NAC-DGERCGC26-00000028, CPCCS-PLE-SG-029-O-2026-0225,
        # CNE-PRE-2026-0026-RS, No. 000-2026, Resolución 001-CS-CPCCS-2026, etc.
        m = re.match(
            r"^(?:No\.?\s*)?([A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+){1,})\s+(.+)$",
            line,
        )
        if m:
            norms.append({
                "funcion": funcion,
                "entidad": entidad,
                "codigo": m.group(1),
                "titulo": m.group(2).strip(),
            })
            continue
        # Fallback: si es una línea larga con verbo típico ("Se reforma",
        # "Se convoca", "Se aprueba", "Se autoriza"), la guardamos con
        # entidad como contexto, sin código estructurado.
        if entidad and re.search(r"\b(se\s+(?:reforma|convoca|aprueba|autoriza|expide|deroga|modifica|declara|delega|nombra|designa|resuelve))\b", line, re.I):
            norms.append({
                "funcion": funcion, "entidad": entidad,
                "codigo": None, "titulo": line[:400],
            })

    return norms


def build_noticia(edition: dict, norm: dict, temas: list[str]) -> dict:
    """Convierte una norma matcheada en dict listo para upsert_noticia."""
    ed_titulo = edition.get("titulo", "").strip()
    entidad = norm.get("entidad") or norm.get("funcion") or ""
    codigo = norm.get("codigo") or ""
    titulo_norma = norm["titulo"][:300]
    titulo = f"{ed_titulo} — {entidad}: {titulo_norma}"[:500]
    anchor = codigo or titulo_norma[:40]
    return {
        "url": f"{edition['url']}#{re.sub(r'[^A-Za-z0-9-]', '', anchor)[:80]}",
        "titulo": titulo,
        "resumen": f"[{entidad}] {codigo} {titulo_norma}".strip()[:500],
        "fecha_pub": edition.get("fecha_pub"),
        "autor": None,
        "tags": "|".join(temas + ["registro-oficial", "normativa"]),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_edition_noticia(edition: dict, indice_text: str, temas: list[str],
                          pdf_excerpt: str | None = None) -> dict:
    """Convierte una edición completa del RO en una noticia clasificada.

    El resumen empieza con el índice (~500 chars) — así el usuario puede leer
    qué normas se publicaron sin abrir el PDF — y si se pudo bajar/leer el
    PDF real de esa edición, se le agrega un extracto del texto legal
    completo (pdf_excerpt), no solo los títulos del índice.
    """
    resumen = re.sub(r"\s+", " ", indice_text).strip()[:500]
    if pdf_excerpt:
        resumen = f"{resumen}\n\n— Texto de la edición: {pdf_excerpt}"[:1500]
    return {
        "url": edition["url"],
        "titulo": edition.get("titulo", "").strip()[:500],
        "resumen": resumen,
        "fecha_pub": edition.get("fecha_pub"),
        "autor": None,
        "tags": "|".join(temas + ["registro-oficial", "normativa"]),
    }


def _skip_metadata(lines: list[str]) -> list[str]:
    """Descarta líneas del header del post (autor, fecha, categoría)."""
    skip_next_bar = False
    out = []
    for i, l in enumerate(lines):
        low = l.lower().strip("| :,.")
        if low in _METADATA_LINES:
            continue
        # descartar "Moises Gutierrez" y "3 Ago 2026" (patrón del WP author line)
        if re.match(r"^\d{1,2}\s+\w+\s+\d{4}$", l):
            continue
        if l in {"Moises Gutierrez"}:
            continue
        out.append(l)
    return out


def run_sync(db, max_editions: int = 20) -> dict:
    """Corre el sync: fetch feed → cada edición se clasifica y se guarda si
    matchea algún sector."""
    stats = {"editions": 0, "matches": 0, "nuevas": 0, "actualizadas": 0, "errores": 0}
    session = _make_session()
    session.headers.update(HEADERS)

    fuente_id = db.upsert_fuente({
        "categoria": "Institucion", "pais": "EC",
        "nombre": FUENTE_NOMBRE,
        "url": "https://www.registroficial.gob.ec/",
        "rss_url": FEED_URL, "tipo": "custom", "activa": 1,
        "notas": "1 noticia por edición; resumen = índice; tag=sector matcheado",
    })

    editions = fetch_recent_editions(session, max_editions=max_editions)
    stats["editions"] = len(editions)
    log.info("RO ediciones a procesar: %d", len(editions))
    pdf_index = fetch_pdf_index(session)

    for ed in editions:
        try:
            r = session.get(ed["url"], timeout=20)
            r.raise_for_status()
            lines = _skip_metadata(_extract_article_text(r.text))
            # ponytail: sacamos la 1ra línea (título repetido del post)
            if lines and lines[0].startswith(ed.get("titulo", "")[:15]):
                lines = lines[1:]
            indice_text = " ".join(lines)
            if not indice_text.strip():
                continue

            temas = clasificar(indice_text, None)
            if not temas:
                continue  # sin sector de interés, ignoramos
            stats["matches"] += 1

            # Solo bajamos/leemos el PDF real para ediciones que ya matchearon
            # un tema por el índice (no vale la pena el ancho de banda/OCR en
            # ediciones que igual no se van a notificar).
            pdf_excerpt = None
            m_num = _PDF_NUMERO_RE.search(ed.get("titulo", ""))
            if m_num:
                tipo = "suplemento" if "suplemento" in ed.get("titulo", "").lower() else "principal"
                urls = pdf_index.get(tipo, {}).get(m_num.group(1))
                if urls:
                    # ponytail: si hubo >1 Suplemento el mismo día/número
                    # (ej. "Segundo Suplemento No. 367", "Tercer Suplemento
                    # No. 367"), el widget no distingue cuál PDF es cuál
                    # ordinal - se usa el primero disponible sin asignación
                    # fina. Mejorar si hace falta precisión por-suplemento.
                    try:
                        r_pdf = session.get(urls[0], timeout=30)
                        r_pdf.raise_for_status()
                        pdf_excerpt = extract_pdf_text(r_pdf.content) or None
                    except Exception as e:
                        log.warning("PDF fetch/extract fallo (%s): %s", ed["url"], e)

            noticia = build_edition_noticia(ed, indice_text, temas, pdf_excerpt)
            is_new, changed = db.upsert_noticia(fuente_id, noticia)
            if is_new:
                stats["nuevas"] += 1
            elif changed:
                stats["actualizadas"] += 1
            log.info("[%s] temas=%s", ed["titulo"][:40], temas)
        except Exception as e:
            log.warning("RO error en %s: %s", ed.get("url"), e)
            stats["errores"] += 1
            continue

    log.info("RO sync: %s", stats)
    return stats


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la lógica no trivial)
# ============================================================

def _demo():
    """Test rápido de parse_norms con datos reales del RO."""
    sample_lines = [
        "FUNCIÓN EJECUTIVA",
        "RESOLUCIONES:",
        "SERVICIO DE RENTAS INTERNAS:",
        "NAC-DGERCGC26-00000028 Se reforma la Resolución NAC-DGERCGC26-00000024",
        "FUNCIÓN DE TRANSPARENCIA Y CONTROL SOCIAL",
        "CONSEJO DE PARTICIPACIÓN CIUDADANA Y CONTROL SOCIAL:",
        "CPCCS-PLE-SG-029-O-2026-0225 Se convoca a la ciudadanía",
    ]
    norms = parse_norms(sample_lines)
    assert len(norms) == 2, f"esperaba 2 normas, hay {len(norms)}"
    assert norms[0]["funcion"] == "FUNCIÓN EJECUTIVA"
    assert norms[0]["entidad"] == "SERVICIO DE RENTAS INTERNAS"
    assert norms[0]["codigo"] == "NAC-DGERCGC26-00000028"
    assert "reforma" in norms[0]["titulo"].lower()
    assert norms[1]["entidad"] == "CONSEJO DE PARTICIPACIÓN CIUDADANA Y CONTROL SOCIAL"
    print("OK parse_norms:", len(norms), "normas")

    _demo_pdf_widget()
    _demo_extract_pdf_text()


def _demo_pdf_widget():
    """_parse_pdf_widget contra un snippet HTML calcado del widget real
    (estructura verificada en vivo contra registroficial.gob.ec, 2026-09-12).
    También confirma que el PDF genérico del Manual (mismo uuid en todo el
    sitio) se descarta y no cuenta como edición real."""
    html_sample = (
        '<div class="row_post_imagen_texto"> Registro Oficial '
        '<span>Año II - Nº 367</span> viernes, 11 septiembre 2026 69 PÁGINAS '
        '<a href="https://esacc.corteconstitucional.gob.ec/storage/api/v1/'
        '10_DWL_FL/eyJjYXJwZXRhIjoicm8iLCJ1dWlkIjoiYWJjLnBkZiJ9">Descargar</a></div>'
        '<div class="row_post_imagen_texto"> Registro Oficial '
        '<span>Año II - Nº 366</span> jueves, 10 septiembre 2026 60 PÁGINAS '
        '<a href="https://esacc.corteconstitucional.gob.ec/storage/api/v1/'
        '10_DWL_FL/eyJjYXJwZXRhIjoicm8iLCJ1dWlkIjoiZGVmLnBkZiJ9">Descargar</a></div>'
        '<a href="https://esacc.corteconstitucional.gob.ec/storage/api/v1/'
        '10_DWL_FL/eyJjYXJwZXRhIjoid2Jwcm92MjAyMyIsInV1aWQiOiJtYW51YWwtZ2VuZXJpY28ucGRmIn0=">'
        'Descargar</a>'  # Manual generico (decodifica a carpeta=wbprov2023) - debe descartarse
    )
    items = _parse_pdf_widget(html_sample)
    assert len(items) == 2, f"esperaba 2 ediciones reales (sin el manual), hay {len(items)}"
    assert items[0]["numero"] == "367" and items[0]["paginas"] == 69
    assert items[1]["numero"] == "366" and items[1]["paginas"] == 60
    assert all(_PDF_MANUAL_MARKER not in i["url"] for i in items)
    print("OK _parse_pdf_widget:", len(items), "ediciones (manual descartado)")


def _demo_extract_pdf_text():
    """extract_pdf_text sobre un PDF sintético de 2 páginas: una con texto
    real (no debe pasar por OCR) y una sin capa de texto (imagen pura, debe
    disparar el fallback OCR). Monkeypatchea _ocr_page para no depender del
    binario tesseract-ocr (no instalado en todos los entornos dev/test) -
    igual ejercita la lógica real de decisión por-página de extract_pdf_text."""
    import pymupdf as fitz

    doc = fitz.open()
    p0 = doc.new_page()
    p0.insert_text((72, 72), "Texto real de una norma, con contenido de sobra.")
    p1 = doc.new_page()  # sin insert_text -> get_text() vacío, simula pagina escaneada
    pdf_bytes = doc.tobytes()
    doc.close()

    calls = []
    orig_ocr = globals()["_ocr_page"]
    globals()["_ocr_page"] = lambda page: (calls.append(page.number), "TEXTO-OCR-SIMULADO")[1]
    try:
        text = extract_pdf_text(pdf_bytes)
    finally:
        globals()["_ocr_page"] = orig_ocr

    assert "Texto real de una norma" in text, "pagina con texto real deberia pasar tal cual"
    assert "TEXTO-OCR-SIMULADO" in text, "pagina sin texto deberia haber disparado OCR"
    assert calls == [1], f"OCR deberia dispararse solo en la pagina 1 (sin texto), disparo en {calls}"
    print("OK extract_pdf_text: pagina con texto intacta, OCR disparado solo en la pagina vacia")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["sync", "demo"])
    p.add_argument("--db", default="proyectos.db")
    p.add_argument("--max-editions", type=int, default=20)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "demo":
        _demo()
    else:
        from noticias.db import Database
        with Database(args.db) as db:
            db.init_schema()
            stats = run_sync(db, max_editions=args.max_editions)
            print(f"RO sync: {stats}")
