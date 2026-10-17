"""¿Le interesa a este cliente y por qué? Gemini juzga cada noticia nueva por
cliente, con su bluebook (notas.md) y las alertas que ya se le mandaron.

Corre en cerebro.yml despues de embeber: solo mira noticias de las ultimas
48 h que el cerebro ya acerca al perfil del cliente (afinidad Media o mas) y
que todavia no se juzgaron. Los veredictos van a la tabla `relevancia` de
cerebro.db, que la app ya descarga. No manda nada a nadie.

    python -m alerts.filtro run
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from alerts import historial
from core import llm
from core.db import ROOT

LOTE = 25
MAX_POR_CLIENTE = 50
VENTANA_HORAS = 48

SYSTEM = ("Sos analista de asuntos publicos en Vali Consultores (Peru y Ecuador). Decidis si "
          "una noticia merece una alerta para un cliente puntual, segun su perfil real. Se "
          "estricto: interesa solo si toca sus temas, entidades, actores o una regulacion "
          "que lo afecte. Coyuntura general o algo que solo comparte palabras con su sector, no.")

SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "indice": {"type": "integer"}, "interesa": {"type": "boolean"},
    "por_que": {"type": "string"}}, "required": ["indice", "interesa", "por_que"]}}


def asegurar_tabla(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS relevancia (
        clave TEXT, cliente TEXT, interesa INTEGER, por_que TEXT, evaluado_at TEXT,
        PRIMARY KEY (clave, cliente))""")


def prompt(slug: str, notas: str, alertas: list[str], items: list[dict]) -> str:
    lista = "\n\n".join(
        f"[{i}] ({it['pais']}, {it['fuente']}, {it['fecha']})\nTitulo: {it['titulo']}\n"
        f"Resumen: {it['resumen'] or '(sin resumen)'}" for i, it in enumerate(items, 1))
    previas = "\n".join(f"- {a}" for a in alertas[-15:]) or "(ninguna todavia)"
    return f"""Perfil del cliente "{slug}" (bluebook):
{notas}

Alertas que ya se le mandaron (si una noticia sigue uno de estos temas, cuenta a favor):
{previas}

Para CADA noticia de abajo responde {{"indice", "interesa", "por_que"}}. "por_que" es una frase
corta y concreta (que le toca al cliente y por que), sin repetir el titulo.

{lista}"""


def juzgar(slug: str, items: list[dict], generar=llm.generar) -> dict[int, tuple[bool, str]]:
    """{indice (1..n): (interesa, por_que)}. Indices que Gemini no devuelve no aparecen."""
    notas = (ROOT / "clientes" / slug / "notas.md").read_text(encoding="utf-8")
    alertas = [e["encabezado"] + " " + e["cuerpo"].split("\n", 1)[0] for e in historial.entradas(slug)]
    texto = generar(prompt(slug, notas, alertas, items), system=SYSTEM, modelo=llm.LITE, schema=SCHEMA)
    out = {}
    for v in json.loads(texto or "[]"):
        if isinstance(v, dict) and isinstance(v.get("indice"), int) and 1 <= v["indice"] <= len(items):
            out[v["indice"]] = (bool(v.get("interesa")), str(v.get("por_que") or "").strip())
    return out


def candidatos(cerebro: sqlite3.Connection, noticias: sqlite3.Connection, slug: str) -> list[dict]:
    from cerebro.embeddings import AFINIDAD_MEDIA, afinidad
    desde = (datetime.now(timezone.utc) - timedelta(hours=VENTANA_HORAS)).strftime("%Y-%m-%dT%H:%M:%S")
    filas = {r[0]: r for r in noticias.execute(
        """SELECT n.id, n.titulo, n.resumen, COALESCE(n.fecha_pub, n.first_seen_at), f.nombre, f.pais
           FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
           WHERE f.activa = 1 AND n.first_seen_at >= ?""", (desde,))}
    ya = {r[0] for r in cerebro.execute("SELECT clave FROM relevancia WHERE cliente = ?", (slug,))}
    af = afinidad([f"noticia_{i}" for i in filas if f"noticia_{i}" not in ya], slug, cerebro)
    elegidas = sorted((c for c, v in af.items() if v >= AFINIDAD_MEDIA), key=af.get, reverse=True)
    out = []
    for clave in elegidas[:MAX_POR_CLIENTE]:
        _, titulo, resumen, fecha, fuente, pais = filas[int(clave.split("_", 1)[1])]
        out.append({"clave": clave, "titulo": titulo, "resumen": (resumen or "")[:500],
                    "fecha": (fecha or "")[:10], "fuente": fuente, "pais": pais})
    return out


def run() -> dict:
    from cerebro.embeddings import _db, conectar
    pe = _db("proyectos.db")
    if not pe:
        raise SystemExit("[filtro] falta proyectos.db")
    cerebro = conectar()
    asegurar_tabla(cerebro)
    noticias = sqlite3.connect(f"file:{pe}?mode=ro", uri=True)
    resumen = {}
    for slug in historial.clientes():
        items = candidatos(cerebro, noticias, slug)
        si = 0
        for i in range(0, len(items), LOTE):
            lote = items[i:i + LOTE]
            try:
                veredictos = juzgar(slug, lote)
            except Exception as e:  # cupo de Gemini o JSON roto: la proxima corrida reintenta
                print(f"[filtro] {slug}: {e}")
                break
            ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
            cerebro.executemany("INSERT OR REPLACE INTO relevancia VALUES (?,?,?,?,?)",
                                [(lote[k - 1]["clave"], slug, int(s), p, ahora)
                                 for k, (s, p) in veredictos.items()])
            cerebro.commit()
            si += sum(s for s, _ in veredictos.values())
        resumen[slug] = {"candidatas": len(items), "interesan": si}
        print(f"[filtro] {slug}: {len(items)} candidatas, {si} le interesan")
    return resumen


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.parse_args()
    run()
