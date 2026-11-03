"""Proyectos de ley que el analista sigue desde la ficha ("Seguir").

La lista y el ultimo estado visto van a data/pls_seguidos.json via core.store
(API de GitHub en la nube y en los workflows, archivo local sin token). Tras
cada sincronizacion, `revisar(pais)` compara el estado de la base con el
guardado y avisa por Telegram cada cambio.

    python -m alerts.pls_seguidos PE   # en refrescar-pe.yml, tras el sync
    python -m alerts.pls_seguidos EC   # en enriquecer-ec.yml
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone

from core import store

PATH = "data/pls_seguidos.json"
_DB = {"PE": ("proyectos.db", "SELECT estado FROM proyectos WHERE proyecto_ley = ?"),
       "EC": ("proyectos_ec.db", "SELECT estado FROM proyectos WHERE n_tramite = ?")}


def clave(pais: str, pl: str) -> str:
    return f"{pais}:{pl}"


def lista() -> dict[str, dict]:
    return store.cargar(PATH, {}, ttl=20)


def seguir(pais: str, pl: str, titulo: str, estado: str | None, url: str | None, por: str | None) -> None:
    item = {"pais": pais, "pl": pl, "titulo": titulo, "estado": estado, "url": url, "por": por,
            "desde": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    store.actualizar(PATH, lambda d: {**d, clave(pais, pl): item}, f"seguir PL {pais} {pl}", {})


def dejar(pais: str, pl: str) -> None:
    k = clave(pais, pl)
    store.actualizar(PATH, lambda d: {x: v for x, v in d.items() if x != k} if k in d else None,
                     f"dejar de seguir PL {pais} {pl}", {})


def cambios(pais: str, conn: sqlite3.Connection, seguidos: dict[str, dict]) -> list[dict]:
    """Seguidos de `pais` cuyo estado en la base ya no es el guardado."""
    sql = _DB[pais][1]
    out = []
    for k, s in seguidos.items():
        if s["pais"] != pais:
            continue
        fila = conn.execute(sql, (s["pl"],)).fetchone()
        if fila and fila[0] and fila[0] != s.get("estado"):
            out.append({**s, "clave": k, "antes": s.get("estado"), "ahora": fila[0]})
    return out


def mensaje(c: dict) -> str:
    pais = {"PE": "Perú", "EC": "Ecuador"}[c["pais"]]
    return (f"📌 Proyecto que sigues ({pais}) cambió de estado\n"
            f"{c['pl']}: {c['titulo'][:120]}\n"
            f"{c['antes'] or 'sin estado'} → {c['ahora']}" + (f"\n{c['url']}" if c.get("url") else ""))


def revisar(pais: str) -> int:
    from congreso_live.notify import enviar_whatsapp  # va por Telegram si esta configurado
    conn = sqlite3.connect(f"file:{_DB[pais][0]}?mode=ro", uri=True)
    hay = cambios(pais, conn, store.leer(PATH, {})[0])
    for c in hay:
        enviar_whatsapp(mensaje(c))
    if hay:
        nuevos = {c["clave"]: c["ahora"] for c in hay}
        store.actualizar(PATH, lambda d: {k: ({**v, "estado": nuevos[k]} if k in nuevos else v) for k, v in d.items()},
                         f"PLs seguidos: {len(hay)} cambio(s) {pais}", {})
    print(f"[pls_seguidos] {pais}: {len(hay)} cambio(s)")
    return len(hay)


def _chequeo() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE proyectos (proyecto_ley TEXT, estado TEXT)")
    conn.execute("INSERT INTO proyectos VALUES ('00709-2026-2031-CD', 'DICTAMEN')")
    seg = {"PE:00709-2026-2031-CD": {"pais": "PE", "pl": "00709-2026-2031-CD", "titulo": "x", "estado": "EN COMISIÓN"},
           "PE:1": {"pais": "PE", "pl": "1", "titulo": "y", "estado": "A"},
           "EC:9": {"pais": "EC", "pl": "9", "titulo": "z", "estado": "B"}}
    c = cambios("PE", conn, seg)
    assert [x["clave"] for x in c] == ["PE:00709-2026-2031-CD"] and c[0]["ahora"] == "DICTAMEN", c
    assert "EN COMISIÓN → DICTAMEN" in mensaje(c[0])
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["chequeo"]:
        _chequeo()
    elif sys.argv[1:2] and sys.argv[1] in _DB:
        revisar(sys.argv[1])
    else:
        raise SystemExit("Uso: python -m alerts.pls_seguidos PE|EC|chequeo")
