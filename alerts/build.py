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
    # Filtramos por first_seen_at (cuando ENTRO a nuestra DB) en lugar
    # de fec_presentacion. Asi cada PL sale 1 sola vez en la primera
    # alerta despues de detectarlo — si fec_presentacion era ayer pero
    # nuestro scraper recien lo vio hoy, sigue siendo "nuevo" para el
    # usuario. La comparacion es precisa a nivel timestamp.
    rows = conn.execute(
        """SELECT per_par_id, pley_num, proyecto_ley, titulo, tema, estado,
                  fec_presentacion, url_portal
           FROM proyectos
           WHERE first_seen_at > ?
           ORDER BY tema, first_seen_at DESC""",
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
    # seguimientos.fecha tiene hora precisa, comparamos a nivel timestamp
    # para que cada dictamen salga 1 vez (no se repita por cambio de dia).
    rows = conn.execute(
        """SELECT p.per_par_id, p.pley_num, p.proyecto_ley, p.titulo, p.tema,
                  s.estado AS estado, p.fec_presentacion, p.url_portal,
                  s.fecha AS changed_at
           FROM seguimientos s
           JOIN proyectos p ON p.per_par_id = s.per_par_id AND p.pley_num = s.pley_num
           WHERE s.fecha > ?
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
    # Mismo cambio que PE: usar first_seen_at en lugar de fec_presentacion
    # para que cada PL salga 1 sola vez.
    rows = conn.execute(
        """SELECT n_tramite, titulo, tema, estado, fec_presentacion
           FROM proyectos
           WHERE first_seen_at > ?
           ORDER BY tema, first_seen_at DESC""",
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
    # Comparacion timestamp precisa para que cada cambio de estado salga 1 vez
    rows = conn.execute(
        f"""SELECT p.n_tramite, p.titulo, p.tema, h.valor_despues AS estado,
                   p.fec_presentacion, h.changed_at
            FROM historial_cambios h
            JOIN proyectos p ON p.n_tramite = h.n_tramite
            WHERE h.changed_at > ?
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


def _ecuador_sesiones_proximas(conn, days_ahead=2):
    """Sesiones de la Asamblea Nacional EC para hoy + N dias siguientes.
    Similar a _peru_sesiones_proximas pero usando tablas sesiones_ec /
    sesion_ec_pl_referenciado."""
    try:
        conn.execute("SELECT 1 FROM sesiones_ec LIMIT 1")
    except Exception:
        return []
    today = datetime.now(timezone.utc).date()
    hasta = (today + timedelta(days=days_ahead)).isoformat()
    desde = today.isoformat()
    rows = conn.execute(
        """SELECT s.uid, s.fecha, s.hora_inicio, s.hora_fin,
                  s.nombre_comision, s.summary
           FROM sesiones_ec s
           WHERE s.fecha >= ? AND s.fecha <= ?
           ORDER BY s.fecha, s.hora_inicio""",
        (desde, hasta),
    ).fetchall()
    out = []
    for r in rows:
        pls = conn.execute(
            """SELECT m.n_tramite, p.titulo, p.tema, p.estado
               FROM sesion_ec_pl_referenciado m
               LEFT JOIN proyectos p ON p.n_tramite = m.n_tramite
               WHERE m.uid = ? AND m.n_tramite IS NOT NULL
               ORDER BY m.score DESC""",
            (r["uid"],),
        ).fetchall()
        # Limpiar "modalidad X" del summary
        nombre = (r["summary"] or "").strip()
        for tok in (", modalidad", " modalidad"):
            idx = nombre.lower().find(tok)
            if idx >= 0:
                nombre = nombre[:idx].rstrip(" ,.;")
                break
        out.append({
            "uid": r["uid"],
            "fecha": r["fecha"],
            "hora": r["hora_inicio"],
            "comision": r["nombre_comision"] or "—",
            "nombre": nombre,
            "pls": [
                {
                    "n_tramite": pl["n_tramite"],
                    "titulo": pl["titulo"],
                    "tema": pl["tema"] or "Otros",
                    "estado": pl["estado"],
                }
                for pl in pls
            ],
        })
    return out


def build_alert(now=None, window_hours=24, db_pe_path=None, db_ec_path=None,
                sesiones_days_ahead=2, since_iso=None):
    """Construye el payload de la alerta.

    Args:
        since_iso: timestamp ISO desde donde filtrar. Si None, calcula
            como now - window_hours (default). El caller (cli.py) puede
            pasar el sent_at de la ultima alerta exitosa para evitar
            duplicar items entre corridas — cada cambio sale 1 vez en
            la primera alerta despues de su fecha.
    """
    now = now or datetime.now(timezone.utc)
    if since_iso is None:
        since = now - timedelta(hours=window_hours)
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "fecha": now.strftime("%Y-%m-%d"),
        "since": since_iso,
        "peru":    {"dictamenes": [], "proyectos": [], "sesiones_proximas": []},
        "ecuador": {"dictamenes": [], "proyectos": [], "sesiones_proximas": []},
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
                payload["ecuador"]["sesiones_proximas"] = _ecuador_sesiones_proximas(
                    conn, days_ahead=sesiones_days_ahead
                )
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
    # Sesiones proximas con al menos 1 PL en agenda (en cualquier pais) cuentan
    for country in ("peru", "ecuador"):
        if any(
            len(s.get("pls") or []) > 0
            for s in payload.get(country, {}).get("sesiones_proximas", []) or []
        ):
            return True
    return False


def count_items(payload):
    base = sum(
        len(payload[country][section])
        for country in ("peru", "ecuador")
        for section in ("dictamenes", "proyectos")
    )
    sesiones_con_pls = sum(
        1
        for country in ("peru", "ecuador")
        for s in payload.get(country, {}).get("sesiones_proximas", []) or []
        if (s.get("pls") or [])
    )
    return base + sesiones_con_pls
