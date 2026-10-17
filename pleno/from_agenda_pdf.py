"""Puente: pleno_agenda_pdf -> pleno_sesiones.

La API de pleno/api.py es la del Pleno unicameral y ya no recibe sesiones;
las del bicameral estan en pleno_agenda_pdf (pleno/agenda_pdf.py). Agenda
PE y home.py leen pleno_sesiones, asi que se copian ahi.
"""
from __future__ import annotations

from core.db import now_iso
from pleno.db import Database

# Offset para que los cod_agenda sinteticos nunca choquen con los reales de
# adp-portal-service (secuenciales, <1000 hoy).
COD_AGENDA_OFFSET = 9_000_000

_CAMARA_CODE = {"senado": "S", "diputados": "D"}


def _titulo_de_texto(texto: str, camara: str, fecha: str) -> str:
    """La 2da linea del PDF suele ser 'Sesión del 17 de setiembre de 2026.'
    - la usamos si esta ahi, si no armamos un titulo generico."""
    for linea in (texto or "").splitlines()[:4]:
        linea = linea.strip()
        if linea.lower().startswith("sesi"):
            return linea.rstrip(".")
    return f"Sesión del Pleno de {camara.title()} - {fecha}"


def sync_from_agenda_pdf(db: Database) -> dict:
    """Lee pleno_agenda_pdf y upsertea en pleno_sesiones (fuente=
    'agenda_pdf'). Requiere que pleno.agenda_pdf.run_sync() ya haya corrido
    en este mismo archivo (mismo proyectos.db, tabla ya creada/poblada por
    el paso de refrescar-pe.yml que corre antes)."""
    stats = {"vistos": 0, "nuevos": 0, "actualizados": 0}
    now = now_iso()

    tablas = {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pleno_agenda_pdf'"
    )}
    if "pleno_agenda_pdf" not in tablas:
        return stats  # pleno.agenda_pdf sync todavia no corrio en esta DB

    rows = db.conn.execute(
        "SELECT rowid, camara, fecha, pdf_url, texto FROM pleno_agenda_pdf"
    ).fetchall()

    with db.tx() as c:
        for r in rows:
            stats["vistos"] += 1
            cod_agenda = COD_AGENDA_OFFSET + r["rowid"]
            camara_code = _CAMARA_CODE.get((r["camara"] or "").lower())
            titulo = _titulo_de_texto(r["texto"], r["camara"], r["fecha"])
            existing = c.execute(
                "SELECT fecha_sesion, titulo, camara, last_changed_at "
                "FROM pleno_sesiones WHERE cod_agenda=?",
                (cod_agenda,),
            ).fetchone()
            if existing is None:
                c.execute(
                    """INSERT INTO pleno_sesiones
                       (cod_agenda, fecha_sesion, titulo, camara,
                        fuente, url_publicacion,
                        first_seen_at, last_seen_at, last_changed_at)
                       VALUES (?,?,?,?,'agenda_pdf',?,?,?,?)""",
                    (cod_agenda, r["fecha"], titulo, camara_code,
                     r["pdf_url"], now, now, now),
                )
                stats["nuevos"] += 1
                continue
            changed = (existing["fecha_sesion"] != r["fecha"]
                       or existing["titulo"] != titulo
                       or existing["camara"] != camara_code)
            c.execute(
                """UPDATE pleno_sesiones SET fecha_sesion=?, titulo=?, camara=?,
                   last_seen_at=?, last_changed_at=?
                   WHERE cod_agenda=?""",
                (r["fecha"], titulo, camara_code, now,
                 now if changed else existing["last_changed_at"], cod_agenda),
            )
            if changed:
                stats["actualizados"] += 1
    return stats
