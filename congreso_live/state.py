"""Estado de sesiones EN VIVO ya vistas + dedupe de avisos.

Lo usan cmd_check (corre una vez al arrancar el job) y watch_and_transcribe
(descubre sesiones nuevas a mitad del job): ambos comparten este dedupe para
no avisar dos veces la misma sesion.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from core.text import norm

log = logging.getLogger(__name__)

STATE_PATH = Path("data/congreso_live_state.json")
MAX_LOG = 300


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"alertados": [], "sesiones": []}


def save_state(state: dict) -> None:
    state["sesiones"] = state.get("sesiones", [])[-MAX_LOG:]
    state["alertados"] = state.get("alertados", [])[-MAX_LOG:]
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def comision_seguida(tipo: str, seguidas_norm: set[str]) -> bool:
    """True si `tipo` ('Comision: Energia Y Minas') matchea por substring
    alguna comision marcada en Seguimiento. Los Plenos y las mesas de trabajo
    (ya filtradas por tema de cliente en detector) siempre pasan, y sin nada
    marcado pasa todo (para no dejar a nadie sin avisos)."""
    if tipo.startswith("Pleno:") or "Mesa de trabajo" in tipo or not seguidas_norm:
        return True
    kw = norm(tipo.split(":", 1)[-1].strip())
    return any(kw in nombre or nombre in kw for nombre in seguidas_norm)


def seguidas_activas() -> set[str]:
    """Comisiones marcadas de interes, normalizadas; set() (= avisar de
    todo) si no se pueden leer."""
    try:
        from alerts.seguimiento_store import list_seguidas
        return {norm(n) for n in list_seguidas()}
    except Exception as e:
        log.warning("no se pudo leer comisiones seguidas, aviso de todo: %s", e)
        return set()


_LOCK = threading.Lock()  # varias sesiones (hilos) leen y guardan el mismo JSON
MAX_AVISADO = 30


def avisado_de(video_id: str) -> list[str]:
    """Puntos del resumen en vivo ya mandados de esta sesion (tramos anteriores incluidos)."""
    with _LOCK:
        return list(load_state().get("avisado", {}).get(video_id, []))


def guardar_avisado(video_id: str, puntos: list[str]) -> None:
    with _LOCK:
        state = load_state()
        av = state.setdefault("avisado", {})
        av.pop(video_id, None)
        av[video_id] = puntos
        state["avisado"] = dict(list(av.items())[-MAX_AVISADO:])
        save_state(state)
