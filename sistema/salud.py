"""Vigia de salud: avisa por Telegram cuando algo de los servicios gratis se
rompe, para que nadie tenga que revisar Actions a mano.

Mira con la API de GitHub (sin `gh`: corre igual en local):
  - workflows con horario que no corrieron en su ventana (lee el cron del
    .yml y da MARGEN de atraso; cualquier corrida, por cron, push o
    dispatch, cuenta),
  - workflows que fallaron FALLAS_SEGUIDAS veces seguidas (en la ultima semana),
  - la rama `datos` sin publicar hace mas de HORAS_DATOS,
  - WARP que no conecto en la ultima corrida que lo uso (scripts/warp.sh
    deja la anotacion "WARP no conecto").

Un aviso por problema (estado en data/salud_estado.json via core.store) y
otro cuando se recupera; todo junto en un solo mensaje.

Uso: python -m sistema.salud [--no-enviar] [--forzar]"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import yaml

from core import store
from core.db import ROOT
from core.tiempo import LIMA

REPO = os.environ.get("GITHUB_REPOSITORY", "nicosil02/Base_legislativa")
ESTADO = "data/salud_estado.json"
MARGEN = timedelta(minutes=90)  # el cron nativo llega a atrasarse ~1 h en horas pico
FALLAS_SEGUIDAS = 2
HORAS_DATOS = 12  # refrescar-pe no corre de 22:00 a 08:00 Lima (10 h)
CADA = timedelta(minutes=50)  # una revision por hora como mucho


def api(ruta: str):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ValiIntelligence/1.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    for intento in range(3):
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{ruta}", headers=headers)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if intento == 2:
                raise
            time.sleep(5)


def _fecha(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _lima(d: datetime) -> str:
    return d.astimezone(LIMA).strftime("%d/%m %H:%M")


# --- cron -----------------------------------------------------------------

def _campo(expr: str, v: int) -> bool:
    """Un campo de cron: '*', '5', '1-5', '*/10', '13-23', listas con ','."""
    for parte in expr.split(","):
        rango, _, paso = parte.partition("/")
        a, _, b = rango.partition("-")
        lo, hi = (0, 99) if rango == "*" else (int(a), int(b) if b else (99 if paso else int(a)))
        if lo <= v <= hi and (v - lo) % int(paso or 1) == 0:
            return True
    return False


def coincide(cron: str, t: datetime) -> bool:
    # ponytail: dia-del-mes Y dia-de-semana con AND (cron real usa OR si ambos
    # estan restringidos); ningun workflow del repo restringe los dos.
    mi, h, dm, me, ds = cron.split()
    return (_campo(mi, t.minute) and _campo(h, t.hour) and _campo(dm, t.day)
            and _campo(me, t.month) and _campo(ds, (t.weekday() + 1) % 7))


def ultimo_disparo(crons: list[str], antes: datetime) -> datetime | None:
    """Ultimo minuto <= `antes` (UTC) en que tocaba correr; busca 8 dias atras."""
    t = antes.replace(second=0, microsecond=0)
    for _ in range(8 * 24 * 60):
        if any(coincide(c, t) for c in crons):
            return t
        t -= timedelta(minutes=1)
    return None


def leer_workflows() -> dict[str, dict]:
    """{archivo.yml: {nombre, crons, warp}} de los .yml del checkout."""
    out = {}
    for f in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        texto = f.read_text(encoding="utf-8")
        w = yaml.safe_load(texto)
        on = w.get(True) or w.get("on") or {}
        crons = [c["cron"] for c in (on.get("schedule") or [])] if isinstance(on, dict) else []
        out[f.name] = {"nombre": w.get("name", f.name), "crons": crons, "warp": "scripts/warp.sh" in texto}
    return out


# --- revisiones (cada una devuelve {clave: mensaje}) -------------------------

def sin_correr(nombre: str, crons: list[str], runs: list[dict], ahora: datetime) -> dict[str, str]:
    tocaba = ultimo_disparo(crons, ahora - MARGEN)
    if not tocaba or any(r["status"] != "completed" for r in runs):
        return {}  # corriendo o en cola (tv-monitor y vigilar-congreso duran horas): esta vivo
    ultima = _fecha(runs[0]["created_at"]) if runs else None
    if ultima and ultima >= tocaba:
        return {}
    desde = f"desde {_lima(ultima)}" if ultima else "nunca"
    return {f"sin_correr:{nombre}": f"{nombre}: no corre {desde} (tocaba {_lima(tocaba)})"}


def fallas(nombre: str, runs: list[dict], ahora: datetime) -> dict[str, str]:
    hechas = [r for r in runs if r["status"] == "completed" and r["conclusion"] not in ("cancelled", "skipped")]
    n = 0
    for r in hechas:
        if r["conclusion"] != "failure":
            break
        n += 1
    if n < FALLAS_SEGUIDAS or ahora - _fecha(hechas[0]["created_at"]) > timedelta(days=7):
        return {}
    return {f"falla:{nombre}": f"{nombre}: fallo {n} veces seguidas ({hechas[0]['html_url']})"}


def datos(ahora: datetime) -> dict[str, str]:
    fecha = _fecha(api("/branches/datos")["commit"]["commit"]["committer"]["date"])
    if ahora - fecha <= timedelta(hours=HORAS_DATOS):
        return {}
    return {"datos": f"rama datos sin publicar desde {_lima(fecha)}"}


def warp(nombre: str, runs: list[dict]) -> dict[str, str] | None:
    """None si ninguna de las ultimas corridas uso WARP (no se sabe)."""
    for r in [r for r in runs if r["status"] == "completed"][:3]:
        for job in api(f"/actions/runs/{r['id']}/jobs")["jobs"]:
            if any("WARP" in s["name"] and s["conclusion"] in ("success", "failure") for s in job["steps"]):
                notas = api(f"/check-runs/{job['id']}/annotations")
                if any("WARP no" in (n.get("message") or "") for n in notas):
                    return {f"warp:{nombre}": f"{nombre}: WARP no conecto, YouTube no anduvo ({r['html_url']})"}
                return {}
    return None


def revisar(ahora: datetime | None = None, previos: dict | None = None) -> dict[str, str]:
    """{clave: mensaje} de los problemas de ahora."""
    ahora = ahora or datetime.now(timezone.utc)
    previos = previos or {}
    activos = {w["path"].rsplit("/", 1)[-1] for w in api("/actions/workflows?per_page=100")["workflows"]
               if w["state"] == "active"}
    problemas = {}
    for archivo, w in leer_workflows().items():
        if archivo not in activos:
            continue
        runs = api(f"/actions/workflows/{archivo}/runs?per_page=10")["workflow_runs"]
        if w["crons"]:
            problemas |= sin_correr(w["nombre"], w["crons"], runs, ahora)
        problemas |= fallas(w["nombre"], runs, ahora)
        if w["warp"]:
            r = warp(w["nombre"], runs)
            clave = f"warp:{w['nombre']}"
            problemas |= r if r is not None else ({clave: previos[clave]} if clave in previos else {})
    problemas |= datos(ahora)
    return problemas


def mensaje(previos: dict[str, str], ahora: dict[str, str]) -> str | None:
    nuevos = [m for k, m in ahora.items() if k not in previos]
    resueltos = [m for k, m in previos.items() if k not in ahora]
    if not nuevos and not resueltos:
        return None
    partes = []
    if nuevos:
        partes.append("⚠️ Algo se rompió en el Radar\n\n" + "\n".join(f"• {m}" for m in nuevos))
    if resueltos:
        partes.append("✅ Se recuperó\n\n" + "\n".join(f"• {m}" for m in resueltos))
    return "\n\n".join(partes)


def reciente() -> bool:
    """Otra revision terminada hace menos de CADA (cron + workflow_run)."""
    propio = os.environ.get("GITHUB_RUN_ID")
    for r in api("/actions/workflows/salud.yml/runs?per_page=5")["workflow_runs"]:
        if str(r["id"]) != propio and r["conclusion"] == "success":
            return datetime.now(timezone.utc) - _fecha(r["created_at"]) < CADA
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sistema.salud")
    ap.add_argument("--no-enviar", action="store_true", help="solo mostrar, sin Telegram ni guardar estado")
    ap.add_argument("--forzar", action="store_true", help="revisar aunque haya otra revision reciente")
    a = ap.parse_args(argv)
    if not a.forzar and not a.no_enviar and reciente():
        print("[salud] ya se reviso hace menos de una hora")
        return 0
    previos, _ = store.leer(ESTADO, {})
    ahora = revisar(previos=previos)
    for m in ahora.values():
        print(f"[salud] problema: {m}")
    texto = mensaje(previos, ahora)
    print(f"[salud] mensaje:\n{texto}" if texto else "[salud] sin cambios")
    if a.no_enviar or ahora.keys() == previos.keys():  # el texto cambia (fechas); los problemas no
        return 0
    if texto:
        from congreso_live.notify import enviar_whatsapp
        if not enviar_whatsapp(texto):
            print("[salud] Telegram fallo; no guardo el estado para reintentar")
            return 1
    store.actualizar(ESTADO, lambda _: ahora, "salud: estado del vigia", {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
