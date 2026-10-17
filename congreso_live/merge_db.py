"""Merge de sesiones_transcripciones entre dos snapshots de proyectos.db.

Varios workflows publican el mismo proyectos.db escribiendo tablas
distintas; quedarse con un archivo entero pierde las filas del otro.

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
    # Tablas que escriben workflows que publican en modo base_remota
    # (noticias/videos.py, noticias/tv_monitor.py) - sin esto se perderian
    # en el merge. Solo se agregan filas nuevas, nunca se pisan.
    from noticias.tv_monitor import SCHEMA as SCHEMA_TV
    from noticias.videos import SCHEMA as SCHEMA_VIDEOS
    for tabla, schema in (("videos_autoridades", SCHEMA_VIDEOS), ("tv_vistos", SCHEMA_TV[0]),
                          ("tv_menciones", SCHEMA_TV[1]), ("tv_avisos", SCHEMA_TV[2])):
        if base.execute("SELECT 1 FROM donor.sqlite_master WHERE name=?", (tabla,)).fetchone():
            base.execute(schema)
            base.execute(f"INSERT OR IGNORE INTO {tabla} SELECT * FROM donor.{tabla}")
    base.commit()
    despues = base.execute("SELECT COUNT(*) FROM sesiones_transcripciones").fetchone()[0]
    nuevas_o_actualizadas = base.total_changes
    base.close()
    return max(despues - antes, 0) or nuevas_o_actualizadas


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python -m congreso_live.merge_db BASE.db DONOR.db")
        sys.exit(1)
    n = merge_sesiones(sys.argv[1], sys.argv[2])
    print(f"merge_db: {n} fila(s) agregada(s)/actualizada(s) desde {sys.argv[2]}")
