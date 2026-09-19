"""Alerta de WhatsApp cuando un PL puntual de la matriz de un cliente
(ver clientes/matrices.py) cambia de `estado` en nuestra base scrapeada
del Congreso.

matriz_bayer_crop("PE") ya existia pero solo se usaba para taguear
"Bayer" en la UI (filtro visual, pages/1_Peru.py/3_Agenda_PE.py) - nunca
disparaba nada. Pedido real de Nicolas 2026-09-18: "vincular los
proyectos de interes y las alertas de whatsapp... automatico por
cliente en base a... la matriz que tenemos... al menos para Bayer".

Solo Peru por ahora: matriz_bayer_crop("EC") existe pero no hay ningun
scraper de la Asamblea Nacional de Ecuador en este repo contra que
cruzar el estado real - proyecto aparte, mas grande, pendiente.

Estado conocido persistido en data/pl_seguimiento_estado.json (mismo
patron que congreso_live_state.json) - {pl_numero: ultimo_estado_visto}
para poder detectar CAMBIOS, no solo leer el estado actual. La PRIMERA
vez que se ve un PL (nunca alertado antes) se guarda su estado sin
avisar - avisar ahi seria un falso "cambio" (bootstrap), no un cambio
real.

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
    """Compara el `estado` actual en `proyectos` de cada PL trackeado por
    matriz_bayer_crop("PE") contra el ultimo estado conocido (persistido).
    Devuelve solo los que CAMBIARON de verdad - un PL visto por primera
    vez se guarda sin reportarse como cambio. Deja el archivo de estado
    actualizado con lo que acaba de leer (llamalo una sola vez por
    corrida, no repetidas veces, o el segundo llamado no vera cambios)."""
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
            continue  # PL de la matriz que todavia no aparece en nuestra DB
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


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    """Sin red: mockea matriz_bayer_crop y la DB de proyectos para probar
    que (1) un PL visto por primera vez se guarda SIN avisar (evita el
    falso "cambio" de bootstrap), (2) un cambio real entre corridas SI
    se detecta, y (3) sin cambio real no avisa de nuevo."""
    import tempfile
    from unittest.mock import patch

    import clientes.alertas_pl as ap

    tracked = [{"pl_numero": "00098-2026-2031-CD", "titulo_matriz": "Ley de facultades",
                "tema_matriz": "x", "estado_matriz": "Activo"}]

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test.db"
        estado_path = Path(td) / "estado.json"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE proyectos (proyecto_ley TEXT PRIMARY KEY, estado TEXT, url_portal TEXT)")
        conn.execute("INSERT INTO proyectos VALUES ('00098-2026-2031-CD', 'EN COMISION', 'http://x')")
        conn.commit()
        conn.close()

        with patch.object(ap, "matriz_bayer_crop", lambda pais: tracked if pais == "PE" else []), \
             patch.object(ap, "ESTADO_PATH", estado_path):
            # 1ra corrida: PL nuevo, nunca visto - se guarda, NO avisa.
            cambios1 = ap.detectar_cambios(db_path)
            assert cambios1 == [], f"un PL nuevo no deberia reportarse como cambio: {cambios1}"

            # 2da corrida: mismo estado en la DB - sigue sin avisar.
            cambios2 = ap.detectar_cambios(db_path)
            assert cambios2 == [], f"sin cambio real no deberia avisar: {cambios2}"

            # El estado cambio de verdad en la DB (ej. nuevo dictamen).
            conn = sqlite3.connect(str(db_path))
            conn.execute("UPDATE proyectos SET estado='DICTAMEN APROBADO' WHERE proyecto_ley='00098-2026-2031-CD'")
            conn.commit()
            conn.close()

            cambios3 = ap.detectar_cambios(db_path)
            assert len(cambios3) == 1, cambios3
            assert cambios3[0]["estado_anterior"] == "EN COMISION", cambios3
            assert cambios3[0]["estado_actual"] == "DICTAMEN APROBADO", cambios3

            # 4ta corrida: ya alertado, sin cambio nuevo - no vuelve a avisar.
            cambios4 = ap.detectar_cambios(db_path)
            assert cambios4 == [], f"no deberia re-avisar el mismo cambio: {cambios4}"

    print("OK alertas_pl: bootstrap silencioso, detecta cambio real, no repite aviso")


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 2 and sys.argv[1] == "check":
        raise SystemExit(cmd_check())
    _demo()
