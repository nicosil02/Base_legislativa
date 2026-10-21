"""Configuracion de cada cliente: `clientes/<slug>/cliente.json`.

Sumar un cliente = crear su carpeta con cliente.json (+ notas.md para el
perfil del cerebro y el chat de alertas). Nada de esto vive en el codigo.

Campos:
  nombre                      como se muestra
  paises                      ["PE", "EC"]: donde se le monitorea
  temas_noticias              temas de noticias/temas.TEMAS (filtro en fuentes amplias)
  categorias_pl               categorias de scraper/categorias.py (filtro de PLs y agenda)
  categorias_fuente           categorias de fuente de noticias que le tocan enteras
  instituciones               fuentes (por nombre) que le tocan
  fuentes_con_perfil_estricto fuentes donde ademas se exige una de sus palabras_clave
  palabras_clave              substrings sin tildes, en minusculas
  matriz_pl                   {pais: matriz de clientes/matrices.MATRICES} con los PL que sigue
  temas_propios               {tema: [palabras]} temas de noticias que no estan en noticias/temas.TEMAS
                              (ej. "Mineria" para un cliente minero); se suman a la clasificacion
                              y a sus temas_noticias sin tocar codigo
  palabras_norma              palabras que hacen "de interes" una norma del diario oficial
  por_que                     notas de por que esta asi (solo para humanos)
"""
from __future__ import annotations

import json
from functools import lru_cache

from core.db import ROOT

CARPETA = ROOT / "clientes"


@lru_cache(maxsize=1)
def todos() -> dict[str, dict]:
    """{slug: config}, en orden alfabetico."""
    return {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(CARPETA.glob("*/cliente.json"))}


def slugs(pais: str | None = None) -> list[str]:
    return [s for s, c in todos().items() if not pais or pais in c["paises"]]


def campo(nombre: str) -> dict[str, list]:
    """{slug: valor del campo} de todos los clientes que lo tienen no vacio."""
    return {s: c[nombre] for s, c in todos().items() if c.get(nombre)}


def temas_propios() -> dict[str, list[str]]:
    """{tema: palabras} de los temas_propios de todos los clientes (unidos)."""
    out: dict[str, list[str]] = {}
    for c in todos().values():
        for tema, kws in (c.get("temas_propios") or {}).items():
            out.setdefault(tema, []).extend(kws)
    return out


def temas_de(slug: str) -> list[str]:
    """temas_noticias del cliente + los nombres de sus temas_propios."""
    c = todos().get(slug, {})
    return [*c.get("temas_noticias", []), *(c.get("temas_propios") or {})]


def por_campo(nombre: str) -> dict[str, list[str]]:
    """Invierte un campo lista: {valor: [slugs que lo tienen]}."""
    out: dict[str, list[str]] = {}
    for s, c in todos().items():
        for v in c.get(nombre, []):
            out.setdefault(v, []).append(s)
    return out


def matriz(slug: str, pais: str) -> list[dict]:
    """Filas de la matriz de PL que el cliente sigue en `pais` ([] si no tiene)."""
    from clientes.matrices import MATRICES
    clave = todos().get(slug, {}).get("matriz_pl", {}).get(pais)
    return MATRICES[clave](pais) if clave else []


def por_matriz(pais: str) -> dict[str, list[str]]:
    """{matriz: [slugs que la siguen en pais]}."""
    out: dict[str, list[str]] = {}
    for s, c in todos().items():
        if clave := c.get("matriz_pl", {}).get(pais):
            out.setdefault(clave, []).append(s)
    return out
