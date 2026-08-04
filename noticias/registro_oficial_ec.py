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


def build_edition_noticia(edition: dict, indice_text: str, temas: list[str]) -> dict:
    """Convierte una edición completa del RO en una noticia clasificada.

    El resumen contiene el índice completo (o primeros ~500 chars) — así el
    usuario puede leer qué normas se publicaron en ese suplemento sin abrir
    el PDF.
    """
    resumen = re.sub(r"\s+", " ", indice_text).strip()[:500]
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
            noticia = build_edition_noticia(ed, indice_text, temas)
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
