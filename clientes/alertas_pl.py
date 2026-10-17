"""Aviso por WhatsApp cuando un PL de la matriz Bayer Crop Perú cambia de
estado en la base del Congreso.

El último estado visto se guarda en data/pl_seguimiento_estado.json. Un PL
que se ve por primera vez se guarda sin avisar: no es un cambio real.

Uso: python -m clientes.alertas_pl check
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from clientes.matrices import matriz_bayer_crop

ESTADO_PATH = Path("data/pl_seguimiento_estado.json")


def _cargar_estado_conocido() -> dict[str, str]:
    if not ESTADO_PATH.exists():
        return {}
    try:
        return json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guardar_estado_conocido(estado: dict[str, str]) -> None:
    ESTADO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ESTADO_PATH.write_text(
        json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def detectar_cambios(db_path: str | Path, cliente: str = "Bayer") -> list[dict]:
    """PLs de matriz_bayer_crop("PE") cuyo estado cambió desde la última
    corrida. Actualiza el archivo de estado: llamar una vez por corrida."""
    tracked = {f["pl_numero"]: f["titulo_matriz"] for f in matriz_bayer_crop("PE") if f["pl_numero"]}
    if not tracked:
        return []
    conocido = _cargar_estado_conocido()
    conn = sqlite3.connect(str(db_path))
    cambios = []
    for pl_numero, titulo in tracked.items():
        row = conn.execute(
            "SELECT estado, url_portal FROM proyectos WHERE proyecto_ley = ?", (pl_numero,)
        ).fetchone()
        if not row:
            continue  # todavía no está en la DB
        estado_actual, url = row
        ya_visto = pl_numero in conocido
        if ya_visto and conocido[pl_numero] != estado_actual:
            cambios.append({
                "pl_numero": pl_numero, "titulo": titulo, "cliente": cliente,
                "estado_anterior": conocido[pl_numero], "estado_actual": estado_actual,
                "url": url,
            })
        conocido[pl_numero] = estado_actual
    conn.close()
    _guardar_estado_conocido(conocido)
    return cambios


def _mensaje_whatsapp(c: dict) -> str:
    return (
        f"📋 PL de interés ({c['cliente']}) cambió de estado\n"
        f"{c['pl_numero']}: {c['titulo'][:100]}\n"
        f"{c['estado_anterior']} → {c['estado_actual']}\n"
        f"{c['url']}"
    )


def cmd_check() -> int:
    from congreso_live.notify import enviar_whatsapp
    from congreso_live.transcripciones import _find_db_path

    cambios = detectar_cambios(_find_db_path())
    for c in cambios:
        enviar_whatsapp(_mensaje_whatsapp(c))
    print(f"{len(cambios)} cambio(s) de estado detectado(s) y notificado(s).")
    for c in cambios:
        print(f"  {c['pl_numero']}: {c['estado_anterior']} -> {c['estado_actual']}")
    return 0



if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["check"]:
        raise SystemExit(cmd_check())
    print("Uso: python -m clientes.alertas_pl check")
    raise SystemExit(2)
