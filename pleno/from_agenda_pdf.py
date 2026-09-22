"""Puente: pleno_agenda_pdf -> pleno_sesiones.

Hallazgo real 2026-09-22 (critique de diseño -> "Peru 0 sesiones"):
pleno/api.py pega contra adp-portal-service, la API JSON del Pleno
UNICAMERAL - dejo de recibir sesiones nuevas despues de la transicion
bicameral de julio 2026 (ultimo registro real: 23 de junio, periodo
"2021-2026"). El 2026-09-15 alguien ya habia encontrado esto y construyo
pleno/agenda_pdf.py (scrapea los PDFs oficiales de sesion en
senado.congreso.gob.pe / diputados.congreso.gob.pe directamente) - YA
esta corriendo en refrescar-pe.yml y YA tiene 19 filas reales frescas.
Pero nunca se conecto con pleno_sesiones (la tabla que Agenda PE y
home.py realmente leen) - quedaba en su propia tabla `pleno_agenda_pdf`,
invisible para el resto de la app. Este modulo cierra ese cable suelto.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pleno.db import Database

# Offset para que los cod_agenda sinteticos nunca choquen con los reales de
# adp-portal-service (secuenciales, <1000 hoy).
COD_AGENDA_OFFSET = 9_000_000

_CAMARA_CODE = {"senado": "S", "diputados": "D"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _demo():
    """Ponytail: 1 chequeo ejecutable de la logica no trivial (mapeo de
    camara, dedup, deteccion de cambios), sin tocar la DB real."""
    import sqlite3
    import tempfile
    from pathlib import Path

    tmpdir = tempfile.mkdtemp()
    dbpath = Path(tmpdir) / "test.db"

    conn = sqlite3.connect(dbpath)
    conn.execute("""CREATE TABLE pleno_agenda_pdf (
        camara TEXT NOT NULL, fecha TEXT NOT NULL, pdf_url TEXT NOT NULL,
        texto TEXT NOT NULL, fetched_at TEXT NOT NULL,
        PRIMARY KEY (camara, fecha, pdf_url))""")
    conn.execute(
        "INSERT INTO pleno_agenda_pdf VALUES (?,?,?,?,?)",
        ("diputados", "2026-09-17", "https://x/a.pdf",
         "CÁMARA DE DIPUTADOS\nSesión del 17 de septiembre de 2026.\nresto...",
         "2026-09-22T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    with Database(dbpath) as db:
        db.init_schema()
        stats = sync_from_agenda_pdf(db)
        assert stats == {"vistos": 1, "nuevos": 1, "actualizados": 0}, stats
        row = db.conn.execute(
            "SELECT titulo, camara, fuente, fecha_sesion FROM pleno_sesiones "
            "WHERE fuente='agenda_pdf'"
        ).fetchone()
        assert row["camara"] == "D", row
        assert row["fecha_sesion"] == "2026-09-17", row
        assert row["titulo"] == "Sesión del 17 de septiembre de 2026", row
        print("OK sync_from_agenda_pdf: crea la fila con camara/fecha/titulo correctos")

        stats2 = sync_from_agenda_pdf(db)
        assert stats2 == {"vistos": 1, "nuevos": 0, "actualizados": 0}, stats2
        print("OK sync_from_agenda_pdf: idempotente, no re-actualiza sin cambios")


if __name__ == "__main__":
    _demo()
