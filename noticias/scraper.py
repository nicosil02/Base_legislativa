"""Scrapers genericos de noticias.

Estrategias soportadas:
  - rss:  parser de RSS 2.0 / Atom (la mayoria de medios y WordPress)
  - html: scraping HTML con selectores comunes (titulo + link + fecha + resumen)

El scraping HTML usa heuristica generica:
  - Buscar <article> o tags semanticos (main, section)
  - Extraer titulos en h1/h2/h3 con su <a href>
  - Fecha en <time datetime> o meta tags
  - Resumen en primer <p>
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse

import requests

# cloudscraper resuelve el challenge JS de Cloudflare (usado por El Productor,
# CONAIE, Criptonoticias, etc.). Es drop-in de requests.Session: para sitios
# sin CF funciona igual que requests, para sitios con CF hace el bypass
# automatico. Fallback a requests si cloudscraper no esta instalado.
try:
    import cloudscraper as _cs

    def _make_session() -> requests.Session:
        return _cs.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True},
        )
except ImportError:
    def _make_session() -> requests.Session:
        return requests.Session()

log = logging.getLogger(__name__)

HEADERS = {
    # UA de Linux Chrome: menos filtrado por firewalls como CEPES/CONAIE que
    # bloquean con el UA de Windows viejo. Referer=google.com ayuda con Wordfence.
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, application/atom+xml, "
              "text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}


def _unescape(s: str) -> str:
    """Unescape HTML entities and limpia whitespace."""
    if not s:
        return ""
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _strip_cdata(s: str) -> str:
    """Quita <![CDATA[ ]]> wrapper."""
    if not s:
        return ""
    m = re.match(r"^\s*<!\[CDATA\[(.*?)\]\]>\s*$", s, re.DOTALL)
    if m:
        return m.group(1)
    return s


def _strip_html(s: str) -> str:
    """Strip tags HTML + entities + colapsa whitespace."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_pubdate(s: str) -> str | None:
    """Parsea pubDate del RSS (RFC822) o ISO 8601 a ISO UTC."""
    if not s:
        return None
    s = s.strip()
    # Probar RFC822 (formato RSS estandar)
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        pass
    # ISO 8601 (Atom o WP custom)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


# ============================================================
# RSS scraper
# ============================================================

# Patrones para extraer items de RSS 2.0 y Atom
_RSS_ITEM = re.compile(r"<item\b[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)
_ATOM_ENTRY = re.compile(r"<entry\b[^>]*>(.*?)</entry>", re.DOTALL | re.IGNORECASE)
# Tags dentro de cada item
_RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_RE_LINK = re.compile(r"<link[^>]*>(.*?)</link>", re.DOTALL | re.IGNORECASE)
_RE_ATOM_LINK = re.compile(
    r'<link[^>]*?(?:rel=[\'"]alternate[\'"][^>]*)?href=[\'"]([^\'"]+)[\'"]',
    re.DOTALL | re.IGNORECASE,
)
_RE_PUBDATE = re.compile(
    r"<(?:pubDate|published|dc:date|updated)[^>]*>(.*?)</(?:pubDate|published|dc:date|updated)>",
    re.DOTALL | re.IGNORECASE,
)
_RE_DESC = re.compile(
    r"<(?:description|summary|content:encoded)[^>]*>(.*?)</(?:description|summary|content:encoded)>",
    re.DOTALL | re.IGNORECASE,
)
_RE_AUTHOR = re.compile(
    r"<(?:author|dc:creator)[^>]*>(.*?)</(?:author|dc:creator)>",
    re.DOTALL | re.IGNORECASE,
)
_RE_CAT = re.compile(r"<category[^>]*>(.*?)</category>", re.DOTALL | re.IGNORECASE)


def parse_rss_feed(xml: str, max_items: int = 100) -> list[dict]:
    """Parsea un feed RSS/Atom. Devuelve list de dicts:
      {url, titulo, resumen, fecha_pub, autor, tags}"""
    items_html = _RSS_ITEM.findall(xml)
    is_atom = False
    if not items_html:
        items_html = _ATOM_ENTRY.findall(xml)
        is_atom = True
    out: list[dict] = []
    for item in items_html[:max_items]:
        # Titulo
        m = _RE_TITLE.search(item)
        titulo = _unescape(_strip_cdata(m.group(1))) if m else ""
        if not titulo:
            continue
        # Link
        if is_atom:
            m = _RE_ATOM_LINK.search(item)
            link = m.group(1).strip() if m else ""
        else:
            m = _RE_LINK.search(item)
            link = _unescape(_strip_cdata(m.group(1))) if m else ""
        if not link:
            continue
        # PubDate
        m = _RE_PUBDATE.search(item)
        fecha = _parse_pubdate(_unescape(_strip_cdata(m.group(1)))) if m else None
        # Descripcion
        m = _RE_DESC.search(item)
        resumen = _strip_html(_strip_cdata(m.group(1)))[:500] if m else None
        # Autor
        m = _RE_AUTHOR.search(item)
        autor = _unescape(_strip_cdata(m.group(1)))[:120] if m else None
        # Tags
        tags = []
        for m in _RE_CAT.finditer(item):
            t = _unescape(_strip_cdata(m.group(1)))
            if t:
                tags.append(t)
        out.append({
            "url": link,
            "titulo": titulo[:500],
            "resumen": resumen,
            "fecha_pub": fecha,
            "autor": autor,
            "tags": "|".join(tags[:10]) if tags else None,
        })
    return out


# ============================================================
# HTML scraper (heuristica generica)
# ============================================================

# Patrones HTML comunes en sitios de noticias
_RE_ARTICLE = re.compile(
    r'<article[^>]*>.*?</article>|'
    r'<div[^>]*?class=[\'"][^\'"]*?(?:post|entry|article|news-item|noticia)[^\'"]*?[\'"][^>]*>',
    re.DOTALL | re.IGNORECASE,
)
_RE_HEADING_LINK = re.compile(
    r'<h[1-4][^>]*>\s*<a[^>]*?href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_RE_TIME_TAG = re.compile(
    r'<time[^>]*?datetime=[\'"]([^\'"]+)[\'"]',
    re.IGNORECASE,
)


_RE_ANCHOR_LINK = re.compile(
    r'<a\b[^>]*?href=[\'"]([^\'"#]+)[\'"][^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
# URLs que claramente no son noticias (nav, login, categorias, social, etc.)
_NAV_BLACKLIST = (
    "/category/", "/categoria/", "/categorias/", "/tag/", "/etiqueta/",
    "/login", "/wp-login", "/contacto", "/contact", "javascript:", "mailto:",
    "/author/", "/autor/", "/page/", "/feed", "/rss", ".pdf", ".jpg", ".png",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "linkedin.com", "whatsapp", "/buscar", "/search", "/nosotros", "/quienes",
)


def _has_slug(url: str) -> bool:
    """True si algún segmento del path parece slug de artículo (multi-palabra
    con guiones, p.ej. .../despachos-via-maritima-concentraron). Distingue
    noticias reales de links de menú (/, /quienes-somos, /noticias)."""
    path = urlparse(url).path
    return any(seg.count("-") >= 2 for seg in path.split("/"))


def _add_item(out: list, seen: set, url: str, titulo: str, base_url: str,
              min_len: int, min_words: int, same_domain: bool = False,
              require_slug: bool = False) -> None:
    """Valida + normaliza un (url, titulo) candidato y lo agrega a `out`."""
    titulo = _strip_html(titulo)
    if not titulo or len(titulo) < min_len:
        return
    if min_words and len(titulo.split()) < min_words:
        return
    if not url or url.startswith(("javascript:", "#", "mailto:")):
        return
    if not url.startswith("http"):
        url = urljoin(base_url, url)
    if any(s in url.lower() for s in _NAV_BLACKLIST):
        return
    # same_domain: en la pasada laxa solo aceptamos enlaces del propio sitio.
    # Los portales gob.ec (JS-rendered) no traen noticias en el HTML estatico
    # pero sí decenas de links a servicios cross-domain (Quipux, Aduana, etc.);
    # exigir mismo dominio descarta esa basura y deja los artículos reales.
    if same_domain:
        host = urlparse(url).netloc.lower().replace("www.", "")
        base = urlparse(base_url).netloc.lower().replace("www.", "")
        if host and base and host != base:
            return
    if require_slug and not _has_slug(url):
        return
    if url in seen:
        return
    seen.add(url)
    out.append({
        "url": url, "titulo": titulo[:500], "resumen": None,
        "fecha_pub": None, "autor": None, "tags": None,
    })


def parse_html_listing(html_text: str, base_url: str,
                       max_items: int = 30) -> list[dict]:
    """Scraping HTML genérico. Dos pasadas, de mayor a menor precisión:
      1) <h1-4> con <a> dentro (titulares semánticos clásicos).
      2) Fallback: cualquier <a href>texto largo</a> que parezca titular.
         Muchos medios (p.ej. Agraria.pe) ponen el título en el <a> directo,
         sin heading — la pasada 1 no los ve. La pasada 2 los recupera con
         filtros estrictos (largo + nº palabras + blacklist de nav) para no
         meter basura. No funciona en sitios JS-rendered (gob.ec, El Peruano
         Normas): ahí el HTML estático no trae los artículos."""
    out: list[dict] = []
    seen_urls: set[str] = set()
    # Pasada 1: <hN><a>
    for m in _RE_HEADING_LINK.finditer(html_text):
        _add_item(out, seen_urls, m.group(1), m.group(2), base_url,
                  min_len=8, min_words=0)
        if len(out) >= max_items:
            return out
    # Pasada 2: <a href>titulo largo</a> del MISMO dominio (evita nav/portal)
    for m in _RE_ANCHOR_LINK.finditer(html_text):
        _add_item(out, seen_urls, m.group(1), m.group(2), base_url,
                  min_len=35, min_words=5, same_domain=True, require_slug=True)
        if len(out) >= max_items:
            break
    return out


# ============================================================
# gob.pe: API JSON unificada (noticias + normas) por institucion
# ============================================================
# Los portales gob.pe son Angular (JS) — el HTML estatico no trae noticias,
# pero exponen busquedas.json. Un solo adaptador cubre TODAS las instituciones
# (MINSA, MIDAGRI, PRODUCE, SENASA, MEF, ...). El slug sale del path de la url.

GOBPE_API = "https://www.gob.pe/busquedas.json"
_MESES = {m: i for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
     "septiembre", "octubre", "noviembre", "diciembre"], 1)}


def _gobpe_slug(url: str | None) -> str | None:
    m = re.search(r"/institucion/([^/?#]+)", url or "")
    if m:
        return m.group(1)
    m = re.search(r"gob\.pe/([^/?#]+)", url or "")  # forma corta gob.pe/minsa
    return m.group(1) if m else None


def _parse_gobpe_date(s: str | None) -> str | None:
    """ '2 de diciembre de 2024 - 6:29 p. m.' -> '2024-12-02T00:00:00Z'.
    Descarta la hora (suficiente para monitoreo diario)."""
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s+de\s+([a-zñ]+)\s+de\s+(\d{4})", s.lower())
    if not m:
        return None
    mes = _MESES.get(m.group(2))
    if not mes:
        return None
    return f"{int(m.group(3)):04d}-{mes:02d}-{int(m.group(1)):02d}T00:00:00Z"


def fetch_gobpe(fuente: dict, session: requests.Session,
                timeout: int = 20) -> list[dict]:
    slug = _gobpe_slug(fuente.get("url"))
    if not slug:
        return []
    # normas solo para reguladores (salud/agro/financiero); el resto seria ruido.
    cat = (fuente.get("categoria") or "").lower()
    tipos = ["noticias"]
    if any(k in cat for k in ("salud", "agrari", "kyc", "aml")):
        tipos.append("normas")
    out: list[dict] = []
    for tipo in tipos:
        # OJO: sort_by=published_date NO ordena por fecha (devuelve normas de
        # 2020/2024). sort_by=recent sí trae lo más nuevo primero — crítico
        # para que las normas caigan dentro de la ventana y no las purgue.
        params = [("contenido[]", tipo), ("institucion[]", slug),
                  ("sort_by", "recent")]
        try:
            r = session.get(GOBPE_API, params=params, timeout=timeout)
            r.raise_for_status()
            results = r.json()["data"]["attributes"]["results"]
        except Exception as e:
            log.warning("gobpe %s/%s: %s", slug, tipo, e)
            continue
        for it in results:
            href = re.search(r'href=[\'"]([^\'"]+)', it.get("url", "") or "")
            nombre = _strip_html(it.get("name_with_parent") or "")
            content = _strip_html(it.get("content") or "")
            # En normas, name_with_parent es solo el codigo (ej "0397-2024-MIDAGRI");
            # la descripcion real esta en content. Mostramos "codigo — descripcion"
            # para que el titulo sea legible y clasificable por tema.
            if tipo == "normas":
                titulo = f"{nombre} — {content}" if (nombre and content) else (content or nombre)
            else:
                titulo = nombre
            if not href or not titulo:
                continue
            out.append({
                "url": urljoin("https://www.gob.pe", href.group(1)),
                "titulo": titulo[:500],
                "resumen": content[:500] or None,
                "fecha_pub": _parse_gobpe_date(it.get("publication")),
                "autor": None,
                "tags": tipo,  # 'noticias' | 'normas' (para badge/filtro en UI)
            })
    return out


def _discover_rss(html_text: str, base_url: str,
                  session: requests.Session, timeout: int) -> str | None:
    """Autodiscovery: <link rss> o /feed/ (WordPress). Auto-sana feeds rotos."""
    m = re.search(
        r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>',
        html_text, re.IGNORECASE)
    if m:
        h = re.search(r'href=["\']([^"\']+)', m.group(0))
        if h:
            return urljoin(base_url, h.group(1))
    feed = urljoin(base_url, "/feed/")
    try:
        r = session.get(feed, timeout=timeout)
        if r.ok and ("<rss" in r.text[:400] or "<feed" in r.text[:400]):
            return feed
    except Exception:
        pass
    return None


# ============================================================
# Pipeline principal
# ============================================================

def fetch_fuente(fuente: dict, session: requests.Session | None = None,
                  timeout: int = 20) -> list[dict]:
    """Fetch + parse de una fuente. Devuelve list de items o [] si falla."""
    s = session or _make_session()
    s.headers.update(HEADERS)
    tipo = (fuente.get("tipo") or "manual").lower()
    if tipo == "manual":
        return []
    if tipo in ("gobpe", "api"):
        return fetch_gobpe(fuente, s, timeout=timeout)
    if tipo == "rss":
        url = fuente.get("rss_url") or fuente.get("url")
        if not url:
            return []
        try:
            r = s.get(url, timeout=timeout)
            r.raise_for_status()
            items = parse_rss_feed(r.text)
            if items:
                return items
        except Exception as e:
            log.warning("RSS fail %s (%s): %s", fuente["nombre"], url, e)
        # Feed vacio o roto: intentar autodiscovery desde la pagina principal.
        page = fuente.get("url")
        if page and page != url:
            try:
                r = s.get(page, timeout=timeout)
                feed = _discover_rss(r.text, page, s, timeout)
                if feed:
                    r2 = s.get(feed, timeout=timeout)
                    r2.raise_for_status()
                    return parse_rss_feed(r2.text)
            except Exception as e:
                log.warning("autodiscover fail %s: %s", fuente["nombre"], e)
        return []
    if tipo == "html":
        url = fuente.get("url")
        if not url:
            return []
        try:
            r = s.get(url, timeout=timeout)
            r.raise_for_status()
            return parse_html_listing(r.text, url)
        except Exception as e:
            log.warning("HTML fail %s (%s): %s", fuente["nombre"], url, e)
            return []
    # 'twitter' / 'api' / otros no implementados
    return []


def run_sync(db, pais: str | None = None,
             categoria: str | None = None) -> dict:
    """Itera fuentes scrapeables y captura noticias.

    Devuelve stats dict.
    """
    stats = {"fuentes": 0, "items_vistos": 0, "nuevos": 0, "actualizados": 0,
             "errores": 0}
    fuentes = db.list_fuentes(
        pais=pais, categoria=categoria,
        solo_activas=True, solo_scrapeables=True,
    )
    session = _make_session()
    session.headers.update(HEADERS)
    for fuente in fuentes:
        stats["fuentes"] += 1
        try:
            items = fetch_fuente(fuente, session=session)
        except Exception as e:
            log.warning("error fuente %s: %s", fuente["nombre"], e)
            stats["errores"] += 1
            continue
        if not items:
            continue
        log.info("[%s] %d items", fuente["nombre"], len(items))
        for item in items:
            stats["items_vistos"] += 1
            try:
                is_new, changed = db.upsert_noticia(fuente["id"], item)
                if is_new:
                    stats["nuevos"] += 1
                elif changed:
                    stats["actualizados"] += 1
            except Exception as e:
                log.warning("upsert fail %s: %s", item.get("url"), e)
                stats["errores"] += 1
    return stats
