"""Merge de sesiones_transcripciones entre dos snapshots de proyectos.db.

data/proyectos.db.gz es un blob binario compartido por workflows que
tocan tablas totalmente distintas: vigilar-congreso.yml/backfill-vod.yml
solo escriben sesiones_transcripciones; refrescar-pe.yml escribe PLs,
agenda, noticias, etc (y ahora tambien sesiones_transcripciones via
captions). "git rebase -X theirs" en un conflicto de push descarta el
archivo COMPLETO de un lado, no solo las filas en pugna - causa real de
perdida de datos verificada en vivo 2026-09-15 (dos veces el mismo dia:
Presupuesto/Transportes borrados por un push de refrescar-pe.yml que
partia de un snapshot mas viejo).

Uso: python -m congreso_live.merge_db BASE.db DONOR.db
  Modifica BASE.db in-place: le agrega/actualiza (por video_id) las filas
  de sesiones_transcripciones que DONOR.db tiene y BASE.db no tiene (o
  tiene con menos texto) - nunca toca ninguna otra tabla de BASE.db.
"""
from __future__ import annotations

import sqlite3
import sys


def merge_sesiones(base_path: str, donor_path: str) -> int:
    """Devuelve cuantas filas se agregaron/actualizaron en base_path."""
    base = sqlite3.connect(base_path)
    base.execute("ATTACH DATABASE ? AS donor", (donor_path,))
    cols = [r[1] for r in base.execute("PRAGMA table_info(sesiones_transcripciones)")]
    col_list = ", ".join(cols)
    antes = base.execute("SELECT COUNT(*) FROM sesiones_transcripciones").fetchone()[0]
    base.execute(f"""
        INSERT OR REPLACE INTO sesiones_transcripciones ({col_list})
        SELECT {col_list} FROM donor.sesiones_transcripciones AS d
        WHERE NOT EXISTS (
            SELECT 1 FROM sesiones_transcripciones b
            WHERE b.video_id = d.video_id AND length(b.texto) >= length(d.texto)
        )
    """)
    base.commit()
    despues = base.execute("SELECT COUNT(*) FROM sesiones_transcripciones").fetchone()[0]
    nuevas_o_actualizadas = base.total_changes
    base.close()
    return max(despues - antes, 0) or nuevas_o_actualizadas


def _demo():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        b = str(Path(td) / "base.db")
        d = str(Path(td) / "donor.db")
        for p in (b, d):
            c = sqlite3.connect(p)
            c.execute("""CREATE TABLE sesiones_transcripciones (
                video_id TEXT PRIMARY KEY, tipo TEXT, titulo TEXT,
                fecha TEXT, duracion_seg INTEGER, texto TEXT,
                temas TEXT, fetched_at TEXT)""")
            c.commit()
            c.close()

        cb = sqlite3.connect(b)
        cb.execute("INSERT INTO sesiones_transcripciones VALUES "
                   "('A','t','tit',NULL,10,'hola','',NULL)")
        cb.commit()
        cb.close()

        cd = sqlite3.connect(d)
        cd.execute("INSERT INTO sesiones_transcripciones VALUES "
                   "('B','t','tit',NULL,20,'chau','',NULL)")
        # Mismo video_id que base, pero con MENOS texto - no debe pisar.
        cd.execute("INSERT INTO sesiones_transcripciones VALUES "
                   "('A','t','tit',NULL,10,'ho','',NULL)")
        cd.commit()
        cd.close()

        merge_sesiones(b, d)

        cb = sqlite3.connect(b)
        filas = {r[0]: r[1] for r in cb.execute(
            "SELECT video_id, texto FROM sesiones_transcripciones")}
        cb.close()
        assert filas == {"A": "hola", "B": "chau"}, filas
    print("OK merge_db: agrega filas nuevas del donor sin pisar filas "
          "mas completas de la base")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "test":
        _demo()
    elif len(sys.argv) == 3:
        n = merge_sesiones(sys.argv[1], sys.argv[2])
        print(f"merge_db: {n} fila(s) agregada(s)/actualizada(s) desde {sys.argv[2]}")
    else:
        print("Uso: python -m congreso_live.merge_db BASE.db DONOR.db | test")
        sys.exit(1)
