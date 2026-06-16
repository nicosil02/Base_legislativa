"""Scraper de mesas de trabajo + eventos del Congreso PE.

Estrategia:
1. RSS feed `/agenda/feed/[?paged=N]` da la lista de los ultimos posts
   con url + titulo + pubDate. Es liviano (~10 KB por pagina, 10 items).
2. Para cada URL nueva, fetcheamos el HTML del post individual y parseamos
   los <p> dentro de entry-content. Estructura tipica:
     <p>"Tema del evento"</p>
     <p>Comisión organizadora</p>
     <p>Presidenta: Congresista X (Bancada Y)</p>
     <p>Edificio Y.</p>
     <p>Sala Z</p>
3. Para fecha+hora, el listado /agenda/?date-agenda=YYYY-MM-DD tiene
   "HORA 11:00 AM" como texto. Pero como el server-side filter no responde
   a query string (filtro JS-only), parseamos la pagina /agenda/ default
   que muestra el dia corriente.

Implementacion pragmatica: usamos RSS para descubrimiento + detalle del
post individual para extraer todos los campos.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Iterator

import requests

log = logging.getLogger(__name__)

BASE = "https://comunicaciones.congreso.gob.pe"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9",
}


# Patron para extraer <item>...</item> del RSS feed
_RSS_ITEM = re.compile(r"<item>(.*?)</item>", re.DOTALL)
_RSS_TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_RSS_LINK = re.compile(r"<link>(.*?)</link>", re.DOTALL)
_RSS_PUBDATE = re.compile(r"<pubDate>(.*?)</pubDate>", re.DOTALL)

# Patrones del listado /agenda/ para extraer fecha+hora+tema+lugar
# Estructura por evento: HORA X TEMA Y ORGANIZA Z LUGAR W
_LISTING_EVENT = re.compile(
    r"HORA\s+(?P<hora>[0-9: APM]+?)\s+"
    r"TEMA\s+(?P<tema>.*?)\s+"
    r"ORGANIZA\s+(?P<organiza>.*?)\s+"
    r"LUGAR\s+(?P<lugar>.*?)(?=\s+HORA\s+|\s*$)",
    re.DOTALL,
)
# Fecha de cabecera: "Lunes 25 de mayo" (sin año explicito)
_LISTING_FECHA = re.compile(
    r"\b(lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\s+"
    r"(\d{1,2})\s+de\s+"
    r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b",
    re.IGNORECASE,
)

MES_NUM = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}


def _strip_html(html: str) -> str:
    txt = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL)
    txt = re.sub(r"<style.*?</style>", " ", txt, flags=re.DOTALL)
    txt = re.sub(r"<[^>]+>", " ", txt)
    # Limpiar entities comunes
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'),
                     ("&#8220;", '"'), ("&#8221;", '"'), ("&#8217;", "'"),
                     ("&laquo;", "«"), ("&raquo;", "»"), ("&#039;", "'")):
        txt = txt.replace(ent, ch)
    return re.sub(r"\s+", " ", txt).strip()


def fetch_rss_page(paged: int = 1, session: requests.Session | None = None) -> str:
    """Devuelve el XML del RSS de la pagina dada (1-indexed)."""
    s = session or requests.Session()
    s.headers.update(HEADERS)
    url = f"{BASE}/agenda/feed/" if paged == 1 else f"{BASE}/agenda/feed/?paged={paged}"
    r = s.get(url, timeout=20)
    if r.status_code == 404:
        return ""  # paginas mas alla del archivo
    r.raise_for_status()
    return r.text


def iter_rss_items(paged: int = 1,
                    session: requests.Session | None = None) -> Iterator[dict]:
    """Yields {url, titulo, pub_date} de la pagina dada."""
    xml = fetch_rss_page(paged, session=session)
    if not xml:
        return
    for item_html in _RSS_ITEM.findall(xml):
        m_title = _RSS_TITLE.search(item_html)
        m_link = _RSS_LINK.search(item_html)
        m_pub = _RSS_PUBDATE.search(item_html)
        if not (m_title and m_link):
            continue
        titulo = _strip_html(m_title.group(1))
        url = m_link.group(1).strip()
        pub_date = m_pub.group(1).strip() if m_pub else ""
        yield {"url": url, "titulo": titulo, "pub_date": pub_date}


# ---------- Parser del post individual ----------

def _parse_organiza(texto: str) -> tuple[str | None, str | None]:
    """De 'Congresista X (Bancada Y)' o 'Presidenta: Congresista X (Y)' extrae
    (congresista, bancada). Heuristica simple."""
    if not texto:
        return None, None
    # Quitar prefijos como "Presidenta:" "Presidente:" "Vicepresidente:"
    s = re.sub(r"^(president[ae]|vicepresident[ae]|secretari[ao]):\s*", "",
                texto.strip(), flags=re.IGNORECASE)
    # Buscar paréntesis para bancada
    m = re.search(r"^(.*?)\s*\((.*?)\)\s*$", s)
    if m:
        return m.group(1).strip() or None, m.group(2).strip() or None
    return s.strip() or None, None


def _extract_lista_p(html: str) -> list[str]:
    """Devuelve los textos limpios de los <p> dentro del article principal."""
    # Buscar el bloque entre <main> ... </main> o entry-content
    m = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
    bloque = m.group(1) if m else html
    paras = re.findall(r"<p[^>]*>(.*?)</p>", bloque, re.DOTALL)
    out = []
    for p in paras:
        txt = _strip_html(p)
        if txt and len(txt) > 2:
            out.append(txt)
    return out


_CATEGORIAS = {"mesa de trabajo", "ceremonia", "evento",
                "sesión descentralizada", "sesion descentralizada"}


def parse_post(html: str, fallback_titulo: str = "") -> dict:
    """Extrae los campos relevantes del HTML de un post individual.

    Estructura habitual de los <p>:
      [0] "Mesa de trabajo" / "Ceremonia" / etc.  ← categoria (tipo)
      [1] "Tema entre comillas" o descripcion     ← TEMA real
      [2] Comisión X de ...                       ← comision
      [3] Presidenta: Congresista Y (Bancada Z)   ← organiza
      [4] Edificio ...                            ← lugar (parte 1)
      [5] Sala ...                                ← lugar (parte 2)
      [6..] footer (newsletter, direccion, etc) — se filtra
    """
    paras_all = _extract_lista_p(html)
    BLACKLIST_SNIPPETS = (
        "newsletter", "ingrese un email", "correo a nuestro",
        "palacio legislativo", "uno o más campos", "intenta de nuevo",
        "anexo", "av. abancay",
    )
    paras = [p for p in paras_all
             if not any(b in p.lower() for b in BLACKLIST_SNIPPETS)
             and len(p) > 2]

    out = {
        "titulo": fallback_titulo or None,
        "tipo": None,
        "tema": None,
        "comision": None,
        "organiza": None,
        "congresista": None,
        "bancada": None,
        "lugar": None,
    }

    if not paras:
        return out

    # Si el primer paragraph es una categoria conocida, ese es el tipo
    idx = 0
    primer = paras[0].strip().lower()
    if primer in _CATEGORIAS:
        out["tipo"] = paras[0].strip()
        idx = 1
    else:
        # Inferir tipo desde fallback_titulo o el primer paragraph
        for cat in _CATEGORIAS:
            if cat in (fallback_titulo or "").lower():
                out["tipo"] = cat.title()
                break
        else:
            out["tipo"] = "Otro"

    # Siguiente: tema
    if idx < len(paras):
        out["tema"] = paras[idx]
        idx += 1

    # Buscar comision desde aqui
    for p in paras[idx:idx + 4]:
        if (re.search(r"\bcomisi[óo]n\b", p, re.IGNORECASE)
                and "presidenta" not in p.lower()
                and "presidente" not in p.lower()
                and "congresista" not in p.lower()):
            out["comision"] = p
            break

    # Organiza: el paragraph con "Congresista" / "Presidenta:" / "Presidente:"
    for p in paras[idx:idx + 5]:
        if re.search(r"\b(congresista|presidenta|presidente)\b", p, re.IGNORECASE):
            out["organiza"] = p
            out["congresista"], out["bancada"] = _parse_organiza(p)
            break

    # Lugar: concatenar todos los paragraphs que mencionen "Edificio" o "Sala"
    lugar_parts = [p for p in paras
                   if re.search(r"\b(edificio|sala|auditorio)\b", p, re.IGNORECASE)
                   and "palacio legislativo" not in p.lower()]
    if lugar_parts:
        # Limitar a los primeros 2 (Edificio + Sala)
        out["lugar"] = " · ".join(lugar_parts[:2])
    # Buscar lugar: cualquier p que mencione 'Edificio' o 'Sala'
    lugar_parts = []
    for p in paras:
        if re.search(r"\bedificio\b|\bsala\b", p, re.IGNORECASE):
            lugar_parts.append(p)
    if lugar_parts:
        out["lugar"] = " · ".join(lugar_parts)
    return out


def fetch_post_detail(url: str,
                      session: requests.Session | None = None) -> dict:
    """Fetchea el HTML de un post y devuelve campos extraidos."""
    s = session or requests.Session()
    s.headers.update(HEADERS)
    r = s.get(url, timeout=20)
    r.raise_for_status()
    return parse_post(r.text)


# ---------- Parser del listado para fecha+hora ----------

def fetch_listing_hoy(session: requests.Session | None = None) -> list[dict]:
    """Lee /agenda/ (dia actual por default) y devuelve eventos."""
    return _fetch_listing_url(f"{BASE}/agenda/", session=session)


def fetch_listing_dia(fecha_iso: str,
                       session: requests.Session | None = None) -> list[dict]:
    """Lee /agenda/YYYY/M/D/ (URL especifica de WordPress) y devuelve
    eventos de ese dia. Aunque la respuesta HTTP es 404, el body si
    contiene la data correcta — el portal renderea la pagina pero con
    status 404 (peculiaridad de su WP).

    fecha_iso: 'YYYY-MM-DD'
    """
    try:
        y, m, d = fecha_iso.split("-")
        # WordPress espera mes/dia SIN zero-padding en el path
        url = f"{BASE}/agenda/{int(y)}/{int(m)}/{int(d)}/"
    except (ValueError, AttributeError):
        return []
    return _fetch_listing_url(url, fecha_iso_hint=fecha_iso, session=session)


def _fetch_listing_url(url: str,
                       fecha_iso_hint: str | None = None,
                       session: requests.Session | None = None) -> list[dict]:
    """Helper interno: fetch + parse del listado en una URL dada.

    Ignora status 404 (WordPress devuelve 404 para URLs por fecha pero
    igual renderea el contenido correcto en el body)."""
    s = session or requests.Session()
    s.headers.update(HEADERS)
    r = s.get(url, timeout=20)
    if r.status_code not in (200, 404):
        r.raise_for_status()
    txt = _strip_html(r.text)
    # Fecha del header
    fecha_iso = fecha_iso_hint
    if not fecha_iso:
        m_f = _LISTING_FECHA.search(txt)
        if m_f:
            dia = int(m_f.group(2))
            mes = MES_NUM.get(m_f.group(3).lower(), 0)
            if mes:
                year = datetime.now(timezone.utc).year
                try:
                    fecha_iso = f"{year:04d}-{mes:02d}-{dia:02d}"
                except Exception:
                    pass
    eventos = []
    for m in _LISTING_EVENT.finditer(txt):
        eventos.append({
            "fecha": fecha_iso,
            "hora": m.group("hora").strip(),
            "tema": m.group("tema").strip(),
            "organiza": m.group("organiza").strip(),
            "lugar": m.group("lugar").strip(),
        })
    return eventos


# ---------- Sync de horas por ventana de dias ----------

def _normalize_for_match(s: str) -> str:
    if not s:
        return ""
    s = s.replace("“", "").replace("”", "")
    s = s.replace("‘", "").replace("’", "")
    s = s.replace('"', "").replace("'", "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def run_sync_dias(db, *, days_back: int = 7, days_fwd: int = 14) -> dict:
    """Itera dias [hoy-back, hoy+fwd] y enriquece mesas existentes con
    hora/fecha/lugar. Tambien crea nuevos registros si encuentra eventos
    que no tienen contraparte en el RSS (eventos pasados o muy futuros).

    Para los eventos sin url al post individual (no estan en el RSS),
    creamos una URL sintetica: "synthetic://YYYY-MM-DD/HH:MM/<hash>".
    """
    from datetime import date, timedelta
    import hashlib

    stats = {"dias": 0, "eventos": 0, "actualizados": 0, "nuevos": 0,
             "errores": 0}

    today = date.today()
    fechas = [today + timedelta(days=d)
              for d in range(-days_back, days_fwd + 1)]

    # Cargar todas las mesas existentes para matching por tema
    rows = db.conn.execute(
        "SELECT url, tema FROM mesas_tecnicas WHERE tema IS NOT NULL"
    ).fetchall()
    mesa_index = {}
    for r in rows:
        norm = _normalize_for_match(r["tema"])
        if norm and len(norm) >= 15:
            mesa_index[norm] = r["url"]

    session = requests.Session()
    session.headers.update(HEADERS)

    for f in fechas:
        iso = f.isoformat()
        try:
            eventos = fetch_listing_dia(iso, session=session)
        except Exception as e:
            log.warning("dia %s fallo: %s", iso, e)
            stats["errores"] += 1
            continue
        stats["dias"] += 1
        if not eventos:
            continue
        stats["eventos"] += len(eventos)
        log.info("[%s] %d eventos", iso, len(eventos))

        for ev in eventos:
            norm_ev = _normalize_for_match(ev.get("tema") or "")
            if not norm_ev:
                continue
            # Buscar match en index existente
            matched_url = None
            for norm_mesa, url in mesa_index.items():
                if norm_mesa in norm_ev or norm_ev.endswith(norm_mesa):
                    matched_url = url
                    break
                if len(norm_mesa) >= 40 and norm_mesa[:40] in norm_ev:
                    matched_url = url
                    break

            # Parsear organiza para extraer congresista/bancada
            organiza_txt = ev.get("organiza") or ""
            congresista = None
            bancada = None
            comision = None
            m_pres = re.search(
                r"(?:presidenta|presidente):\s*(.+?)(?:\.|$|\s+y\s+)",
                organiza_txt, re.IGNORECASE,
            )
            if m_pres:
                # Lo que sigue a "Presidenta:" es congresista (Bancada)
                resto = m_pres.group(1).strip()
                m_b = re.search(r"\((.*?)\)", resto)
                if m_b:
                    bancada = m_b.group(1).strip()
                    congresista = resto.split("(", 1)[0].strip()
                else:
                    congresista = resto
            else:
                # Quizas sea "Congresista X (Bancada)" sin "Presidenta:"
                m_b = re.search(r"\((.*?)\)", organiza_txt)
                if m_b:
                    bancada = m_b.group(1).strip()
                    congresista = organiza_txt.split("(", 1)[0].strip()
                    congresista = re.sub(r"^\s*congresista\s+", "",
                                          congresista, flags=re.IGNORECASE).strip()
            # Comision: si el texto menciona "Comision" antes del congresista
            m_com = re.search(r"\b(Comisi[óo]n[^.]*?)(?:\s+Presidenta|\s+Presidente|$)",
                               organiza_txt, re.IGNORECASE)
            if m_com:
                comision = m_com.group(1).strip().rstrip(".,;")

            row = {
                "tipo": ev.get("tipo", "Otro"),
                "tema": ev.get("tema"),
                "fecha": ev.get("fecha"),
                "hora": ev.get("hora"),
                "organiza": organiza_txt,
                "congresista": congresista,
                "bancada": bancada,
                "comision": comision,
                "lugar": ev.get("lugar"),
            }

            if matched_url:
                # Actualizar registro existente
                row["url"] = matched_url
                try:
                    is_new, changed = db.upsert(row)
                    if changed:
                        stats["actualizados"] += 1
                except Exception as e:
                    log.warning("update fallo: %s", e)
                    stats["errores"] += 1
            else:
                # Crear nuevo registro con URL sintetica (no esta en RSS)
                h = hashlib.md5(
                    f"{iso}|{ev.get('hora')}|{norm_ev[:80]}".encode()
                ).hexdigest()[:12]
                row["url"] = f"synthetic://{iso}/{ev.get('hora','')}/{h}"
                row["titulo"] = (ev.get("tema") or "")[:200]
                try:
                    is_new, _ = db.upsert(row)
                    if is_new:
                        stats["nuevos"] += 1
                        # Agregar al index para evitar duplicar en el mismo run
                        mesa_index[norm_ev[:200]] = row["url"]
                except Exception as e:
                    log.warning("insert fallo: %s", e)
                    stats["errores"] += 1
    return stats


# ---------- Sync principal ----------

def run_sync(db, *, max_pages_rss: int = 5, fetch_details: bool = True,
             include_listing_hoy: bool = True) -> dict:
    """Pipeline completo de scraping.

    1. Itera RSS feed (max_pages_rss paginas) → URLs nuevas
    2. Fetch HTML de cada URL → extrae detalles
    3. Tambien lee listado /agenda/ del dia para enriquecer con hora real
       (los datos del listado se mergean con los del post por matching de
       titulo / organiza).
    4. Upsert en mesas_tecnicas.
    """
    stats = {"vistos": 0, "nuevos": 0, "actualizados": 0,
             "paginas_rss": 0, "errores": 0}

    session = requests.Session()
    session.headers.update(HEADERS)

    # Lista de eventos del listado de hoy (para merge por substring matching).
    # No es dict porque el matching no es exacto — buscamos texto entre comillas
    # del post dentro del texto del listado.
    eventos_hoy: list[dict] = []
    if include_listing_hoy:
        try:
            eventos_hoy = fetch_listing_hoy(session=session)
            log.info("listado /agenda/ del dia: %d eventos", len(eventos_hoy))
        except Exception as e:
            log.warning("no pude leer /agenda/ del dia: %s", e)
            stats["errores"] += 1

    def _normalize_for_match(s: str) -> str:
        """Normaliza un texto para matching: lowercase, sin comillas
        curvas, sin doble espacio. Mantiene solo lo esencial."""
        if not s:
            return ""
        # Reemplazar comillas curvas/rectas por nada
        s = s.replace("“", "").replace("”", "")  # " "
        s = s.replace("‘", "").replace("’", "")  # ' '
        s = s.replace('"', "").replace("'", "")
        s = re.sub(r"\s+", " ", s).strip().lower()
        return s

    def _find_match(tema_post: str) -> dict | None:
        """Busca un evento del listado_hoy cuyo tema contenga el del post.
        Retorna el evento si hay match, None si no."""
        norm_post = _normalize_for_match(tema_post)
        if not norm_post or len(norm_post) < 20:  # texto muy corto = match poco confiable
            return None
        for ev in eventos_hoy:
            norm_ev = _normalize_for_match(ev.get("tema") or "")
            if norm_post in norm_ev or norm_ev.endswith(norm_post):
                return ev
            # Fallback: si la primera mitad del post esta en el listado, match
            if len(norm_post) >= 40 and norm_post[:40] in norm_ev:
                return ev
        return None

    # Iterar RSS
    for paged in range(1, max_pages_rss + 1):
        try:
            items = list(iter_rss_items(paged, session=session))
        except Exception as e:
            log.warning("error rss pagina %d: %s", paged, e)
            stats["errores"] += 1
            break
        if not items:
            break
        stats["paginas_rss"] += 1
        log.info("RSS pagina %d: %d items", paged, len(items))

        for item in items:
            stats["vistos"] += 1
            row = dict(item)  # url, titulo, pub_date
            # Detalle del post
            if fetch_details:
                try:
                    det = fetch_post_detail(item["url"], session=session)
                    row.update({
                        "tipo": det.get("tipo"),
                        "tema": det.get("tema"),
                        "comision": det.get("comision"),
                        "organiza": det.get("organiza"),
                        "congresista": det.get("congresista"),
                        "bancada": det.get("bancada"),
                        "lugar": det.get("lugar"),
                    })
                except Exception as e:
                    log.warning("error detail %s: %s", item["url"], e)
                    stats["errores"] += 1
                    continue

            # Mergear con listado de hoy: substring match (el listado tiene
            # "Mesa de trabajo 'X'" y el post solo "'X'"). Buscamos el post
            # dentro del listado del dia.
            ev = _find_match(row.get("tema") or "")
            if ev:
                row["hora"] = ev.get("hora")
                # Solo poner fecha si no la teniamos del post
                if not row.get("fecha"):
                    row["fecha"] = ev.get("fecha")
                if not row.get("lugar"):
                    row["lugar"] = ev.get("lugar")

            # Dejamos titulo generico (tipo) y tema separados — la UI usa
            # tema como el contenido principal cuando esta presente.

            try:
                is_new, changed = db.upsert(row)
                if is_new:
                    stats["nuevos"] += 1
                elif changed:
                    stats["actualizados"] += 1
            except Exception as e:
                log.warning("error upsert %s: %s", item["url"], e)
                stats["errores"] += 1

    return stats
