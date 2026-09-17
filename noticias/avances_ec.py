"""Senal temprana de avances de tramite en Ecuador: noticias de la Asamblea
Nacional que suelen contar un cambio de estado (informe, debate, aprobacion)
antes de que el sync oficial (scraper_ec.csv_importer, corre 4x/dia) lo
refleje en `estado`.

Nicolas 2026-09-17: en Ecuador los cambios de estado salen primero en las
noticias de la Asamblea que en el portal oficial.

Se probo (y se descarto) enlazar automaticamente cada noticia a un PL
especifico via similitud de texto (TF-IDF titulo de la noticia vs titulo del
PL): con datos reales el resultado no fue confiable - el titulo formal de un
PL ("...INSTITUTO NACIONAL DE INVESTIGACIONES AGROPECUARIAS (INIAP)") y el
titular de prensa ("...normativa para modernizar el INIAP") comparten muy
poco vocabulario, y en al menos un caso real probado a mano el score mas alto
señalaba a un PL totalmente distinto (uno de inteligencia artificial, por la
palabra generica "desarrollo"). Un vinculo automatico que a veces apunta al
PL equivocado es peor que no tener vinculo - Nicolas conoce sus PLs de
memoria, lo que necesita es la lista corta y confiable de noticias
candidatas, no una adivinanza. Este modulo se queda en eso: filtra ruido
(deportes/policiales/etc., que son la mayoria del volumen de "Coyuntura
Politica") y devuelve solo noticias de fuentes puntuales de la Asamblea que
mencionan vocabulario de tramite legislativo, recientes.

Uso:
    from noticias.avances_ec import noticias_tramite_recientes
    candidatas = noticias_tramite_recientes(conn_noticias)
"""
from __future__ import annotations

import re
import sqlite3

# Fuentes puntuales de la Asamblea (ver noticias/fuentes.py) - deliberadamente
# NO se usa la categoria "Coyuntura Politica" completa, que es mayormente
# deportes/policiales/etc. y ahogaria las pocas noticias relevantes.
FUENTES_TRAMITE_EC = (
    "Portal de la Asamblea Nacional",
    "Google News EC — Ley Orgánica",
)

_RE_TRAMITE = re.compile(
    r"informe|primer debate|segundo debate|comisi[oó]n|aprob|tramit|"
    r"avoc|calific|dictamen|pleno",
    re.IGNORECASE,
)


def noticias_tramite_recientes(db_noticias: sqlite3.Connection, dias: int = 7) -> list[dict]:
    """Noticias EC recientes, de fuentes de la Asamblea, con vocabulario de
    tramite legislativo - para que Nicolas las revise a mano y las cruce con
    sus PLs de interes. Devuelve {titulo, resumen, fecha_pub, url} ordenado
    por fecha descendente."""
    placeholders = ",".join("?" * len(FUENTES_TRAMITE_EC))
    filas = db_noticias.execute(
        f"""
        SELECT n.titulo, n.resumen, n.fecha_pub, n.url
        FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
        WHERE f.pais = 'EC' AND f.nombre IN ({placeholders})
          AND n.fecha_pub IS NOT NULL
          AND n.fecha_pub >= datetime('now', ?)
        ORDER BY n.fecha_pub DESC
        """,
        (*FUENTES_TRAMITE_EC, f"-{dias} days"),
    ).fetchall()
    return [
        {"titulo": titulo, "resumen": resumen, "fecha_pub": fecha_pub, "url": url}
        for titulo, resumen, fecha_pub, url in filas
        if _RE_TRAMITE.search(f"{titulo or ''} {resumen or ''}")
    ]
