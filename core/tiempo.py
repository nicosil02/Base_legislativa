"""Hora de Lima y Quito (UTC-5 todo el anio, sin horario de verano)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LIMA = timezone(timedelta(hours=-5), "America/Lima")


def ahora_lima() -> datetime:
    return datetime.now(LIMA)


def hoy_lima() -> str:
    return ahora_lima().date().isoformat()
