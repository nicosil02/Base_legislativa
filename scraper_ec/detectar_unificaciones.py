"""Detector heuristico de candidatos a unificacion en PLs EC.

El portal de la Asamblea no expone info estructurada de "PLs unificados".
La aproximacion: dos PLs probablemente esten unificados (o son candidatos
a serlo) si comparten:
  1. La MISMA comision asignada (filtro fuerte, sin esto descartamos).
  2. Mucho overlap de tokens significativos en el titulo (Jaccard).
  3. Al menos un token "raro" compartido — alguna palabra distintiva
     (IDF alta) que no sea generica tipo "ley", "organica", "reformatoria".

Output: lista de "grupos candidatos" con score de confianza. NO los inserta
automaticamente en la DB — solo los reporta. El usuario revisa y aprueba
con `marcar-unificacion --pls X,Y,Z` o con `aprobar-candidatos`.
"""
from __future__ import annotations

import math
import re
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass


# Stopwords genericas que aparecen en muchos titulos y no aportan distincion.
STOPWORDS = {
    "proyecto", "ley", "organica", "reformatoria", "interpretativa",
    "que", "de", "del", "la", "el", "los", "las", "y", "o", "a", "en",
    "al", "para", "por", "con", "sin", "como", "su", "se", "es", "una",
    "varios", "varias", "cuerpos", "legales", "codigo", "reforma",
    "modificacion", "modifica", "modificatoria", "incorpora", "incorporar",
    "establece", "establecer", "regula", "regular", "crea", "crear",
    "nacional", "general", "publico", "publica", "vigente",
}


def _normalize(text: str | None) -> str:
    """Lowercase + sin acentos + sin puntuacion."""
    if not text:
        return ""
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokens(titulo: str, min_len: int = 5) -> set[str]:
    """Tokens significativos: len >= min_len y no stopword."""
    norm = _normalize(titulo)
    return {t for t in norm.split() if len(t) >= min_len and t not in STOPWORDS}


def _build_idf(rows: list[tuple[str, str]]) -> dict[str, float]:
    """Calcula IDF de cada token significativo sobre todos los titulos.
    IDF alto = palabra rara = mas distintiva."""
    df: dict[str, int] = defaultdict(int)
    n_docs = len(rows)
    for _, titulo in rows:
        for tok in _tokens(titulo):
            df[tok] += 1
    return {t: math.log((n_docs + 1) / (cnt + 1)) for t, cnt in df.items()}


@dataclass
class Candidate:
    pls: tuple[str, ...]              # n_tramites del grupo
    comision: str
    jaccard: float                    # similitud promedio
    rare_token: str | None            # token raro compartido (debug)
    rare_idf: float                   # IDF del token raro
    titulos: dict[str, str]           # n_tramite -> titulo (primeros 100 chars)


def detectar(
    conn: sqlite3.Connection,
    min_jaccard: float = 0.5,
    min_rare_idf: float = 2.0,
    min_token_len: int = 6,
) -> list[Candidate]:
    """Detecta grupos candidatos a unificacion.

    Algoritmo:
    1. Cargar todos los PLs con (n_tramite, titulo, comision_asignada)
    2. Excluir PLs sin comision asignada o con "No Asignado"
    3. Excluir PLs ya marcados en algun grupo de unificacion
    4. Calcular IDF global de tokens
    5. Para cada PAR de PLs en la misma comision, computar Jaccard
       y verificar que comparten al menos 1 token "raro"
    6. Agrupar candidatos transitivos (componentes conexas):
       si (A,B) y (B,C) son candidatos, (A,B,C) es un grupo
    """
    # Cargar PLs validos
    rows = conn.execute(
        """SELECT n_tramite, titulo, comision_asignada
           FROM proyectos
           WHERE titulo IS NOT NULL
             AND length(titulo) >= 20
             AND comision_asignada IS NOT NULL
             AND comision_asignada != ''
             AND UPPER(comision_asignada) NOT LIKE '%NO SE ASIGNA%'
             AND UPPER(comision_asignada) NOT LIKE '%NO ASIGNADO%'"""
    ).fetchall()

    # Excluir PLs ya en algun grupo
    try:
        ya_unificados = {
            r[0] for r in conn.execute("SELECT n_tramite FROM unificacion_pl")
        }
    except sqlite3.OperationalError:
        ya_unificados = set()
    rows = [r for r in rows if r[0] not in ya_unificados]

    # IDF global
    idf = _build_idf([(r[0], r[1]) for r in rows])

    # Agrupar por comision
    por_comision: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for n_tramite, titulo, comision in rows:
        por_comision[comision].append((n_tramite, titulo))

    # Detectar pares dentro de cada comision
    pares: list[tuple[str, str, float, str, float, str]] = []
    # (n_tramite_a, n_tramite_b, jaccard, rare_token, rare_idf, comision)
    for comision, pls in por_comision.items():
        if len(pls) < 2:
            continue
        # Pre-tokenizar
        tokens_map = {n: _tokens(t, min_len=min_token_len) for n, t in pls}
        titulos_map = {n: t for n, t in pls}
        for i in range(len(pls)):
            n_a, _ = pls[i]
            ta = tokens_map[n_a]
            if not ta:
                continue
            for j in range(i + 1, len(pls)):
                n_b, _ = pls[j]
                tb = tokens_map[n_b]
                if not tb:
                    continue
                inter = ta & tb
                if not inter:
                    continue
                union = ta | tb
                jacc = len(inter) / len(union)
                if jacc < min_jaccard:
                    continue
                # Token mas raro compartido
                rarest = max(inter, key=lambda t: idf.get(t, 0.0))
                ridf = idf.get(rarest, 0.0)
                if ridf < min_rare_idf:
                    continue
                pares.append((n_a, n_b, jacc, rarest, ridf, comision))

    # Componentes conexas (Union-Find simple)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for n_a, n_b, *_ in pares:
        parent.setdefault(n_a, n_a)
        parent.setdefault(n_b, n_b)
        union(n_a, n_b)

    # Agrupar n_tramites por root
    grupos: dict[str, set[str]] = defaultdict(set)
    info: dict[tuple[str, str], tuple[float, str, float]] = {}
    for n_a, n_b, jacc, rare, ridf, comision in pares:
        root = find(n_a)
        grupos[root].add(n_a)
        grupos[root].add(n_b)
        info[(n_a, n_b)] = (jacc, rare, ridf)

    # Construir Candidates
    titulos_full = {r[0]: r[1] for r in rows}
    comision_de = {r[0]: r[2] for r in rows}
    candidatos: list[Candidate] = []
    for root, miembros in grupos.items():
        if len(miembros) < 2:
            continue
        # Promedio Jaccard sobre los pares del grupo
        jaccs = []
        rare_tokens = set()
        rare_idfs = []
        for n_a, n_b in info:
            if n_a in miembros and n_b in miembros:
                j, t, i_v = info[(n_a, n_b)]
                jaccs.append(j)
                rare_tokens.add(t)
                rare_idfs.append(i_v)
        if not jaccs:
            continue
        avg_jacc = sum(jaccs) / len(jaccs)
        # El token mas raro del grupo
        best_rare = max(rare_tokens, key=lambda t: max((i for tt, i in zip(rare_tokens, rare_idfs) if tt == t), default=0))
        best_idf = max(rare_idfs) if rare_idfs else 0
        comision = next(comision_de[n] for n in miembros)
        candidatos.append(Candidate(
            pls=tuple(sorted(miembros)),
            comision=comision,
            jaccard=avg_jacc,
            rare_token=best_rare,
            rare_idf=best_idf,
            titulos={n: (titulos_full[n] or "")[:140] for n in miembros},
        ))

    # Ordenar por score descendente (jaccard * idf del token raro)
    candidatos.sort(key=lambda c: c.jaccard * c.rare_idf, reverse=True)
    return candidatos
