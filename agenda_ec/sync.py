"""Sync diario: descarga ICS de Zimbra + parse + import + matching de PLs.

Pipeline:
  1. Download ICS con filtro de rango temporal (epoch ms) ~1 MB para 5 meses
  2. Parse VEVENTs con ics_parser
  3. Upsert en sesiones_ec
  4. Re-matchea PLs por descripcion contra proyectos.titulo
"""
from __future__ import annotations

import sqlite3
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from .ics_parser import IcsEvent, parse_events
from .matching import build_idf, extract_comision, extract_modalidad, find_matches
from .schema import SCHEMA_AGENDA_EC


ZIMBRA_BASE = (
    "https://correo.asambleanacional.gob.ec/home/"
    "direccion.comunicacion@asambleanacional.gob.ec/Actividades.ics"
)
USER_AGENT = "Mozilla/5.0 (compatible; ValiIntelligence/1.0)"


def _ms(dt: datetime) -> int:
    """Convierte datetime aware a epoch ms (entero)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def download_ics(days_back: int = 60, days_fwd: int = 120, timeout: int = 120) -> str:
    """Descarga el ICS filtrado por rango temporal.

    Args:
        days_back: dias hacia atras desde hoy (default 60 - 2 meses)
        days_fwd: dias hacia adelante (default 120 - 4 meses)
        timeout: timeout HTTP en segundos

    Returns:
        Texto del ICS (utf-8).
    """
    now = datetime.now(timezone.utc)
    start_ms = _ms(now - timedelta(days=days_back))
    end_ms = _ms(now + timedelta(days=days_fwd))
    url = f"{ZIMBRA_BASE}?start={start_ms}&end={end_ms}"

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def init_schema(conn: sqlite3.Connection) -> None:
    """Crea las tablas de agenda si no existen."""
    with conn:
        conn.executescript(SCHEMA_AGENDA_EC)


def _row_from_event(ev: IcsEvent, captured_at: str) -> dict:
    """Mapea IcsEvent -> dict para INSERT en sesiones_ec."""
    fecha = ev.dtstart.strftime("%Y-%m-%d") if ev.dtstart else ""
    hora_inicio = ev.dtstart.strftime("%H:%M") if ev.dtstart else None
    hora_fin = ev.dtend.strftime("%H:%M") if ev.dtend else None
    return {
        "uid": ev.uid,
        "summary": ev.summary or "(sin titulo)",
        "nombre_comision": extract_comision(ev.summary),
        "modalidad": extract_modalidad(ev.summary, ev.location),
        "fecha": fecha,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "descripcion": ev.description,
        "location": ev.location,
        "status": ev.status,
        "last_modified": ev.last_modified,
        "captured_at": captured_at,
    }


def upsert_events(conn: sqlite3.Connection, events: list[IcsEvent]) -> tuple[int, int]:
    """Inserta/actualiza eventos en sesiones_ec.

    Returns:
        (nuevos, actualizados)
    """
    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nuevos = 0
    actualizados = 0
    with conn:
        for ev in events:
            if not ev.uid or not ev.dtstart:
                continue
            row = _row_from_event(ev, captured_at)
            existing = conn.execute(
                "SELECT last_modified FROM sesiones_ec WHERE uid = ?", (ev.uid,)
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO sesiones_ec
                      (uid, summary, nombre_comision, modalidad, fecha,
                       hora_inicio, hora_fin, descripcion, location, status,
                       last_modified, captured_at)
                    VALUES (:uid,:summary,:nombre_comision,:modalidad,:fecha,
                            :hora_inicio,:hora_fin,:descripcion,:location,:status,
                            :last_modified,:captured_at)
                    """,
                    row,
                )
                nuevos += 1
            else:
                conn.execute(
                    """
                    UPDATE sesiones_ec SET
                      summary=:summary, nombre_comision=:nombre_comision,
                      modalidad=:modalidad, fecha=:fecha,
                      hora_inicio=:hora_inicio, hora_fin=:hora_fin,
                      descripcion=:descripcion, location=:location,
                      status=:status, last_modified=:last_modified,
                      captured_at=:captured_at
                    WHERE uid=:uid
                    """,
                    row,
                )
                actualizados += 1
    return nuevos, actualizados


def rematch_all(conn: sqlite3.Connection) -> int:
    """Borra y recalcula los matches de PL para TODAS las sesiones.

    Precalcula la lista de proyectos y el IDF map UNA SOLA VEZ (no por
    sesion) para que sea O(N_sesiones * N_proyectos) en vez de
    O(N_sesiones * (N_proyectos * 2)).
    """
    pl_rows = [
        (r[0], r[1])
        for r in conn.execute(
            "SELECT n_tramite, titulo FROM proyectos "
            "WHERE titulo IS NOT NULL AND length(titulo) >= 20"
        ).fetchall()
    ]
    idf = build_idf(pl_rows)
    print(f"[agenda_ec] indice IDF: {len(pl_rows)} proyectos, {len(idf)} tokens unicos")

    total_matches = 0
    with conn:
        conn.execute("DELETE FROM sesion_ec_pl_referenciado")
        rows = conn.execute(
            "SELECT uid, summary, descripcion FROM sesiones_ec"
        ).fetchall()
        for uid, summary, descripcion in rows:
            matches = find_matches(
                conn, descripcion or "", summary or "",
                idf=idf, pl_rows=pl_rows,
            )
            for m in matches:
                conn.execute(
                    """
                    INSERT INTO sesion_ec_pl_referenciado
                      (uid, n_tramite, match_text, score)
                    VALUES (?,?,?,?)
                    """,
                    (uid, m.n_tramite, m.match_text[:200], m.score),
                )
                total_matches += 1
    return total_matches


def sync(
    conn: sqlite3.Connection,
    days_back: int = 60,
    days_fwd: int = 120,
) -> dict:
    """Ejecuta el sync completo y devuelve estadisticas."""
    t0 = time.time()
    print(f"[agenda_ec] descargando ICS (-{days_back}d / +{days_fwd}d)...")
    text = download_ics(days_back=days_back, days_fwd=days_fwd)
    size_kb = len(text.encode("utf-8")) // 1024
    print(f"[agenda_ec] descargado {size_kb} KB en {time.time()-t0:.1f}s")

    init_schema(conn)

    t1 = time.time()
    events = list(parse_events(text))
    print(f"[agenda_ec] parseados {len(events)} VEVENTs en {time.time()-t1:.1f}s")

    t2 = time.time()
    nuevos, actualizados = upsert_events(conn, events)
    print(f"[agenda_ec] upsert: {nuevos} nuevos, {actualizados} actualizados ({time.time()-t2:.1f}s)")

    t3 = time.time()
    total_matches = rematch_all(conn)
    print(f"[agenda_ec] rematch: {total_matches} matches en {time.time()-t3:.1f}s")

    return {
        "events_parsed": len(events),
        "nuevos": nuevos,
        "actualizados": actualizados,
        "matches": total_matches,
        "elapsed_sec": time.time() - t0,
    }
