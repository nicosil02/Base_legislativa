"""Parser de temas del Pleno: extrae PLs referenciados con dos estrategias.

Estrategia 1 (alta precision): la URL canonica `desUrl` del tema apunta al
portal del PL:
   https://wb2server.congreso.gob.pe/spley-portal/#/expediente/{per_par}/{pley_num}
De ahi sacamos el `pley_num` con regex.

Estrategia 2 (recall): parseamos el HTML `desTema` con el extractor del modulo
sesiones/ — captura PLs "acumulados" o referencias adicionales que no estan en
la URL principal.
"""
from __future__ import annotations

import re

from sesiones.agenda_parser import extract_pls, to_text

# URL canonica del portal del PL:
#   https://wb2server.congreso.gob.pe/spley-portal/#/expediente/2021/594
URL_PL_PATTERN = re.compile(
    r"/expediente/(\d{4})/(\d{1,5})",
    re.IGNORECASE,
)

# nomTemaCor a veces viene como "Proyecto de Ley 594" o "Proyectos de Ley 594, 678"
NOM_PL_PATTERN = re.compile(
    r"proyectos?\s+de\s+ley\s+n?[°ºo\.]*\s*(\d{1,5})(?:\s*/\s*(\d{4}))?",
    re.IGNORECASE,
)


def _from_url(url: str | None) -> tuple[int, int] | None:
    """De una URL del portal extrae (per_par_id, pley_num). None si no matchea."""
    if not url:
        return None
    m = URL_PL_PATTERN.search(url)
    if not m:
        return None
    try:
        return (int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def parse_tema(tema: dict) -> tuple[dict, list[dict]]:
    """Procesa un tema crudo de la API y devuelve:
      - tema_row: dict con columnas para pleno_tema
      - pls: lista deduplicada de {pley_num, per_par_id, raw, origen}
    """
    cod_tema = tema.get("codTema")
    des_url = tema.get("desUrl") or ""
    des_tema_html = tema.get("desTema") or ""
    des_tema_texto = to_text(des_tema_html)

    pls_seen: dict[int, dict] = {}

    # Estrategia 1: URL canonica (alta precision)
    canon = _from_url(des_url)
    if canon:
        per_par, pley_num = canon
        pls_seen[pley_num] = {
            "pley_num": pley_num,
            "per_par_id": per_par,
            "raw": tema.get("nomTemaCor") or str(pley_num),
            "origen": "url_canonica",
        }

    # Estrategia 2: regex sobre el HTML rich (capta acumulados, referencias
    # adicionales). Usa el extractor de sesiones/ que ya maneja todas las
    # variantes (PL, P.L., Proyecto de Ley, con/sin sufijo -CR/-PE/etc).
    for pl in extract_pls(des_tema_texto):
        if pl["pley_num"] in pls_seen:
            continue
        pls_seen[pl["pley_num"]] = {
            "pley_num": pl["pley_num"],
            "per_par_id": 2021,  # default: las agendas del Pleno actual son 2021-2026
            "raw": pl["raw"],
            "origen": "regex_texto",
        }

    # Estrategia 3 (fallback): si ni URL ni HTML dieron PLs pero nomTemaCor
    # tiene un numero, lo capturamos. Ej. "Proyecto de Ley 594".
    if not pls_seen:
        m = NOM_PL_PATTERN.search(tema.get("nomTemaCor") or "")
        if m:
            try:
                pley_num = int(m.group(1))
                if 1 <= pley_num <= 30000:
                    pls_seen[pley_num] = {
                        "pley_num": pley_num,
                        "per_par_id": 2021,
                        "raw": tema.get("nomTemaCor"),
                        "origen": "nom_tema_cor",
                    }
            except ValueError:
                pass

    tema_row = {
        "cod_tema": cod_tema,
        "cod_sec": tema.get("codSec"),
        "des_sec": tema.get("desSec"),
        "cod_sub_sec": tema.get("codSubSec"),
        "des_sub_sec": tema.get("desSubSec"),
        "num_tema": tema.get("numTema"),
        "nom_tema_cor": tema.get("nomTemaCor"),
        "des_url": des_url or None,
        "des_comisiones": tema.get("desComisiones"),
        "des_resumen": tema.get("desResumen"),
        "des_tema_html": des_tema_html or None,
        "des_tema_texto": des_tema_texto or None,
        "cod_est_tema": tema.get("codEstTema"),
        "nota_estado": tema.get("notaEstado"),
        "ind_publicado": tema.get("indPublicado"),
    }
    return tema_row, list(pls_seen.values())


def flatten_temas(agenda_data: dict) -> list[dict]:
    """Recorre secciones.subsecciones.temas y devuelve la lista plana de temas
    listos para parsear. Maneja el caso de subsecciones anidadas (rara vez)."""
    out: list[dict] = []
    for sec in (agenda_data.get("secciones") or []):
        for sub in (sec.get("subsecciones") or []):
            for t in (sub.get("temas") or []):
                if t.get("codTema") is None:
                    continue
                out.append(t)
            # subsecciones anidadas (defensivo, rara vez sucede)
            for subsub in (sub.get("subsecciones") or []):
                for t in (subsub.get("temas") or []):
                    if t.get("codTema") is None:
                        continue
                    out.append(t)
        for t in (sec.get("temas") or []):  # temas directos sin subseccion
            if t.get("codTema") is None:
                continue
            out.append(t)
    return out
