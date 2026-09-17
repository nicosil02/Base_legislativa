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

# Fuentes puntuales (ver noticias/fuentes.py) - deliberadamente NO se usa la
# categoria "Coyuntura Politica" completa (mayormente deportes/policiales/
# farandula, ahogaria las pocas noticias relevantes), solo estos nombres.
#
# Nicolas 2026-09-17: "las noticias de la asamblea vienen de un solo lugar" -
# cierto, la primera version solo usaba el RSS propio de la Asamblea. Se
# sumaron El Comercio y El Universo (medios independientes EC ya trackeados
# en el catalogo, con RSS real y activo - verificado en vivo: ambos tienen
# cientos de notas de los ultimos dias) para no depender de una sola fuente
# que ademas es la misma institucion cuyo portal oficial (Ppless) recien
# estuvo roto 4 meses. Prueba real de que la redundancia vale la pena: la
# noticia de "Segura EP" del 15-sept aparecio TANTO en el portal de la
# Asamblea como en El Universo, de forma independiente.
#
# "Google News EC — Ley Organica" (ver noticias/fuentes.py) se DEJO AFUERA
# a proposito: verificado en vivo 2026-09-17 que el feed en si funciona
# (curl directo trae resultados de hoy), pero la tabla `noticias` no tiene
# nada mas nuevo que 2026-09-03 pese a que el sync corre 15x/dia - un bug
# de sync distinto (posible bloqueo/degradacion de Google News a la IP del
# runner de CI, no confirmado) que no se investigo a fondo esta sesion.
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

# El Comercio/El Universo cubren TODA la coyuntura politica (judicial,
# electoral, aprobacion presidencial, etc.) - "informe"/"aprob"/"comision"
# solos matchean de todo (probado en vivo: "informe PISA", "Consejo de la
# Judicatura", ratings de aprobacion de Noboa, hasta un "segundo debate en
# el Concejo" que es el Concejo MUNICIPAL de Quito, no la Asamblea). Para
# estas fuentes se exige ademas una palabra ancla de Asamblea/Legislativo.
# El RSS propio de la Asamblea no la necesita: todo lo que publica ya es
# por definicion de la Asamblea.
_RE_ANCLA_ASAMBLEA = re.compile(
    r"asamblea|legislativ|asamble[ií]sta|proyecto de ley|\bpleno\b",
    re.IGNORECASE,
)
FUENTE_ASAMBLEA_PROPIA = "Portal de la Asamblea Nacional"


def noticias_tramite_recientes(db_noticias: sqlite3.Connection, dias: int = 7) -> list[dict]:
    """Noticias EC recientes, de fuentes con cobertura de la Asamblea
    (propia + medios independientes), con vocabulario de tramite legislativo
    - para que Nicolas las revise a mano y las cruce con sus PLs de interes.
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
