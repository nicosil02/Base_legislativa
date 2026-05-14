"""Export del estado actual de la DB a JSON."""
from __future__ import annotations

import json
from pathlib import Path

from scraper.db import Database


def export_json(db: Database, path: str | Path) -> int:
    cur = db.conn.execute(
        """SELECT * FROM proyectos ORDER BY per_par_id DESC, pley_num DESC"""
    )
    proyectos: list[dict] = []
    for row in cur.fetchall():
        d = dict(row)
        key = (d["per_par_id"], d["pley_num"])
        d["comisiones"] = [
            dict(r) for r in db.conn.execute(
                "SELECT comision_id, nombre FROM proyecto_comision WHERE per_par_id=? AND pley_num=?",
                key,
            )
        ]
        # `tema` y `tema_manual` ya vienen como columnas del SELECT * de proyectos
        d["seguimientos"] = [
            dict(r) for r in db.conn.execute(
                "SELECT seguimiento_pley_id, fecha, estado, comisiones, detalle, observacion, flag_inicial "
                "FROM seguimientos WHERE per_par_id=? AND pley_num=? ORDER BY fecha DESC",
                key,
            )
        ]
        proyectos.append(d)

    path = Path(path)
    path.write_text(json.dumps(proyectos, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(proyectos)
