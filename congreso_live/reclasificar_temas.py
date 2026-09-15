"""Re-clasifica sesiones_transcripciones.temas usando el RESUMEN (texto
limpio y sintetizado) en vez de la transcripcion cruda.

Bug real encontrado en vivo 2026-09-15 (feedback de Nicolas: "estas
clasificando mal por temas las sesiones de comisiones"): noticias.temas.
clasificar() esta calibrado para noticias (titulo + resumen corto, donde
mencionar "diputado" o un acronimo SI es una senal real), pero
congreso_live lo aplicaba sobre la TRANSCRIPCION CRUDA de la sesion, que
tiene dos problemas estructurales que un articulo de noticias no tiene:

  1. Cortesias protocolares ("senor diputado", "senora presidenta") en
     CADA sesion, sin excepcion - dispara "Coyuntura politica" siempre,
     sin ser una senal real de contenido.
  2. Apellidos/nombres de parlamentarios que coinciden con siglas o
     palabras cortas de otras categorias - verificado en vivo con la
     sesion real de Salud (uawItrs3E9U): la diputada de apellido
     "Lavado" disparaba "KYC / AML / Financiero" (lavado de activos), y
     la diputada "Ana Luisa Yufra" disparaba "Crop" (ANA = Autoridad
     Nacional del Agua). Probado: ni recortar el arranque (rollcall) ni
     usar el texto completo lo arregla - los apellidos y cortesias
     aparecen a lo largo de TODA la transcripcion, no solo al principio.

Contra el RESUMEN real de esa misma sesion (data/transcripciones_
resumenes.json, generado por la rutina horaria de resumenes), clasificar
da ['Salud', ...] sin ningun falso positivo de nombre/sigla - el
resumen es prosa sintetizada, no transcripcion verbatim con roles de
protocolo y listas de asistencia.

La rutina de resumenes NO puede escribir proyectos.db (es de solo
lectura para ella, a proposito). Este modulo corre aparte (wireado a
refrescar-pe.yml, despues de que la rutina horaria ya dejo su commit) y
SI actualiza sesiones_transcripciones.temas para las sesiones que ya
tienen resumen.

Uso:
    python -m congreso_live.reclasificar_temas run
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from noticias.temas import clasificar

log = logging.getLogger(__name__)

RESUMENES_PATH = "data/transcripciones_resumenes.json"


def _cargar_resumenes(path: str | Path) -> dict[str, dict]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {r["video_id"]: r for r in data}
    except Exception as e:
        log.warning("no se pudo leer %s: %s", path, e)
        return {}


def run(db_path: str | Path, resumenes_path: str | Path = RESUMENES_PATH) -> dict:
    stats = {"con_resumen": 0, "actualizadas": 0}
    resumenes = _cargar_resumenes(resumenes_path)
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


def _demo():
    """Self-check sin red: sesion real de Salud (falsos positivos ya
    documentados) reclasificada contra su resumen real debe dar Salud
    sin Crop ni KYC/AML (los que disparaban nombres/siglas de personas)."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        resumenes_path = Path(td) / "resumenes.json"

        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE sesiones_transcripciones (
            video_id TEXT PRIMARY KEY, titulo TEXT, temas TEXT)""")
        conn.execute(
            "INSERT INTO sesiones_transcripciones VALUES (?,?,?)",
            ("uawItrs3E9U", "Sesión de la Comisión de Salud de la Cámara de Diputados",
             "Coyuntura política,KYC / AML / Financiero"),  # temas viejos, con los falsos positivos
        )
        conn.commit()
        conn.close()

        resumenes_path.write_text(json.dumps([{
            "video_id": "uawItrs3E9U",
            "resumen": "Sesion de la Comision de Salud sobre crisis en hospitales de EsSalud.",
            "ideas_clave": [
                "Redes de salud de Loreto denuncian que el SIS les nego "
                "presupuesto para medicamentos",
                "Hospital Carlos Seguin Escobedo: el acelerador lineal "
                "esta inoperativo, se contrata clinica privada",
            ],
        }]), encoding="utf-8")

        stats = run(db_path, resumenes_path)
        assert stats == {"con_resumen": 1, "actualizadas": 1}, stats

        conn = sqlite3.connect(db_path)
        temas_nuevos = conn.execute(
            "SELECT temas FROM sesiones_transcripciones WHERE video_id='uawItrs3E9U'"
        ).fetchone()[0]
        conn.close()
        assert "Salud" in temas_nuevos, temas_nuevos
        assert "Crop" not in temas_nuevos, temas_nuevos
    print("OK reclasificar_temas: resumen limpio da Salud, sin los falsos "
          "positivos de nombres/siglas del texto crudo")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["run", "test"])
    p.add_argument("--db", default="proyectos.db")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "test":
        _demo()
    else:
        stats = run(args.db)
        print(f"Reclasificacion de temas: {stats}")
