"""¿Qué cosas de interés pasaron hoy? - la pregunta guia de Nicolas, sola.

Una vez al dia (desde las 18:00 Lima, en cerebro.yml) junta lo de las
ultimas 24 h que ya paso por los filtros del sistema y Gemini lo escribe como
lo contaria un analista: por cliente, lo que importa y por que, y al final
los hilos no obvios que vale la pena seguir (como la compra a India por
AIL EP, que salio de esta pregunta). Va por Telegram y queda en cerebro.db
(tabla resumen_dia).

Material:
  - noticias que alerts/filtro.py marco "le interesa" a un cliente (con el
    por que), juntando las del mismo hecho (noticias/mismo_hecho.py)
  - normas de interes (El Peruano, Registro Oficial)
  - cambios de estado de PLs PE/EC de las categorias o matrices de clientes
  - resumenes de sesiones transcritas, avisos de TV

    python -m alerts.que_paso_hoy run [--forzar] [--no-enviar]
"""
from __future__ import annotations

from functools import lru_cache

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from clientes import config
from core import llm
from core.db import db_path
from core.tiempo import LIMA

HORA_DESDE = 18          # hora Lima desde la que sale el resumen del dia
# Lo que importa es cuando PASO, no cuando el sistema lo vio: las busquedas
# de Google News traen notas de hace años y el backfill resume sesiones viejas.
DIAS_FRESCO = 2
MAX = {"noticias": 70, "normas": 25, "pls": 40, "sesiones": 12, "tv": 12}

SYSTEM = """Eres analista senior de asuntos publicos en Vali Consultores (Peru y Ecuador).
Respondes la pregunta de todos los dias del equipo: "¿que cosas de interes pasaron hoy?".

Con el material del dia (ya filtrado por relevancia) escribe:
1. Por cada cliente con algo real, de 1 a 4 puntos. Cada punto dice que paso, por que le
   importa a ese cliente y el link. Lo mas importante primero. Si un cliente no tiene nada
   relevante, no lo nombres.
2. "Hilos para seguir": 2 a 4 cosas no obvias que conviene investigar o vigilar (una compra
   publica, un nombramiento, una norma que viene, un PL que se mueve rapido, algo que se
   repite en varias fuentes). Di que buscarias y donde.

Reglas: solo lo que esta en el material, nada inventado. A un cliente solo le cuentas cosas
de sus paises. Espanol simple y directo, frases cortas, sin metaforas ni jerga. Formato de
Telegram: *un asterisco* para negrita (solo el nombre del cliente), links como [link](url), sin
titulos (#) ni **dobles asteriscos**. Si el dia fue flojo, dilo en una linea y no rellenes."""


def _lima_ahora() -> datetime:
    return datetime.now(LIMA)


def _desde_utc(horas: int = 24) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%S")


def _ro(nombre: str) -> sqlite3.Connection | None:
    p = db_path(nombre)
    if not p.exists():
        return None
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _grupos(ids: list[int], cerebro: sqlite3.Connection) -> list[list[int]]:
    """Junta las noticias que el juez dijo que cuentan el mismo hecho."""
    padre = {i: i for i in ids}

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i
    if ids:
        lista = ",".join(map(str, ids))
        try:
            for a, b in cerebro.execute(
                    f"SELECT a, b FROM mismo_hecho WHERE igual = 1 AND a IN ({lista}) AND b IN ({lista})"):
                padre[raiz(a)] = raiz(b)
        except sqlite3.OperationalError:
            pass
    grupos: dict[int, list[int]] = {}
    for i in ids:
        grupos.setdefault(raiz(i), []).append(i)
    return list(grupos.values())


def _fresca(r) -> bool:
    from noticias.digest import _es_reciente
    return _es_reciente({"fecha_pub": r["fecha_pub"]}, DIAS_FRESCO)


def _url(url: str) -> str:
    """Las de Google News pesan 500+ caracteres: se comen el prompt y el mensaje."""
    from congreso_live.notify import acortar_url
    return acortar_url(url) if "news.google." in url else url


def noticias(pe: sqlite3.Connection, cerebro: sqlite3.Connection, desde: str) -> list[str]:
    por_id: dict[int, list[tuple[str, str]]] = {}
    for clave, cliente, por_que in cerebro.execute(
            "SELECT clave, cliente, por_que FROM relevancia WHERE interesa = 1"):
        por_id.setdefault(int(clave.split("_", 1)[1]), []).append((cliente, por_que))
    if not por_id:
        return []
    lista = ",".join(map(str, por_id))
    filas = {r["id"]: r for r in pe.execute(
        f"""SELECT n.id, n.titulo, n.url, n.fecha_pub, f.nombre AS fuente, f.pais FROM noticias n
            JOIN noticias_fuentes f ON f.id = n.fuente_id
            WHERE n.id IN ({lista}) AND n.first_seen_at >= ? ORDER BY n.first_seen_at DESC""", (desde,)) if _fresca(r)}
    out = []
    for g in _grupos(list(filas), cerebro)[:MAX["noticias"]]:
        r = filas[g[0]]
        clientes = {c: p for i in g for c, p in por_id.get(i, [])}
        otras = sorted({filas[i]["fuente"] for i in g[1:]} - {r["fuente"]})
        out.append(f"[{r['pais']}] {r['titulo']} ({r['fuente']}"
                   + (f"; tambien en {', '.join(otras)}" if otras else "") + f") {_url(r['url'])}\n"
                   + "".join(f"   - {c}: {p}\n" for c, p in clientes.items()))
    return out


def normas(pe: sqlite3.Connection, desde: str) -> list[str]:
    from noticias.temas import es_normativa_de_interes
    out = []
    for r in pe.execute(
            """SELECT n.titulo, n.resumen, n.url, n.tags, n.fecha_pub, f.pais FROM noticias n
               JOIN noticias_fuentes f ON f.id = n.fuente_id
               WHERE n.first_seen_at >= ? AND (n.tags LIKE '%normativa%' OR n.tags LIKE '%normas%')""",
            (desde,)):
        if _fresca(r) and es_normativa_de_interes(r["tags"], r["resumen"]):
            out.append(f"[{r['pais']}] {r['titulo']}: {(r['resumen'] or '')[:250]} {_url(r['url'])}")
    return out[:MAX["normas"]]


@lru_cache(maxsize=None)
def _matriz_nums(slug: str, pais: str) -> frozenset[str]:
    # La matriz es un xlsx: leerla por cada PL tardaba minutos.
    return frozenset(f["pl_numero"] for f in config.matriz(slug, pais))


def _clientes_de_pl(tema: str | None, numero: str, pais: str) -> list[str]:
    return [s for s in config.slugs(pais)
            if (tema and tema in config.todos()[s].get("categorias_pl", []))
            or numero in _matriz_nums(s, pais)]


def pls(desde: datetime) -> list[str]:
    """PL de clientes (categoria o matriz) que cambiaron de estado o comision."""
    from core import legislativo
    out = []
    for pais in legislativo.PAISES:
        for r in legislativo.cambios(pais, desde):
            cl = _clientes_de_pl(r["categoria"], r["numero"], pais)
            if cl:
                out.append(f"[{pais}] PL {r['numero']} ({r['categoria']}; {', '.join(cl)}) {r['titulo'][:160]} "
                           f"-> {r['campo']}: {r['valor']} ({r['fecha']}) {r['url'] or ''}".rstrip())
    return out[:MAX["pls"]]


def sesiones(pe: sqlite3.Connection | None, desde: str) -> list[str]:
    from congreso_live.resumenes_store import list_resumenes
    fechas = dict(pe.execute("SELECT video_id, fecha FROM sesiones_transcripciones")) if pe else {}
    minimo = (_lima_ahora() - timedelta(days=DIAS_FRESCO)).date().isoformat()
    out = []
    for vid, r in list_resumenes().items():
        if (r.get("generated_at") or "") >= desde and r["resumen"] and (fechas.get(vid) or "") >= minimo:
            ideas = "; ".join(r["ideas_clave"][:4])
            out.append(f"{r['resumen'][:500]} Ideas: {ideas}")
    return out[:MAX["sesiones"]]


def tv(pe: sqlite3.Connection, desde: str) -> list[str]:
    try:
        return [f"{r['canal']}: {r['que'][:300]}" for r in pe.execute(
            "SELECT canal, que FROM tv_avisos WHERE ts >= ? ORDER BY ts DESC", (desde,))][:MAX["tv"]]
    except sqlite3.OperationalError:
        return []


def material(cerebro: sqlite3.Connection | None = None) -> dict[str, list[str]]:
    from cerebro.embeddings import conectar
    pe, cerebro = _ro("proyectos.db"), cerebro or conectar()
    desde = _desde_utc()
    return {"noticias": noticias(pe, cerebro, desde) if pe else [],
            "normas": normas(pe, desde) if pe else [],
            "pls": pls(_lima_ahora() - timedelta(hours=24)),
            "sesiones": sesiones(pe, desde),
            "tv": tv(pe, desde) if pe else []}


TITULOS = {"noticias": "NOTICIAS QUE LE INTERESAN A UN CLIENTE (con el por que del filtro)",
           "normas": "NORMAS DE INTERES PUBLICADAS", "pls": "PLs DE CLIENTES QUE SE MOVIERON",
           "sesiones": "SESIONES DEL CONGRESO/ASAMBLEA RESUMIDAS", "tv": "MENCIONES EN TV"}


def prompt(m: dict[str, list[str]]) -> str:
    perfiles = "\n".join(f"- {s} ({c['nombre']}, {'/'.join(c['paises'])}): temas {', '.join(c.get('temas_noticias', []))}"
                         for s, c in config.todos().items())
    partes = [f"Clientes:\n{perfiles}"]
    for k, items in m.items():
        if items:
            partes.append(f"== {TITULOS[k]} ({len(items)})\n" + "\n".join(items))
    return f"Hoy es {_lima_ahora():%A %d/%m/%Y}. Material de las ultimas 24 horas:\n\n" + "\n\n".join(partes)


def escribir(m: dict[str, list[str]], generar=llm.generar) -> str:
    # Sin cupo de flash (compartido con los chats) llm.generar cae solo a lite.
    return generar(prompt(m), system=SYSTEM, modelo=llm.FLASH)


def partir(texto: str, largo: int = 3500) -> list[str]:
    """Mensajes de Telegram (limite 4096) cortando entre parrafos."""
    out, actual = [], ""
    for par in texto.split("\n\n"):
        if actual and len(actual) + len(par) + 2 > largo:
            out.append(actual)
            actual = par
        else:
            actual = f"{actual}\n\n{par}" if actual else par
    return out + [actual] if actual else out


def _tabla(cerebro: sqlite3.Connection) -> None:
    cerebro.execute("CREATE TABLE IF NOT EXISTS resumen_dia (fecha TEXT PRIMARY KEY, texto TEXT, "
                    "material TEXT, enviado_at TEXT)")


def run(forzar: bool = False, enviar: bool = True) -> str | None:
    from cerebro.embeddings import conectar
    ahora = _lima_ahora()
    hoy = ahora.date().isoformat()
    cerebro = conectar()
    _tabla(cerebro)
    if not forzar:
        if ahora.hour < HORA_DESDE:
            print(f"[que_paso_hoy] son las {ahora:%H:%M} en Lima, sale desde las {HORA_DESDE}:00")
            return None
        if cerebro.execute("SELECT 1 FROM resumen_dia WHERE fecha = ? AND enviado_at IS NOT NULL", (hoy,)).fetchone():
            print(f"[que_paso_hoy] el de hoy ({hoy}) ya salio")
            return None
    m = material()
    print("[que_paso_hoy] material:", {k: len(v) for k, v in m.items()})
    texto = escribir(m).strip()
    mensajes = partir(f"¿Qué pasó hoy? · {ahora:%d/%m}\n\n{texto}")
    enviado = None
    if enviar:
        from congreso_live.notify import enviar_whatsapp
        if all([enviar_whatsapp(x) for x in mensajes]):
            enviado = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cerebro.execute("INSERT OR REPLACE INTO resumen_dia VALUES (?,?,?,?)",
                    (hoy, texto, json.dumps(m, ensure_ascii=False), enviado))
    cerebro.commit()
    print(texto)
    return texto


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--forzar", action="store_true", help="fuera de horario o aunque ya haya salido")
    ap.add_argument("--no-enviar", action="store_true", help="solo escribir, sin Telegram")
    a = ap.parse_args()
    run(forzar=a.forzar, enviar=not a.no_enviar)
