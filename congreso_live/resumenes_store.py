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


REMOTO_URL = ("https://raw.githubusercontent.com/nicosil02/Base_legislativa/main/"
              + RESUMENES_PATH)
_remoto: dict = {"t": 0.0, "data": []}


def _bajar_remoto() -> list:
    """El JSON de main, cada 10 min como mucho. La app baja las transcripciones
    frescas de la rama `datos`, pero el JSON local queda viejo si el checkout
    no esta al dia (PC con otra rama, o entre redespliegues): sin esto, las
    sesiones nuevas salian 'Resumen pendiente' aunque ya estuvieran resumidas."""
    import time
    import urllib.request
    if time.time() - _remoto["t"] > 600:
        _remoto["t"] = time.time()
        try:
            with urllib.request.urlopen(REMOTO_URL, timeout=20) as r:
                _remoto["data"] = json.loads(r.read().decode("utf-8"))
        except Exception as e:
            print(f"[resumenes] no pude bajar de main: {e}")
    return _remoto["data"]


def list_resumenes(path: str | Path | None = None) -> dict[str, dict]:
    """video_id -> {resumen, ideas_clave, generated_at, ...}. {} si no hay.

    Sin `path`, junta el archivo local con el de main y por sesion se queda
    con el mas reciente."""
    p = Path(path) if path else _local_path()
    data = []
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = []
    if path is None:
        por_id = {r.get("video_id"): r for r in data}
        for r in _bajar_remoto():
            loc = por_id.get(r.get("video_id"))
            if not loc or (r.get("generated_at") or "") > (loc.get("generated_at") or ""):
                por_id[r.get("video_id")] = r
        data = list(por_id.values())
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
