"""Parser minimo de iCalendar (RFC 5545).

No usamos la libreria `ics` ni `icalendar` para mantener el repo sin deps
extra — solo necesitamos extraer VEVENTs del feed de Zimbra y no manejamos
recurrencias complejas (RRULE/EXDATE), el calendario de la Asamblea no las usa.

Soporta:
  - Line unfolding (CRLF + leading whitespace)
  - Properties con params (DTSTART;TZID=...)
  - Escapes RFC 5545 (\\n, \\,, \\;, \\\\)
  - DTSTART/DTEND con TZID o "Z" (UTC) o naive
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # Python <3.9


# Convertimos todo a hora local Ecuador (UTC-5) para que el storage sea
# uniforme y la UI no tenga que recomputar timezones.
EC_TZ = ZoneInfo("America/Guayaquil") if ZoneInfo else None


@dataclass
class IcsEvent:
    uid: str = ""
    summary: str = ""
    description: str = ""
    location: str = ""
    status: str = ""
    last_modified: str = ""
    dtstart: datetime | None = None
    dtend: datetime | None = None
    raw_params: dict[str, dict[str, str]] = field(default_factory=dict)


def _unfold(text: str) -> list[str]:
    """Une lineas continuadas (RFC 5545 §3.1): un line break seguido de
    whitespace es una continuacion del valor anterior."""
    # Normalizar line endings antes de splittear
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in text.split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(s: str) -> str:
    """Revierte los escapes del valor texto del ICS."""
    # El orden importa: primero \\ para no doble-procesar
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n" or nxt == "N":
                out.append("\n")
            elif nxt in ",;\\":
                out.append(nxt)
            else:
                out.append(s[i])
                out.append(nxt)
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _parse_property(line: str) -> tuple[str, dict[str, str], str]:
    """Devuelve (NAME, params_dict, raw_value).

    Ejemplos:
      "DTSTART;TZID=America/Guayaquil:20260128T103000" ->
        ("DTSTART", {"TZID": "America/Guayaquil"}, "20260128T103000")
    """
    idx = line.find(":")
    if idx < 0:
        return "", {}, ""
    head = line[:idx]
    value = line[idx + 1 :]

    parts = head.split(";")
    name = parts[0].strip().upper()
    params: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip().upper()] = v.strip().strip('"')
    return name, params, value


def _parse_datetime(value: str, tzid: str | None) -> datetime | None:
    """Parsea un DT-VALUE de iCalendar.

    Formatos soportados:
      - YYYYMMDDTHHMMSS (naive, asume tzid si esta)
      - YYYYMMDDTHHMMSSZ (UTC)
      - YYYYMMDD (date-only)
    """
    if not value:
        return None
    try:
        if "T" in value:
            is_utc = value.endswith("Z")
            clean = value.rstrip("Z")
            dt = datetime.strptime(clean, "%Y%m%dT%H%M%S")
            if is_utc:
                dt = dt.replace(tzinfo=timezone.utc)
            elif tzid and ZoneInfo is not None:
                try:
                    dt = dt.replace(tzinfo=ZoneInfo(tzid))
                except Exception:
                    pass  # fallback naive
            return dt
        else:
            return datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None


def parse_events(ics_text: str) -> Iterator[IcsEvent]:
    """Itera VEVENTs del texto iCalendar.

    Convierte DTSTART/DTEND a timezone America/Guayaquil para consistencia
    (asi en la DB siempre guardamos hora local EC sin importar de que TZ vino).

    IMPORTANTE: ignora props dentro de subcomponentes anidados (VALARM,
    VTIMEZONE, etc.) — si no, "DESCRIPTION:Reminder" del VALARM pisa
    el DESCRIPTION real del VEVENT.
    """
    lines = _unfold(ics_text)
    current: IcsEvent | None = None
    # nesting > 0 cuando estamos dentro de un subcomponente del VEVENT
    # (ej VALARM). Solo procesamos props con nesting == 0 dentro del VEVENT.
    nesting = 0
    for line in lines:
        line_stripped = line.strip()
        if line_stripped == "BEGIN:VEVENT":
            current = IcsEvent()
            nesting = 0
            continue
        if line_stripped == "END:VEVENT":
            if current is not None:
                # Normalizar timezone a EC
                if current.dtstart and current.dtstart.tzinfo is not None and EC_TZ is not None:
                    current.dtstart = current.dtstart.astimezone(EC_TZ)
                if current.dtend and current.dtend.tzinfo is not None and EC_TZ is not None:
                    current.dtend = current.dtend.astimezone(EC_TZ)
                yield current
            current = None
            nesting = 0
            continue
        if current is None:
            continue
        # Subcomponentes anidados (VALARM, etc.) — saltar todas sus props
        if line_stripped.startswith("BEGIN:"):
            nesting += 1
            continue
        if line_stripped.startswith("END:"):
            nesting = max(0, nesting - 1)
            continue
        if nesting > 0:
            continue

        name, params, value = _parse_property(line)
        if not name:
            continue

        if name == "UID":
            current.uid = value
        elif name == "SUMMARY":
            current.summary = _unescape(value)
        elif name == "DESCRIPTION":
            current.description = _unescape(value)
        elif name == "LOCATION":
            current.location = _unescape(value)
        elif name == "STATUS":
            current.status = value
        elif name == "LAST-MODIFIED":
            current.last_modified = value
        elif name == "DTSTART":
            current.dtstart = _parse_datetime(value, params.get("TZID"))
        elif name == "DTEND":
            current.dtend = _parse_datetime(value, params.get("TZID"))
