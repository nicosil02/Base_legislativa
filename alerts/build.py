"""Construye el payload del alerta diaria desde las DBs PE + EC.

Detecta:
  - Nuevos PLs presentados en las ultimas 24h (first_seen_at).
  - Nuevos dictamenes / cambios de fase relevantes:
      * PE: estado contiene "DICTAMEN"
      * EC: estado en una lista cerrada (INFORME PARA PRIMER DEBATE,
        REGISTRO OFICIAL, etc.)

Devuelve un dict con la estructura que `alerts.template.render_html` espera.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

PE_PORTAL_URL = "https://wb2server.congreso.gob.pe/spley-portal/#/expediente/{per_par_id}/{pley_num}"
EC_PORTAL_URL = "https://proyectosdeley.asambleanacional.gob.ec/report"

EC_DICTAMEN_STATES = (
    "INFORME PARA PRIMER DEBATE",
    "INFORME PARA SEGUNDO DEBATE",
    "AVOCO DEL PROYECTO POR PARTE DE LA COMISION",
    "INFORME NO VINCULANTE UTL",
    "REGISTRO OFICIAL",
)


def _find_db_file(filename, search_root=None):
    here = (search_root or Path(__file__).resolve().parent).resolve()
    candidates = [here / filename, Path.cwd() / filename]
    cur = here
    for _ in range(6):
        candidates.append(cur / filename)
        cur = cur.parent
    for p in candidates:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.resolve()
    return None


def _open_ro(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _peru_new_pls(conn, since_iso):
    # Filtramos por fec_presentacion (fecha oficial) y no first_seen_at
    # (cuando lo vio nuestro scraper) para evitar ruido el primer dia
    # despues de un bootstrap masivo. Compara date() para ser tolerante a
    # formatos ISO con timestamp vs date-only.
    rows = conn.execute(
        """SELECT per_par_id, pley_num, proyecto_ley, titulo, tema, estado,
                  fec_presentacion, url_portal
           FROM proyectos
           WHERE date(fec_presentacion) >= date(?)
           ORDER BY tema, fec_presentacion DESC""",
        (since_iso,),
    ).fetchall()
    return [
        {
            "id": r["proyecto_ley"],
            "titulo": r["titulo"],
            "tema": r["tema"] or "Otros",
            "estado": r["estado"],
            "fecha": r["fec_presentacion"],
            "url": r["url_portal"] or PE_PORTAL_URL.format(
                per_par_id=r["per_par_id"], pley_num=r["pley_num"]
            ),
        }
        for r in rows
    ]


def _peru_new_dictamenes(conn, since_iso):
    # PE no tiene historial_cambios; usa la tabla seguimientos (fecha + estado por fase).
    rows = conn.execute(
        """SELECT p.per_par_id, p.pley_num, p.proyecto_ley, p.titulo, p.tema,
                  s.estado AS estado, p.fec_presentacion, p.url_portal,
                  s.fecha AS changed_at
           FROM seguimientos s
           JOIN proyectos p ON p.per_par_id = s.per_par_id AND p.pley_num = s.pley_num
           WHERE date(s.fecha) >= date(?)
             AND UPPER(s.estado) LIKE '%DICTAMEN%'
           ORDER BY p.tema, s.fecha DESC""",
        (since_iso,),
    ).fetchall()
    return [
        {
            "id": r["proyecto_ley"],
            "titulo": r["titulo"],
            "tema": r["tema"] or "Otros",
            "estado": r["estado"],
            "fecha": (r["changed_at"] or r["fec_presentacion"])[:10],
            "url": r["url_portal"] or PE_PORTAL_URL.format(
                per_par_id=r["per_par_id"], pley_num=r["pley_num"]
            ),
        }
        for r in rows
    ]


def _ecuador_new_pls(conn, since_iso):
    rows = conn.execute(
        """SELECT n_tramite, titulo, tema, estado, fec_presentacion
           FROM proyectos
           WHERE date(fec_presentacion) >= date(?)
           ORDER BY tema, fec_presentacion DESC""",
        (since_iso,),
    ).fetchall()
    return [
        {
            "id": r["n_tramite"],
            "titulo": r["titulo"],
            "tema": r["tema"] or "Otros",
            "estado": r["estado"],
            "fecha": r["fec_presentacion"],
            "url": EC_PORTAL_URL,
        }
        for r in rows
    ]


def _ecuador_new_dictamenes(conn, since_iso):
    placeholders = ",".join("?" * len(EC_DICTAMEN_STATES))
    rows = conn.execute(
        f"""SELECT p.n_tramite, p.titulo, p.tema, h.valor_despues AS estado,
                   p.fec_presentacion, h.changed_at
            FROM historial_cambios h
            JOIN proyectos p ON p.n_tramite = h.n_tramite
            WHERE date(h.changed_at) >= date(?)
              AND h.campo = 'estado'
              AND h.valor_despues IN ({placeholders})
            ORDER BY p.tema, h.changed_at DESC""",
        (since_iso, *EC_DICTAMEN_STATES),
    ).fetchall()
    return [
        {
            "id": r["n_tramite"],
            "titulo": r["titulo"],
            "tema": r["tema"] or "Otros",
            "estado": r["estado"],
            "fecha": (r["changed_at"] or r["fec_presentacion"])[:10],
            "url": EC_PORTAL_URL,
        }
        for r in rows
    ]


def _peru_sesiones_proximas(conn, days_ahead=2):
    """Sesiones convocadas para hoy + N dias siguientes con sus PLs en agenda.

    Devuelve una lista de dicts agrupables: {comision, fecha, hora, nombre,
    estado, link_teams, pls=[{pley_num, proyecto_ley, titulo, tema, estado}]}.
    Si la tabla `sesiones` no existe (porque sesiones/ no esta inicializado),
    devuelve lista vacia sin error.
    """
    # Validar que la tabla exista
    try:
        conn.execute("SELECT 1 FROM sesiones LIMIT 1")
    except Exception:
        return []
    today = datetime.now(timezone.utc).date()
    hasta = (today + timedelta(days=days_ahead)).isoformat()
    desde = today.isoformat()
    rows = conn.execute(
        """SELECT s.id_sesion, s.fecha, s.hora_inicio, s.hora_fin,
                  s.nombre_comision, s.nombre_sesion, s.estado, s.link_teams
           FROM sesiones s
           WHERE s.fecha >= ? AND s.fecha <= ?
             AND UPPER(COALESCE(s.estado,'')) = 'CONVOCADA'
           ORDER BY s.fecha, s.hora_inicio""",
        (desde, hasta),
    ).fetchall()
    out = []
    for r in rows:
        pls = conn.execute(
            """SELECT pr.pley_num, p.proyecto_ley, p.titulo, p.tema, p.estado
               FROM sesion_pl_referenciado pr
               LEFT JOIN proyectos p ON p.pley_num = pr.pley_num AND p.per_par_id = pr.per_par_id
               WHERE pr.id_sesion = ? ORDER BY pr.pley_num""",
            (r["id_sesion"],),
        ).fetchall()
        out.append({
            "id_sesion": r["id_sesion"],
            "fecha": r["fecha"],
            "hora": r["hora_inicio"],
            "comision": r["nombre_comision"],
            "nombre": r["nombre_sesion"],
            "estado": r["estado"],
            "link_teams": r["link_teams"],
            "pls": [
                {
                    "pley_num": pl["pley_num"],
                    "proyecto_ley": pl["proyecto_ley"],
                    "titulo": pl["titulo"],
                    "tema": pl["tema"] or "Otros",
                    "estado": pl["estado"],
                }
                for pl in pls
            ],
        })
    return out


def build_alert(now=None, window_hours=24, db_pe_path=None, db_ec_path=None,
                sesiones_days_ahead=2):
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=window_hours)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "fecha": now.strftime("%Y-%m-%d"),
        "since": since_iso,
        "peru":    {"dictamenes": [], "proyectos": [], "sesiones_proximas": []},
        "ecuador": {"dictamenes": [], "proyectos": []},
    }

    db_pe = db_pe_path or _find_db_file("proyectos.db")
    if db_pe:
        try:
            conn = _open_ro(db_pe)
            try:
                payload["peru"]["dictamenes"] = _peru_new_dictamenes(conn, since_iso)
                payload["peru"]["proyectos"] = _peru_new_pls(conn, since_iso)
                payload["peru"]["sesiones_proximas"] = _peru_sesiones_proximas(
                    conn, days_ahead=sesiones_days_ahead
                )
            finally:
                conn.close()
        except Exception as e:
            print(f"[alerts] error leyendo Peru DB ({db_pe}): {e}")

    db_ec = db_ec_path or _find_db_file("proyectos_ec.db")
    if db_ec:
        try:
            conn = _open_ro(db_ec)
            try:
                payload["ecuador"]["dictamenes"] = _ecuador_new_dictamenes(conn, since_iso)
                payload["ecuador"]["proyectos"] = _ecuador_new_pls(conn, since_iso)
            finally:
                conn.close()
        except Exception as e:
            print(f"[alerts] error leyendo Ecuador DB ({db_ec}): {e}")

    return payload


def has_content(payload):
    if any(
        len(payload[country][section]) > 0
        for country in ("peru", "ecuador")
        for section in ("dictamenes", "proyectos")
    ):
        return True
    # Sesiones proximas con al menos 1 PL en agenda tambien cuentan como contenido
    return any(
        len(s.get("pls") or []) > 0
        for s in payload.get("peru", {}).get("sesiones_proximas", []) or []
    )


def count_items(payload):
    base = sum(
        len(payload[country][section])
        for country in ("peru", "ecuador")
        for section in ("dictamenes", "proyectos")
    )
    sesiones_con_pls = sum(
        1 for s in payload.get("peru", {}).get("sesiones_proximas", []) or []
        if (s.get("pls") or [])
    )
    return base + sesiones_con_pls
