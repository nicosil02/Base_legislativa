"""Estado compartido de sesiones EN VIVO detectadas + dedupe de alertas
WhatsApp.

Usado por `cli.py::cmd_check` (chequeo rapido, corre UNA vez al arrancar
el job de vigilar-congreso.yml) y por `live_transcribe.py::watch_and_transcribe`
(el job largo de transcripcion, que tambien puede descubrir una sesion
NUEVA a mitad de camino, cuando cmd_check ya paso).

Bug real 2026-09-17: el Pleno de Diputados arranco mientras el job ya
venia transcribiendo OTRA sesion (hasta 170 min) - como cmd_check solo
corre al arranque del job, y el siguiente disparo (cron-job.org, cada 10
min) queda encolado y cancelado mientras el job actual sigue corriendo
(mismo concurrency group), el aviso de WhatsApp del Pleno de Diputados
tardo ~1h30 en salir. Fix: watch_and_transcribe tambien avisa cuando
descubre una sesion nueva en su propio poll interno, reusando este mismo
dedupe (data/congreso_live_state.json) para no avisar dos veces la misma
sesion si cmd_check ya la habia alertado.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

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
    """True si `tipo` (ej. 'Comision: Energia Y Minas', armado por
    detector.clasificar_titulo() con una palabra clave corta) matchea
    alguna comision que Nicolas marco como de interes en la pestana
    Seguimiento (nombres completos) - mismo criterio de substring que ya
    usa clasificar_titulo() para reconocer la comision en el titulo real.

    Los Plenos (tipo empieza con "Pleno:") siempre pasan - son pocos y
    relevantes en general, no per-comision. Sin nada marcado todavia,
    tambien pasa todo (comportamiento actual: avisa de cualquier sesion)
    para no dejar a Nicolas sin alertas antes de configurar nada."""
    from congreso_live.detector import _norm
    if tipo.startswith("Pleno:") or not seguidas_norm:
        return True
    kw = _norm(tipo.split(":", 1)[-1].strip())
    return any(kw in nombre or nombre in kw for nombre in seguidas_norm)


def seguidas_activas() -> set[str]:
    """Comisiones que Nicolas marco de interes, normalizadas - set() (=
    avisar de todo) si no se puede leer por lo que sea."""
    from congreso_live.detector import _norm
    try:
        from alerts.seguimiento_store import list_seguidas
        return {_norm(n) for n in list_seguidas()}
    except Exception as e:
        log.warning("no se pudo leer comisiones seguidas, aviso de todo: %s", e)
        return set()
