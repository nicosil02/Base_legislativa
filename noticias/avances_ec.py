"""Senal temprana de avances de tramite en Ecuador: noticias de la Asamblea
Nacional que suelen contar un cambio de estado (informe, debate, aprobacion)
antes de que el sync oficial (scraper_ec.csv_importer, corre 4x/dia) lo
refleje en `estado`.

No se enlaza cada noticia a un PL por similitud de texto: el titulo formal
del PL y el titular de prensa comparten poco vocabulario y el mejor score a
veces apuntaba a otro PL. Un vinculo equivocado es peor que ninguno; esto
devuelve la lista corta de noticias candidatas para revisar a mano.

Uso:
    from noticias.avances_ec import noticias_tramite_recientes
    candidatas = noticias_tramite_recientes(conn_noticias)
"""
from __future__ import annotations

import re
import sqlite3

# Fuentes puntuales, no toda "Coyuntura Politica" (mayormente deportes y
# policiales). El Comercio y El Universo dan redundancia al RSS de la
# Asamblea, cuyo portal ya estuvo caido meses.
FUENTES_TRAMITE_EC = (
    "Portal de la Asamblea Nacional",
    "El Comercio",
    "El Universo",
)

_RE_TRAMITE = re.compile(
    r"informe|primer debate|segundo debate|comisi[oó]n|aprob|tramit|"
    r"avoc|calific|dictamen|pleno",
    re.IGNORECASE,
)

# Los medios cubren toda la coyuntura: "informe"/"aprob" solos matchean de
# todo (informe PISA, Concejo de Quito). A ellos se les exige ademas una
# palabra de la Asamblea; al RSS propio de la Asamblea no.
_RE_ANCLA_ASAMBLEA = re.compile(
    r"asamblea|legislativ|asamble[ií]sta|proyecto de ley|\bpleno\b",
    re.IGNORECASE,
)
FUENTE_ASAMBLEA_PROPIA = "Portal de la Asamblea Nacional"


def noticias_tramite_recientes(db_noticias: sqlite3.Connection, dias: int = 7) -> list[dict]:
    """Noticias EC recientes, de fuentes con cobertura de la Asamblea
    (propia + medios independientes), con vocabulario de tramite legislativo
    - para revisarlas a mano contra los PLs de interes.
    Devuelve {titulo, resumen, fecha_pub, url} ordenado por fecha descendente."""
    placeholders = ",".join("?" * len(FUENTES_TRAMITE_EC))
    filas = db_noticias.execute(
        f"""
        SELECT n.titulo, n.resumen, n.fecha_pub, n.url, f.nombre
        FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
        WHERE f.pais = 'EC' AND f.nombre IN ({placeholders})
          AND n.fecha_pub IS NOT NULL
          AND n.fecha_pub >= datetime('now', ?)
        ORDER BY n.fecha_pub DESC
        """,
        (*FUENTES_TRAMITE_EC, f"-{dias} days"),
    ).fetchall()
    out = []
    for titulo, resumen, fecha_pub, url, fuente in filas:
        texto = f"{titulo or ''} {resumen or ''}"
        if not _RE_TRAMITE.search(texto):
            continue
        if fuente != FUENTE_ASAMBLEA_PROPIA and not _RE_ANCLA_ASAMBLEA.search(texto):
            continue
        out.append({"titulo": titulo, "resumen": resumen, "fecha_pub": fecha_pub, "url": url})
    return out
