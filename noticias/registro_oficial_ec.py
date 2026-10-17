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
import functools
import html as _html
import logging
import re

from noticias.scraper import HEADERS, _make_session, parse_rss_feed
from noticias.temas import clasificar, es_norma_de_interes

log = logging.getLogger(__name__)

FEED_URL = "https://www.registroficial.gob.ec/feed/"
FUENTE_NOMBRE = "Registro Oficial EC (índice)"

# ============================================================
# PDFs reales por edición + anexos (Suplementos)
# ============================================================
# El post WP de cada edición nunca trae su PDF: solo un link genérico al
# "Manual de Documentos a Publicarse" (mismo en todo el sitio). Los PDFs
# reales solo aparecen en el widget de últimas ediciones (~12 items) de 2
# páginas de categoría fijas:
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
        # El ULTIMO match de la ventana: varios items del widget caen en los
        # mismos 400 chars y el primero es el del item anterior.
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


@functools.lru_cache(maxsize=1)
def _paddle_ocr():
    """Carga PaddleOCR una sola vez por proceso (bajar/cargar modelos tarda
    varios segundos). Modelos "small" de PP-OCRv6: ~2 s/pagina en CPU vs
    ~12 s con los "medium" por defecto, misma lectura en las pruebas
    (tildes y ñ incluidas). Los pasos de orientacion/enderezado van apagados:
    una pagina renderizada desde PDF ya viene derecha.
    Con paddlepaddle-gpu usa la GPU solo (~0,75 s/pagina en la RTX 2060)."""
    try:
        import torch  # noqa: F401  antes que paddle-gpu, si no WinError 127
    except ImportError:
        pass
    from paddleocr import PaddleOCR
    return PaddleOCR(
        text_detection_model_name="PP-OCRv6_small_det",
        text_recognition_model_name="PP-OCRv6_small_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def _ocr_page(page) -> str:
    """OCR de UNA página via PaddleOCR - nunca corre sobre el doc entero.
    Si paddleocr no esta instalado (solo se instala en CI, ver
    refrescar-pe.yml), falla silencioso (logueado) y se sigue sin ese texto."""
    try:
        import io
        import numpy as np
        from PIL import Image
        pix = page.get_pixmap(dpi=200)
        img = np.array(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
        return "\n".join(
            t for res in _paddle_ocr().predict(img) for t in res["rec_texts"]
        ).strip()
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


def build_edition_noticia(edition: dict, indice_text: str, temas: list[str],
                          pdf_excerpt: str | None = None,
                          interes: list[dict] = ()) -> dict:
    """Convierte una edición completa del RO en una noticia clasificada.

    El resumen empieza con el índice (~500 chars) — así el usuario puede leer
    qué normas se publicaron sin abrir el PDF — y si se pudo bajar/leer el
    PDF real de esa edición, se le agrega un extracto del texto legal
    completo (pdf_excerpt), no solo los títulos del índice.
    """
    resumen = re.sub(r"\s+", " ", indice_text).strip()[:500]
    if pdf_excerpt:
        resumen = f"{resumen}\n\n— Texto de la edición: {pdf_excerpt}"[:1500]
    titulo = edition.get("titulo", "").strip()
    tags = temas + ["registro-oficial", "normativa"]
    # Normas de interés de cliente van ADELANTE: el índice se recorta a 500
    # chars y lo que venía al final no llegaba al digest.
    if interes:
        lineas = [f"{n.get('entidad') or ''}: {n.get('codigo') or ''} {n['titulo']}".strip()
                  for n in interes]
        titulo = f"{titulo} — {lineas[0]}"
        if len(lineas) > 1:
            titulo += f" (+{len(lineas) - 1} más de interés)"
        resumen = f"Normas de interés: {' | '.join(lineas)}\n\n{resumen}"[:2000]
        tags.append("interes-cliente")
    return {
        "url": edition["url"],
        "titulo": titulo[:500],
        "resumen": resumen,
        "fecha_pub": edition.get("fecha_pub"),
        "autor": None,
        "tags": "|".join(tags),
    }


def _skip_metadata(lines: list[str]) -> list[str]:
    """Descarta líneas del header del post (autor, fecha, categoría)."""
    out = []
    for l in lines:
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
            interes = [n for n in parse_norms(lines) if es_norma_de_interes(n["titulo"])]
            if not temas and not interes:
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

            noticia = build_edition_noticia(ed, indice_text, temas, pdf_excerpt, interes)
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


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["sync"])
    p.add_argument("--db", default="proyectos.db")
    p.add_argument("--max-editions", type=int, default=20)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from noticias.db import Database
    with Database(args.db) as db:
        db.init_schema()
        stats = run_sync(db, max_editions=args.max_editions)
        print(f"RO sync: {stats}")
