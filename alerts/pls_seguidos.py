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


def seguir_matrices() -> int:
    """Sigue los PLs de las matrices de los clientes (clientes/<slug>/cliente.json)
    que esten en la base. No toca los que ya se siguen. Devuelve cuantos agrego."""
    from clientes import config
    nuevos: dict[str, dict] = {}
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for pais, (db, _) in _DB.items():
        col = "proyecto_ley" if pais == "PE" else "n_tramite"
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for slug in config.slugs():
            for f in config.matriz(slug, pais):
                pl = str(f["pl_numero"]).replace(" ", "")
                fila = conn.execute(f"SELECT {col}, titulo, estado, url_portal FROM proyectos WHERE {col} = ?", (pl,)).fetchone()
                if not fila:
                    continue
                k = clave(pais, fila[0])
                previo = nuevos.get(k)
                por = f"matriz {slug}" if not previo else previo["por"] + ("" if slug in previo["por"] else f", {slug}")
                nuevos[k] = {"pais": pais, "pl": fila[0], "titulo": fila[1] or "", "estado": fila[2],
                             "url": fila[3], "por": por, "desde": ahora}
    agregados = [k for k in nuevos if k not in store.leer(PATH, {})[0]]
    if agregados:
        store.actualizar(PATH, lambda d: {**{k: v for k, v in nuevos.items() if k not in d}, **d},
                         f"seguir {len(agregados)} PLs de las matrices de clientes", {})
    print(f"[pls_seguidos] matrices: {len(agregados)} agregados de {len(nuevos)}")
    return len(agregados)


# Ecuador: el portal de proyectos se actualiza dias despues; los boletines de la
# Asamblea y la prensa cuentan antes el avance. Gemini dice a que PL seguido se
# refiere cada nota nueva de tramite.
VISTAS = "data/pls_seguidos_noticias.json"
CRUCE = """Eres analista legislativo en Ecuador. Abajo van proyectos de ley que seguimos
y noticias recientes. Busca las noticias que nombran alguno de esos proyectos (por su
titulo o uno casi igual) y cuentan un hecho de su tramite: se presento, el CAL lo
califico, se unifico con otro, la comision avoco, recibio comparecencias, aprobo
informe, se debatio en el Pleno, se aprobo, veto o archivo. Si una noticia nombra
varios proyectos de la lista, devuelve una fila por cada uno. Cada fila lleva el numero
de la noticia, el codigo del proyecto tal como aparece en la lista y en una oracion que
paso. Si la noticia habla de otro proyecto o de un tema general, no va.

PROYECTOS:
{pls}

NOTICIAS:
{noticias}"""
ESQUEMA = {"type": "array", "items": {"type": "object", "properties": {
    "noticia": {"type": "integer"}, "pl": {"type": "string"}, "paso": {"type": "string"}},
    "required": ["noticia", "pl", "paso"]}}


def cruzar(pls: dict[str, dict], noticias: list[dict], generar=None) -> list[dict]:
    """[{pl, paso, noticia}] de las noticias que Gemini liga a un PL seguido."""
    import json
    if not pls or not noticias:
        return []
    if generar is None:
        from core.llm import LITE, generar as g
        generar = lambda p: g(p, modelo=LITE, json=True, schema=ESQUEMA)
    txt_pls = "\n".join(f"{s['pl']}: {s['titulo'][:220]}" for s in pls.values())
    txt_not = "\n".join(f"[{i}] {n['titulo']}. {(n.get('resumen') or '')[:400]}" for i, n in enumerate(noticias, 1))
    por_pl = {s["pl"]: s for s in pls.values()}
    out = []
    for r in json.loads(generar(CRUCE.format(pls=txt_pls, noticias=txt_not)) or "[]"):
        if r.get("pl") in por_pl and 1 <= r.get("noticia", 0) <= len(noticias):
            out.append({"pl": por_pl[r["pl"]], "paso": r["paso"], "noticia": noticias[r["noticia"] - 1]})
    return out


def revisar_noticias_ec(db: str = "proyectos.db", dias: int = 3) -> int:
    from congreso_live.notify import acortar_url, enviar_whatsapp
    from noticias.avances_ec import noticias_tramite_recientes
    seguidos = {k: v for k, v in store.leer(PATH, {})[0].items() if v["pais"] == "EC"}
    vistas = set(store.leer(VISTAS, [])[0])
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    nuevas = [n for n in noticias_tramite_recientes(conn, dias=dias) if n["url"] not in vistas]
    if not nuevas or not seguidos:
        print(f"[pls_seguidos] noticias EC: {len(nuevas)} nuevas, nada que cruzar")
        return 0
    hay = cruzar(seguidos, nuevas)  # si Gemini falla, levanta y no se marcan como vistas
    for c in hay:
        p, n = c["pl"], c["noticia"]
        enviar_whatsapp(f"📌 Proyecto que sigues (Ecuador): avance según noticia, antes que el portal\n"
                        f"{p['pl']}: {p['titulo'][:120]}\n{c['paso']}\n{acortar_url(n['url'])}")
    urls = [n["url"] for n in nuevas]
    store.actualizar(VISTAS, lambda d: (d + [u for u in urls if u not in d])[-500:],
                     f"PLs seguidos: {len(urls)} noticias EC revisadas", [])
    print(f"[pls_seguidos] noticias EC: {len(nuevas)} revisadas, {len(hay)} avisos")
    return len(hay)


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
    falso = lambda p: '[{"noticia": 1, "pl": "9", "paso": "La comision aprobo el informe"}, {"noticia": 5, "pl": "9", "paso": "x"}, {"noticia": 1, "pl": "77", "paso": "x"}]'
    r = cruzar({"EC:9": seg["EC:9"]}, [{"titulo": "Comision aprueba informe", "url": "u"}], falso)
    assert len(r) == 1 and r[0]["pl"]["pl"] == "9" and r[0]["noticia"]["url"] == "u", r
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["chequeo"]:
        _chequeo()
    elif sys.argv[1:] == ["matrices"]:
        seguir_matrices()
    elif sys.argv[1:] == ["noticias_ec"]:
        revisar_noticias_ec()
    elif sys.argv[1:2] and sys.argv[1] in _DB:
        revisar(sys.argv[1])
    else:
        raise SystemExit("Uso: python -m alerts.pls_seguidos PE|EC|matrices|chequeo")
