"""Catálogo de comisiones del Congreso del Perú, por cámara.

Las 24 ordinarias del período 2021-2026 van por nombre; las del período
bicameral van por comisionId, porque Senado y Diputados repiten nombres.
Todo lo demás es "Especial".
"""
from __future__ import annotations

from core.text import norm

# IDs del Senado a mano: el API no separa por cámara. Actualizar si el
# Congreso agrega o renumera comisiones.
COMISIONES_SENADO_IDS: set[int] = set(range(61, 72))  # 61-71 (11 comisiones)

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


normalize = norm  # minúsculas, sin tildes, espacios simples


# Tipos de comisión de cada cámara: los nombres se resuelven solo contra el
# catálogo de la cámara del PL (Senado y Diputados repiten nombres).
TIPOS_POR_CAMARA: dict[str, tuple[str, ...]] = {
    "C": ("Ordinaria", "Bicameral"),
    "D": ("Diputados",),
    "S": ("Senado",),
}


_ORDINARIAS_NORM: set[str] = {normalize(n) for n in COMISIONES_ORDINARIAS}


def es_ordinaria(nombre: str | None) -> bool:
    return normalize(nombre) in _ORDINARIAS_NORM


def tipo_de(comision_id: int | None, nombre: str | None = None) -> str:
    """'Senado'/'Diputados'/'Bicameral' por id, 'Ordinaria' por nombre, o 'Especial'."""
    if comision_id in COMISIONES_SENADO_IDS:
        return "Senado"
    if comision_id in COMISIONES_DIPUTADOS_IDS:
        return "Diputados"
    if comision_id in COMISIONES_BICAMERAL_IDS:
        return "Bicameral"
    if es_ordinaria(nombre):
        return "Ordinaria"
    return "Especial"
