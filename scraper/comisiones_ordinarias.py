"""Catálogo canónico de comisiones del Congreso del Perú, por cámara.

Cubre las 24 Comisiones Ordinarias del período unicameral 2021-2026 (por
nombre) y las comisiones propias del período bicameral 2026-2031 (Senado,
Cámara de Diputados, Bicameral) — estas últimas por comisionId, NO por
nombre: verificado contra el catálogo real del API (2026-09-11) que Senado
y Diputados tienen comisiones con el MISMO nombre exacto (ej. "Justicia y
Derechos Humanos" existe en ambas cámaras, y también en la lista vieja
unicameral) — matchear solo por nombre las hace indistinguibles.

Todo lo que no esté en ninguna de estas listas se considera "Comisión
Especial" (comisiones especiales, subcomisiones, investigadoras, registros
con typos del catálogo del API, etc.) y se agrupa bajo el rótulo
"Comisiones Especiales" en el frontend.

Match de nombres insensible a tildes, mayúsculas y espacios extra para
tolerar variantes ortográficas que pueda traer el API.
"""
from __future__ import annotations

import unicodedata

# IDs reales del catálogo del Senado (verificado 2026-09-11 contra
# GET /comisiones — no hay endpoint que separe por cámara, así que esto es
# un mapeo manual de IDs. Si el Congreso agrega/renumera comisiones,
# actualizar acá (mismo mantenimiento que COMISIONES_ORDINARIAS de abajo).
COMISIONES_SENADO_IDS: set[int] = set(range(61, 72))  # 61-71 (11 comisiones)

# IDs reales del catálogo de la Cámara de Diputados (idem, 2026-09-11).
COMISIONES_DIPUTADOS_IDS: set[int] = set(range(72, 91))  # 72-90 (19 comisiones)

# Comisión bicameral (ambas cámaras en conjunto) — hoy solo existe esta.
COMISIONES_BICAMERAL_IDS: set[int] = {60}  # "Bicameral de Presupuesto y de la Cuenta General de la República"

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


def tipo_de(comision_id: int | None, nombre: str | None = None) -> str:
    """Clasifica una comisión: 'Ordinaria' (24 del período unicameral,
    por nombre), 'Senado'/'Diputados'/'Bicameral' (período bicameral, por
    comisionId — el nombre NO alcanza, ver docstring del módulo), o
    'Especial' (todo lo demás: especiales, subcomisiones, investigadoras,
    basura del catálogo)."""
    if comision_id in COMISIONES_SENADO_IDS:
        return "Senado"
    if comision_id in COMISIONES_DIPUTADOS_IDS:
        return "Diputados"
    if comision_id in COMISIONES_BICAMERAL_IDS:
        return "Bicameral"
    if es_ordinaria(nombre):
        return "Ordinaria"
    return "Especial"
