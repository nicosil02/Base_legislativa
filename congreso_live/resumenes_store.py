"""Resumenes/ideas clave de transcripciones de sesiones.

`data/transcripciones_resumenes.json` es la fuente de verdad, commiteada al
repo. Solo la escribe la rutina de resumenes (con su propio checkout + push)
y la app solo la lee, asi que alcanza con un archivo local (sin Contents API).
"""
from __future__ import annotations

import json
from pathlib import Path

from core.db import now_iso

RESUMENES_PATH = "data/transcripciones_resumenes.json"


def _local_path() -> Path:
    return Path(__file__).resolve().parent.parent / RESUMENES_PATH


def list_resumenes(path: str | Path | None = None) -> dict[str, dict]:
    """video_id -> {resumen, ideas_clave, generated_at, ...}. {} si no hay."""
    p = Path(path) if path else _local_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for r in data:
        # el agente que resume a veces guarda el resumen como lista de parrafos
        if isinstance(r.get("resumen"), list):
            r["resumen"] = "\n\n".join(map(str, r["resumen"]))
        r["resumen"] = r.get("resumen") or ""
        r["ideas_clave"] = [str(i) for i in r.get("ideas_clave") or []]
        out[r["video_id"]] = r
    return out


def guardar_resumen(*, video_id: str, resumen: str, ideas_clave: list[str],
                    duracion_seg: int | None = None,
                    agenda_cumplida: str | None = None) -> None:
    """Upsert por video_id.

    `duracion_seg`: duracion de la transcripcion al generar este resumen; si
    despues crece (la sesion seguia en vivo), la rutina la vuelve a resumir.
    `agenda_cumplida`: texto libre, cuanto de lo agendado se trato."""
    p = _local_path()
    data = []
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = []
    entrada = {
        "video_id": video_id, "resumen": resumen,
        "ideas_clave": ideas_clave, "generated_at": now_iso(),
        "duracion_seg": duracion_seg, "agenda_cumplida": agenda_cumplida,
    }
    existente = next((r for r in data if r.get("video_id") == video_id), None)
    if existente:
        existente.update(entrada)
    else:
        data.append(entrada)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
