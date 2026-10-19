"""Aviso por Telegram cuando una fuente deja de traer noticias.

Caida = trajo algo en los ultimos 30 dias pero nada en los ultimos
DIAS_SIN_NADA (las que nunca trajeron nada no cuentan: son manuales o ya
se sabe que estan bloqueadas). Se avisa una vez por caida; cuando vuelve
a traer, sale de la lista y una caida nueva se avisa de nuevo. Caso real:
el portal de la Asamblea estuvo 3 semanas sin nada y nadie se entero.

Uso: python -m noticias.fuentes_caidas [--db proyectos.db] [--no-enviar]"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone

DIAS_SIN_NADA = 7
CLAVE = "fuentes_caidas"
CLAVE_ULTIMA = "fuentes_ultima_noticia"  # {pais|nombre: ISO}: la purga borra a los 7 dias


def ultimas_actuales(conn: sqlite3.Connection) -> dict[str, str]:
    """{pais|nombre: ultima first_seen_at} de las fuentes activas con noticias."""
    return {f"{p}|{n}": u for p, n, u in conn.execute("""
        SELECT f.pais, f.nombre, MAX(n.first_seen_at)
        FROM noticias_fuentes f JOIN noticias n ON n.fuente_id = f.id
        WHERE f.activa = 1 GROUP BY f.id""")}


def caidas(ultimas: dict[str, str], activas: set[str], ahora: datetime | None = None) -> list[tuple[str, str, str]]:
    """[(pais, nombre, ultima ISO)]: activas que trajeron algo en los ultimos
    60 dias pero nada en los ultimos DIAS_SIN_NADA."""
    ahora = ahora or datetime.now(timezone.utc)
    corte = (ahora - timedelta(days=DIAS_SIN_NADA)).strftime("%Y-%m-%dT%H:%M:%S")
    desde = (ahora - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")
    return sorted((*k.split("|", 1), u) for k, u in ultimas.items()
                  if k in activas and desde <= u < corte)


def _leer(conn, clave, vacio):
    fila = conn.execute("SELECT v FROM app_state WHERE k = ?", (clave,)).fetchone()
    return json.loads(fila[0]) if fila else vacio


def run(db: str = "proyectos.db", enviar: bool = True) -> list[tuple[str, str, str]]:
    """Avisa las caidas nuevas y devuelve esas. Guarda el estado en app_state."""
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE IF NOT EXISTS app_state (k TEXT PRIMARY KEY, v TEXT)")
    ultimas = _leer(conn, CLAVE_ULTIMA, {})
    for k, u in ultimas_actuales(conn).items():
        ultimas[k] = max(u, ultimas.get(k, u))
    activas = {f"{p}|{n}" for p, n in conn.execute(
        "SELECT pais, nombre FROM noticias_fuentes WHERE activa = 1")}
    avisadas = set(_leer(conn, CLAVE, []))
    ahora = caidas(ultimas, activas)
    nuevas = [c for c in ahora if f"{c[0]}|{c[1]}" not in avisadas]
    if nuevas and enviar:
        from congreso_live.notify import enviar_whatsapp
        lineas = [f"• {p} · {n} (última {u[:10]})" for p, n, u in nuevas]
        enviar_whatsapp(f"⚠️ Fuentes sin noticias hace {DIAS_SIN_NADA}+ días\n\n" + "\n".join(lineas))
    for clave, valor in ((CLAVE_ULTIMA, ultimas), (CLAVE, sorted(f"{p}|{n}" for p, n, _u in ahora))):
        conn.execute("INSERT OR REPLACE INTO app_state VALUES (?, ?)", (clave, json.dumps(valor, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return nuevas


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="proyectos.db")
    ap.add_argument("--no-enviar", action="store_true")
    a = ap.parse_args()
    for p, n, u in run(a.db, not a.no_enviar):
        print(f"[fuentes-caidas] nueva: {p} {n} (ultima {u})")
