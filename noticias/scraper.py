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
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
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


def _fecha_cercana(html_text: str, pos: int, ventana: int = 200) -> str | None:
    """Busca un <time datetime="..."> cerca de `pos` (offset del match del
    titular/link dentro de `html_text`) y lo parsea. Las paginas de listado
    tipicamente ponen la fecha justo antes o despues del titular/link, no
    en un bloque <article> limpio que se pueda aislar de forma confiable -
    por eso una ventana de caracteres alrededor, no _RE_ARTICLE (nunca
    matcheaba nada real, quedo sin usar)."""
    inicio = max(0, pos - ventana)
    fin = min(len(html_text), pos + ventana)
    m = _RE_TIME_TAG.search(html_text[inicio:fin])
    if not m:
        return None
    return _parse_pubdate(m.group(1))


def _add_item(out: list, seen: set, url: str, titulo: str, base_url: str,
              min_len: int, min_words: int, same_domain: bool = False,
              require_slug: bool = False, fecha_pub: str | None = None) -> None:
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
        # ponytail: sin <time> cerca en el listado queda None y se muestra
        # first_seen_at (fecha del scrape); backfill_fechas la repara despues.
        "fecha_pub": fecha_pub, "autor": None, "tags": None,
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
                  min_len=8, min_words=0,
                  fecha_pub=_fecha_cercana(html_text, m.start()))
        if len(out) >= max_items:
            return out
    # Pasada 2: <a href>titulo largo</a> del MISMO dominio (evita nav/portal)
    for m in _RE_ANCHOR_LINK.finditer(html_text):
        _add_item(out, seen_urls, m.group(1), m.group(2), base_url,
                  min_len=35, min_words=5, same_domain=True, require_slug=True,
                  fecha_pub=_fecha_cercana(html_text, m.start()))
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
# gob.pe escribe "setiembre" (variante peruana).
_MESES["setiembre"] = _MESES["septiembre"]


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
    if fuente.get("busqueda"):
        return _gobpe_busqueda(fuente, session, timeout)
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
            # gob.pe mezcla paginas institucionales estaticas (Mesa de Partes,
            # Registro de visitas...) sin fecha: viven bajo /pages/.
            if "/pages/" in href.group(1):
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


def _gobpe_busqueda(fuente: dict, session: requests.Session, timeout: int) -> list[dict]:
    """Normas de CUALQUIER institucion que contengan `busqueda` (texto completo).
    Sirve para las prepublicaciones ("disponen la publicacion del proyecto"):
    la norma antes de que salga. `exige` descarta el ruido de municipios cuyo
    texto no tiene la frase de verdad (la busqueda de gob.pe es difusa)."""
    params = [("contenido[]", "normas"), ("term", fuente["busqueda"]), ("sort_by", "recent")]
    try:
        r = session.get(GOBPE_API, params=params, timeout=timeout)
        r.raise_for_status()
        results = r.json()["data"]["attributes"]["results"]
    except Exception as e:
        log.warning("gobpe busqueda %r: %s", fuente["busqueda"], e)
        return []
    exige = re.compile(fuente.get("exige") or re.escape(fuente["busqueda"]), re.IGNORECASE)
    out = []
    for it in results:
        href = re.search(r'href=[\'"]([^\'"]+)', it.get("url", "") or "")
        content = _strip_html(it.get("content") or "")
        fecha = _parse_gobpe_date(it.get("publication"))
        if not href or not fecha or not exige.search(content):
            continue
        entidad = _strip_html(it.get("content_sub_title_card") or "")
        nombre = _strip_html(it.get("url") or "")
        out.append({"url": urljoin("https://www.gob.pe", href.group(1)),
                    "titulo": f"{entidad} — {nombre}: {content}"[:500],
                    "resumen": content[:500], "fecha_pub": fecha, "autor": None,
                    "tags": "normas|prepublicacion"})
    return out


def fetch_wpmedia(fuente: dict, session: requests.Session, timeout: int) -> list[dict]:
    """PDFs que sube una institucion con WordPress (wp-json/wp/v2/media): las
    resoluciones y los borradores en consulta aparecen aca antes que en el
    Registro Oficial (SPDP, Agrocalidad, SERCOP...)."""
    base = fuente["url"].rstrip("/")
    try:
        r = _get(session, f"{base}/wp-json/wp/v2/media?per_page=30&mime_type=application/pdf", timeout)
        r.raise_for_status()
        items = json.loads(r.content.decode("utf-8-sig"))  # algunos .gob.ec mandan BOM
    except Exception as e:
        log.warning("wpmedia %s: %s", fuente["nombre"], e)
        return []
    out = []
    for it in items:
        titulo = _strip_html((it.get("title") or {}).get("rendered") or "")
        # "23092026_062842_Borrador-Resolucion-Portabilidad-version-0" -> legible
        titulo = re.sub(r"^\d{8}_\d{6}_", "", titulo).replace("_", " ").replace("-", " ").strip()
        if not it.get("source_url") or not titulo:
            continue
        out.append({"url": it["source_url"], "titulo": f"{fuente['nombre']}: {titulo}"[:500],
                    "resumen": None, "fecha_pub": it.get("date"), "autor": None,
                    "tags": "normas|documento"})
    return out


OECE_API = "https://contratacionesabiertas.oece.gob.pe/api/v1/search"


def fetch_oece(fuente: dict, session: requests.Session, timeout: int,
               dias: int = 4) -> list[dict]:
    """Compras publicas de Peru (SEACE en formato OCDS, datos del mismo dia)
    por cada termino de `terminos`. La API ordena por relevancia, no por fecha:
    se recorren todas las paginas del año y se quedan las de los ultimos dias.
    ponytail: ~3 paginas de 100 por termino; con muchos terminos, pedirle a
    OECE un filtro por fecha si lo agregan."""
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    # OECE da 403 a IPs de datacenter (GitHub): en CI sale por WARP.
    proxy = os.environ.get("PROXY_BLOQUEADOS")
    proxies = {"http": proxy, "https": proxy} if proxy else None
    out, vistos = [], set()
    for termino in fuente["terminos"]:
        pagina = 1
        while pagina:
            try:
                r = session.get(OECE_API, params={"search": termino, "year": datetime.now().year,
                                                  "format": "json", "paginateBy": 100, "page": pagina},
                                timeout=timeout, proxies=proxies)
                r.raise_for_status()
                d = r.json()
            except Exception as e:
                log.warning("oece %r p%s: %s", termino, pagina, e)
                break
            for res in d.get("results", []):
                c = res.get("compiledRelease") or {}
                t = c.get("tender") or {}
                fecha = c.get("date") or ""
                if c.get("ocid") in vistos or not fecha:
                    continue
                try:
                    if datetime.fromisoformat(fecha) < datetime.fromisoformat(desde):
                        continue
                except ValueError:
                    continue
                vistos.add(c["ocid"])
                monto = (t.get("value") or {}).get("amount")
                comprador = (c.get("buyer") or {}).get("name") or ""
                out.append({
                    "url": f"https://contratacionesabiertas.oece.gob.pe/proceso/{c['ocid']}",
                    "titulo": f"Compra pública: {comprador} — {t.get('description') or t.get('title') or ''}"[:500],
                    "resumen": (f"{t.get('procurementMethodDetails') or ''} {t.get('title') or ''}"
                                + (f", S/ {monto:,.0f}" if monto else "")).strip()[:500],
                    "fecha_pub": fecha, "autor": comprador or None, "tags": "compra-publica"})
            pagina = (d.get("pagination") or {}).get("next_page_number")
    return out


def _get(session: requests.Session, url: str, timeout: int) -> requests.Response:
    """GET con fallback SSL: cloudscraper (la session normal de este modulo)
    impersona un fingerprint TLS de navegador para saltar Cloudflare, pero ese
    mismo fingerprint rompe el handshake TLS con algunos sitios .gob.ec.
    Reintenta una vez con una sesion sin cloudscraper.
    ponytail: una sesion plana nueva por reintento (sin pool ni reuso) porque
    esto es la excepcion, no el camino comun - si se vuelve frecuente, cachear
    una sesion "plana" de fallback por dominio."""
    try:
        return session.get(url, timeout=timeout)
    except requests.exceptions.SSLError:
        plain = requests.Session()
        plain.headers.update(HEADERS)
        return plain.get(url, timeout=timeout)


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
        r = _get(session, feed, timeout)
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
    if tipo == "gobpe":
        return fetch_gobpe(fuente, s, timeout=timeout)
    if tipo == "wpmedia":
        return fetch_wpmedia(fuente, s, timeout)
    if tipo == "oece":
        return fetch_oece(fuente, s, timeout)
    if tipo == "rss":
        url = fuente.get("rss_url") or fuente.get("url")
        if not url:
            return []
        try:
            r = _get(s, url, timeout)
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
                r = _get(s, page, timeout)
                feed = _discover_rss(r.text, page, s, timeout)
                if feed:
                    r2 = _get(s, feed, timeout)
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
            r = _get(s, url, timeout)
            r.raise_for_status()
            return parse_html_listing(r.text, url)
        except Exception as e:
            log.warning("HTML fail %s (%s): %s", fuente["nombre"], url, e)
            return []
    # 'twitter' / 'custom' / 'manual': sin captura generica
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
    # La tabla guarda lo comun; los parametros propios de un tipo (busqueda,
    # terminos de compras...) viven solo en fuentes.py.
    from noticias.fuentes import all_fuentes
    extra = {(f["pais"], f["nombre"]): f for f in all_fuentes()}
    for fuente in fuentes:
        fuente = {**extra.get((fuente["pais"], fuente["nombre"]), {}), **fuente}
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


# ============================================================
# Backfill de fechas: repara noticias con fecha_pub NULL
# ============================================================
# run_sync() solo re-toca los items mas recientes por fuente: una fila con
# fecha_pub NULL sale de esa ventana y nunca se repara. Esto visita cada
# articulo y saca la fecha de <time>/meta tags/texto en español.

_RE_META_FECHA = re.compile(
    r'<meta[^>]*?(?:property|name)=["\'](?:article:published_time|og:published_time|'
    r'publish-date|publish_date|date|DC\.date\.issued)["\'][^>]*?content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_RE_JSONLD_FECHA = re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.IGNORECASE)
_RE_TEXTO_FECHA_ES = re.compile(r"\d{1,2}\s+de\s+[a-zA-Zñ]+\s+de\s+\d{4}[^.<]{0,25}")


def _extraer_fecha_de_pagina(html_text: str) -> str | None:
    m = _RE_TIME_TAG.search(html_text)
    if m:
        f = _parse_pubdate(m.group(1))
        if f:
            return f
    m = _RE_META_FECHA.search(html_text)
    if m:
        f = _parse_pubdate(m.group(1))
        if f:
            return f
    m = _RE_JSONLD_FECHA.search(html_text)
    if m:
        f = _parse_pubdate(m.group(1))
        if f:
            return f
    texto = re.sub(r"<[^>]+>", " ", html_text)
    texto = re.sub(r"\s+", " ", texto)
    m = _RE_TEXTO_FECHA_ES.search(texto)
    if m:
        return _parse_gobpe_date(m.group(0))
    return None


def backfill_fechas(db, limit: int | None = None, max_workers: int = 8) -> dict:
    """Visita cada noticia (de fuente activa) con fecha_pub NULL y trata de
    recuperar su fecha real visitando el articulo directo. No inventa nada:
    si no encuentra fecha real, la deja como estaba. Devuelve stats dict."""
    rows = db.conn.execute(
        """SELECT n.id, n.url FROM noticias n
           JOIN noticias_fuentes f ON f.id = n.fuente_id
           WHERE n.fecha_pub IS NULL AND f.activa = 1
           ORDER BY n.id DESC"""
        + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()
    if not rows:
        return {"intentadas": 0, "recuperadas": 0}

    session = _make_session()
    session.headers.update(HEADERS)

    def _procesar(row_id: int, url: str) -> tuple[int, str | None]:
        try:
            r = _get(session, url, timeout=15)
            if r.status_code != 200:
                return row_id, None
            return row_id, _extraer_fecha_de_pagina(r.text)
        except Exception:
            return row_id, None

    recuperadas = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = {pool.submit(_procesar, r["id"], r["url"]): r for r in rows}
        for fut in as_completed(futuros):
            row_id, fecha = fut.result()
            if fecha:
                with db.tx() as c:
                    c.execute("UPDATE noticias SET fecha_pub=? WHERE id=?", (fecha, row_id))
                recuperadas += 1
    return {"intentadas": len(rows), "recuperadas": recuperadas}
