"""Catálogo canónico de las 24 Comisiones Ordinarias del Congreso del Perú.

Todo lo que no esté en esta lista se considera "Comisión Especial" (incluye
comisiones especiales, subcomisiones, comisiones investigadoras, registros
con typos del catálogo del API, etc.) y se agrupa bajo el rótulo
"Comisiones Especiales" en el frontend.

Match insensible a tildes, mayúsculas y espacios extra para tolerar
variantes ortográficas que pueda traer el API.
"""
from __future__ import annotations

import unicodedata

COMISIONES_ORDINARIAS: set[str] = {
    "Agraria",
    "Ciencia, Innovación y Tecnología",
    "Comercio Exterior y Turismo",
    "Constitución y Reglamento",
    "Cultura y Patrimonio Cultural",
    "Defensa del Consumidor y Organismos Reguladores de los Servicios Públicos",
    "Defensa Nacional, Orden Interno, Desarrollo Alternativo y Lucha Contra las Drogas",
    "Descentralización, Regionalización, Gobiernos Locales y Modernización de la Gestión del Estado",
    "Economía, Banca, Finanzas e Inteligencia Financiera",
    "Educación, Juventud y Deporte",
    "Energía y Minas",
    "Fiscalización y Contraloría",
    "Inclusión Social y Personas con Discapacidad",
    "Inteligencia",
    "Justicia y Derechos Humanos",
    "Mujer y Familia",
    "Presupuesto y Cuenta General de la República",
    "Producción, Micro y Pequeña Empresa y Cooperativas",
    "Pueblos Andinos, Amazónicos y Afroperuanos, Ambiente y Ecología",
    "Relaciones Exteriores",
    "Salud y Población",
    "Trabajo y Seguridad Social",
    "Transportes y Comunicaciones",
    "Vivienda y Construcción",
}


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    s = text.strip().lower()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = " ".join(s.split())
    return s


_ORDINARIAS_NORM: set[str] = {_normalize(n) for n in COMISIONES_ORDINARIAS}


def es_ordinaria(nombre: str | None) -> bool:
    return _normalize(nombre) in _ORDINARIAS_NORM


def tipo_de(nombre: str | None) -> str:
    return "Ordinaria" if es_ordinaria(nombre) else "Especial"
