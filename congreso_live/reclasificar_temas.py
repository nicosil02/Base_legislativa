"""Re-clasifica sesiones_transcripciones.temas usando el RESUMEN en vez de
la transcripcion cruda.

noticias.temas.clasificar() esta calibrado para noticias; sobre una
transcripcion cruda da falsos positivos fijos: las cortesias ("senor
diputado") disparan Coyuntura politica y apellidos como "Lavado" o "Ana"
disparan KYC o Crop. El resumen es prosa sintetizada y no tiene ese ruido.
La rutina de resumenes no escribe proyectos.db, por eso esto corre aparte
(refrescar-pe.yml).

Uso:
    python -m congreso_live.reclasificar_temas run
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from congreso_live.resumenes_store import list_resumenes
from noticias.temas import clasificar

log = logging.getLogger(__name__)


def run(db_path: str | Path, resumenes_path: str | Path | None = None) -> dict:
    stats = {"con_resumen": 0, "actualizadas": 0}
    resumenes = list_resumenes(resumenes_path)
    if not resumenes:
        return stats

    conn = sqlite3.connect(str(db_path))
    filas = conn.execute(
        "SELECT video_id, titulo, temas FROM sesiones_transcripciones"
    ).fetchall()
    for video_id, titulo, temas_actual in filas:
        res = resumenes.get(video_id)
        if not res:
            continue
        stats["con_resumen"] += 1
        texto_limpio = res.get("resumen", "") + " " + " ".join(res.get("ideas_clave", []))
        nuevos_temas = ",".join(clasificar(titulo, texto_limpio))
        if nuevos_temas != (temas_actual or ""):
            conn.execute(
                "UPDATE sesiones_transcripciones SET temas=? WHERE video_id=?",
                (nuevos_temas, video_id),
            )
            stats["actualizadas"] += 1
    conn.commit()
    conn.close()
    log.info("reclasificar_temas: %s", stats)
    return stats


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run"])
    p.add_argument("--db", default="proyectos.db")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stats = run(args.db)
    print(f"Reclasificacion de temas: {stats}")
