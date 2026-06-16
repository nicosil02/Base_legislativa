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
from urllib.parse import urljoin

import requests

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, application/atom+xml, "
              "text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
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


def parse_html_listing(html_text: str, base_url: str,
                       max_items: int = 30) -> list[dict]:
    """Scraping HTML genérico: extrae headings con link dentro de article-like
    containers. No reemplaza RSS pero da cobertura razonable para sitios sin feed."""
    out: list[dict] = []
    seen_urls: set[str] = set()
    # Buscar todos los <h1-4> con un <a> dentro (titulos clickeables)
    for m in _RE_HEADING_LINK.finditer(html_text):
        url = m.group(1)
        titulo = _strip_html(m.group(2))
        if not titulo or len(titulo) < 8:
            continue
        if "javascript:" in url.lower() or "#" == url:
            continue
        # Resolver URL relativa
        if not url.startswith("http"):
            url = urljoin(base_url, url)
        # Filtrar URLs que claramente no son noticias (categorias, login, etc.)
        if any(s in url.lower() for s in (
            "/category/", "/categoria/", "/login", "/wp-login",
            "/contacto", "/contact", "javascript:", "mailto:"
        )):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        out.append({
            "url": url,
            "titulo": titulo[:500],
            "resumen": None,
            "fecha_pub": None,
            "autor": None,
            "tags": None,
        })
        if len(out) >= max_items:
            break
    return out


# ============================================================
# Pipeline principal
# ============================================================

def fetch_fuente(fuente: dict, session: requests.Session | None = None,
                  timeout: int = 20) -> list[dict]:
    """Fetch + parse de una fuente. Devuelve list de items o [] si falla."""
    s = session or requests.Session()
    s.headers.update(HEADERS)
    tipo = (fuente.get("tipo") or "manual").lower()
    if tipo == "manual":
        return []
    if tipo == "rss":
        url = fuente.get("rss_url") or fuente.get("url")
        if not url:
            return []
        try:
            r = s.get(url, timeout=timeout)
            r.raise_for_status()
            return parse_rss_feed(r.text)
        except Exception as e:
            log.warning("RSS fail %s (%s): %s", fuente["nombre"], url, e)
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
    session = requests.Session()
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
