"""Almacenamiento de resumenes/ideas clave de transcripciones de sesiones.

Mismo patron que alerts/borradores_store.py pero mas simple: NO usa la
GitHub Contents API (esa la necesita borradores_store porque Streamlit
Cloud escribe en vivo desde la app). Este archivo solo lo escribe la
rutina programada de resumenes (tiene su propio checkout + git push), y
lo lee la app - por eso alcanza con lectura/escritura de archivo local.

`data/transcripciones_resumenes.json` es la fuente de verdad, commiteada
al repo publico (mismo criterio ya aceptado por Nicolas para
alertas_borradores.json - no hay nada sensible en un resumen de una
sesion publica del Congreso).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

RESUMENES_PATH = "data/transcripciones_resumenes.json"


def _local_path() -> Path:
    return Path(__file__).resolve().parent.parent / RESUMENES_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_resumenes() -> dict[str, dict]:
    """video_id -> {resumen, ideas_clave, generated_at}."""
    p = _local_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {r["video_id"]: r for r in data}
    except Exception:
        return {}


def guardar_resumen(*, video_id: str, resumen: str, ideas_clave: list[str],
                    duracion_seg: int | None = None,
                    agenda_cumplida: str | None = None) -> None:
    """Crea o actualiza (upsert por video_id).

    `duracion_seg` es la duracion de la transcripcion en el momento de
    generar ESTE resumen - permite que la rutina que resume detecte que
    una sesion sigue en vivo (la transcripcion crecio desde el ultimo
    resumen guardado) y la vuelva a resumir en la proxima corrida, en
    vez de tratarla como "ya resumida, no tocar" para siempre.

    `agenda_cumplida` es texto libre opcional: que tanto de lo agendado
    para la sesion efectivamente se toco, segun el cruce contra
    sesion_agenda_punto/pleno_tema."""
    p = _local_path()
    data = []
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = []
    entrada = {
        "video_id": video_id, "resumen": resumen,
        "ideas_clave": ideas_clave, "generated_at": _now_iso(),
        "duracion_seg": duracion_seg, "agenda_cumplida": agenda_cumplida,
    }
    existente = next((r for r in data if r.get("video_id") == video_id), None)
    if existente:
        existente.update(entrada)
    else:
        data.append(entrada)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    import tempfile
    global _local_path
    old = _local_path
    tmp = Path(tempfile.mkdtemp()) / "data" / "transcripciones_resumenes.json"
    _local_path = lambda: tmp  # noqa: E731
    try:
        assert list_resumenes() == {}
        guardar_resumen(video_id="abc123", resumen="Se debatio X",
                        ideas_clave=["Punto 1", "Punto 2"])
        r = list_resumenes()
        assert r["abc123"]["resumen"] == "Se debatio X"
        assert r["abc123"]["ideas_clave"] == ["Punto 1", "Punto 2"]
        guardar_resumen(video_id="abc123", resumen="Version actualizada",
                        ideas_clave=["Punto A"])
        r = list_resumenes()
        assert len(r) == 1
        assert r["abc123"]["resumen"] == "Version actualizada"
        print("OK resumenes_store: crea y actualiza (upsert) correctamente")
    finally:
        _local_path = old


if __name__ == "__main__":
    _demo()
