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
import re
import sqlite3
from datetime import datetime, timedelta, timezone

from clientes import config
from core import llm
from core.http import session
from core.db import db_path
from core.tiempo import LIMA

HORA_DESDE = 18          # hora Lima desde la que sale el resumen del dia
# Lo que importa es cuando PASO, no cuando el sistema lo vio: las busquedas
# de Google News traen notas de hace años y el backfill resume sesiones viejas.
DIAS_FRESCO = 2
DIAS_PDF_VIEJO = 365     # un PDF de hace mas de un año resubido a la web no es novedad
MAX = {"noticias": 70, "normas": 25, "pls": 40, "sesiones": 12, "tv": 12}

SYSTEM = """Eres analista senior de asuntos publicos en Vali Consultores (Peru y Ecuador).
Respondes la pregunta de todos los dias del equipo: "¿que cosas de interes pasaron hoy?".

El material ya paso un filtro automatico que deja pasar ruido: tu trabajo es tirar la mayor
parte. Un dia normal tiene de 0 a 5 cosas que valen; 8 es el maximo.

Vale solo lo que cambia algo para un cliente: una norma o resolucion publicada, un proyecto de
ley presentado o que avanza, una decision o anuncio concreto de una autoridad sobre sus temas,
una compra publica, una consulta publica con plazo, o un cambio de ministro, viceministro o jefe
de la entidad que lo regula.

No va aunque este en el material:
- viajes, visitas, ceremonias, foros y reuniones o "coordinaciones" sin un compromiso concreto
- cooperacion o acuerdos genericos (seguridad, narcotrafico, "fortalecer la relacion"); si
  vale un proceso formal con pasos y compromisos, como la adhesion a la OCDE
- politica exterior o seguridad en general; la relacion con EE.UU. solo si toca comercio,
  tecnologia, datos o el sector del cliente
- designaciones de mandos medios, regionales o encargos temporales
- becas, capacitaciones, obras o inversiones regionales, medidas de emergencia generales
- algo que solo comparte una palabra con el sector del cliente
Prueba: si el "por que" te sale generico ("para monitorear", "para dar seguimiento", "impacta
en el sector", "define estandares"), no va.

Formato: una lista ordenada por importancia, cada hecho una sola vez aunque le toque a varios
clientes. Cada punto empieza con los clientes entre corchetes, por ejemplo [Bayer Crop,
Syngenta], y dice en una o dos frases que paso, que le cambia en concreto y el link. Despues,
"Hilos para seguir" con 0 a 3 cosas no obvias y concretas (que buscarias y donde); si no hay,
omite la seccion.

Reglas: solo lo que esta en el material, nada inventado. A un cliente solo le cuentas cosas
de sus paises. Espanol simple y directo, frases cortas, sin metaforas ni jerga. Formato de
Telegram: links como [link](url), sin titulos (#) ni **dobles asteriscos**. Si no hubo nada
que pase la prueba, escribe una sola linea diciendo que el dia fue flojo."""


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


# Mismo hecho: lo dijo el juez (mismo_hecho), o vectores >= UMBRAL_NOTICIAS entre
# portales distintos, o titulares casi iguales. Lo ultimo hace falta porque el
# vector mezcla titulo y resumen: "ViaOCDE" en RPP y Google News, o "El Nino
# amenaza la productividad avicola" en SENASA y AgroPeru, daban 0,79-0,81 y a
# ese nivel tambien empatan cosas distintas (biocomercio vs semillas nativas).
TITULO_IGUAL = 0.6  # Jaccard de palabras del titular sin el " - Medio" del final


def _palabras_titulo(t: str) -> frozenset[str]:
    from core.text import norm
    t = re.split(r"\s+[-|–—]\s+(?=[^-|–—]{2,60}$)", t or "")[0]
    return frozenset(re.findall(r"\w{4,}", norm(t)))


def _mismo_titulo(a: frozenset, b: frozenset) -> bool:
    return len(a) >= 3 and len(b) >= 3 and len(a & b) / len(a | b) >= TITULO_IGUAL


def _grupos(clave: list[int], cerebro: sqlite3.Connection, candidatas: dict[int, dict]) -> list[list[int]]:
    """Grupos del mismo hecho alrededor de `clave` (las que interesan, mas
    recientes primero). `candidatas` {id: fila con titulo y fuente} son las
    demas noticias de la ventana: entran al grupo como fuente extra aunque el
    filtro no las haya marcado. Cada grupo empieza con una de `clave`."""
    import numpy as np
    from cerebro.embeddings import vectores_noticias
    from noticias.historias import UMBRAL_NOTICIAS, _NUM_NORMA
    todas = list(dict.fromkeys(clave + list(candidatas)))
    try:
        vec = vectores_noticias(todas, cerebro)
    except Exception:
        vec = {}
    juicio: dict[tuple[int, int], bool] = {}
    if clave:
        lista_c, lista_t = ",".join(map(str, clave)), ",".join(map(str, todas))
        try:
            for a, b, igual in cerebro.execute(
                    f"SELECT a, b, igual FROM mismo_hecho WHERE (a IN ({lista_c}) AND b IN ({lista_t})) "
                    f"OR (b IN ({lista_c}) AND a IN ({lista_t}))"):
                juicio[(a, b)] = juicio[(b, a)] = bool(igual)
        except sqlite3.OperationalError:  # cerebro.db sin la tabla todavia
            pass
    pal = {i: _palabras_titulo(candidatas[i]["titulo"]) for i in todas}
    normas = {i: set(_NUM_NORMA.findall(candidatas[i]["titulo"] or "")) for i in todas}
    ids_v = [i for i in todas if i in vec]
    m = np.stack([np.asarray(vec[i], "float32") for i in ids_v]) if ids_v else None

    en_clave = set(clave)
    padre = {i: i for i in todas}

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i
    for c in clave:
        sims = dict(zip(ids_v, m @ np.asarray(vec[c], "float32"))) if c in vec and m is not None else {}
        for j in todas:
            if j == c:
                continue
            if (c, j) in juicio:
                igual = juicio[(c, j)]
            elif normas[c] and normas[j] and not normas[c] & normas[j]:
                igual = False  # DS 200-2026-EF vs 201-2026-EF
            else:
                # el vector solo entre marcadas: un post largo de SENASA sobre El Nino
                # daba 0,83 con cualquier nota de El Nino, sin ser el mismo hecho
                igual = _mismo_titulo(pal[c], pal[j]) or (
                    j in en_clave and sims.get(j, 0) >= UMBRAL_NOTICIAS
                    and candidatas[c]["fuente"] != candidatas[j]["fuente"])
            if igual:
                padre[raiz(j)] = raiz(c)
    grupos: dict[int, list[int]] = {}
    for i in clave:
        grupos.setdefault(raiz(i), []).append(i)
    for i in candidatas:
        if i not in en_clave and raiz(i) in grupos:
            grupos[raiz(i)].append(i)
    return list(grupos.values())


def _fresca(r) -> bool:
    from noticias.digest import _es_reciente
    return _es_reciente({"fecha_pub": r["fecha_pub"]}, DIAS_FRESCO)


@lru_cache(maxsize=None)
def _fecha_pdf(url: str) -> datetime | None:
    """Fecha de creacion dentro del PDF; None si no se puede leer."""
    import pymupdf
    try:
        r = session().get(url, timeout=30)
        r.raise_for_status()
        fecha = pymupdf.open(stream=r.content, filetype="pdf").metadata["creationDate"]
        return datetime.strptime(fecha[2:10], "%Y%m%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _pdf_viejo(url: str) -> bool:
    """Las webs del Estado resuben documentos viejos en carpetas del mes: la
    Resolucion 0117 de Agrocalidad, de 2016, aparecio como subida en 2026."""
    if not url.lower().split("?")[0].endswith(".pdf"):
        return False
    fecha = _fecha_pdf(url)
    return bool(fecha) and datetime.now(timezone.utc) - fecha > timedelta(days=DIAS_PDF_VIEJO)


def titular_norma(titulo: str) -> tuple[str, str | None]:
    """El Peruano titula "ENTIDAD — RESOLUCIÓN N° X: Modifican..." y gob.pe
    "634-2026-MINSA — APROBAR la baja...". Devuelve lo que hace la norma y
    aparte de quien es. Agrocalidad deja el nombre del archivo firmado
    ("Aprobado(1) signed signed")."""
    limpio = re.sub(r"(\(\d+\))?(\s+signed)+\s*$", "", titulo, flags=re.I)
    m = re.match(r"^([^a-z]+?) [—–-] (.+?): (.+)$", limpio)
    if m:
        return m[3], f"{m[1].capitalize()}, {m[2]}"
    m = re.match(r"^(\d\S+) [—–-] (\S+)(.*)$", limpio)
    return (m[2].capitalize() + m[3], m[1]) if m else (limpio, None)


def reparar(texto: str) -> str:
    """Canal N llega de Google News con el UTF-8 leido como latin-1 ("MarÃa")."""
    if "Ã" not in texto and "Â" not in texto:
        return texto
    return texto.encode("cp1252", "ignore").decode("utf-8", "ignore") or texto


def _url(url: str) -> str:
    """Las de Google News pesan 500+ caracteres: se comen el prompt y el mensaje."""
    from congreso_live.notify import acortar_url
    return acortar_url(url) if "news.google." in url else url


def hallazgos(pe: sqlite3.Connection, cerebro: sqlite3.Connection, desde: str) -> list[dict]:
    """Noticias que le interesan a un cliente, juntando las del mismo hecho."""
    por_id: dict[int, list[tuple[str, str]]] = {}
    for clave, cliente, por_que in cerebro.execute(
            "SELECT clave, cliente, por_que FROM relevancia WHERE interesa = 1"):
        por_id.setdefault(int(clave.split("_", 1)[1]), []).append((cliente, por_que))
    if not por_id:
        return []
    ventana = {r["id"]: r for r in pe.execute(
        """SELECT n.id, n.titulo, n.url, n.fecha_pub, n.tags, f.nombre AS fuente, f.pais FROM noticias n
           JOIN noticias_fuentes f ON f.id = n.fuente_id
           WHERE n.first_seen_at >= ? ORDER BY n.first_seen_at DESC""", (desde,))}
    filas = {i: r for i, r in ventana.items() if i in por_id and _fresca(r) and not _pdf_viejo(r["url"])}
    out = []
    for g in _grupos(list(filas), cerebro, ventana)[:MAX["noticias"]]:
        r = ventana[g[0]]
        # otras fuentes del mismo hecho, una por medio y sin repetir el enlace
        fuentes, vistas = [], {r["fuente"], r["url"]}
        for i in g[1:]:
            x = ventana[i]
            if x["fuente"] not in vistas and x["url"] not in vistas:
                vistas |= {x["fuente"], x["url"]}
                fuentes.append({"titulo": reparar(x["titulo"]), "url": x["url"], "fuente": x["fuente"], "fecha": x["fecha_pub"]})
        out.append({"id": r["id"], "ids": g, "titulo": reparar(r["titulo"]), "url": r["url"], "fuente": r["fuente"],
                    "pais": r["pais"], "fecha": r["fecha_pub"], "es_norma": any(x in (r["tags"] or "") for x in ("normativa", "normas")),
                    "otras": [f["fuente"] for f in fuentes], "fuentes": fuentes,
                    "clientes": {c: p for i in g for c, p in por_id.get(i, [])}})
    return out


def noticias(pe: sqlite3.Connection, cerebro: sqlite3.Connection, desde: str) -> list[str]:
    return [f"[{h['pais']}] {h['titulo']} ({h['fuente']}"
            + (f"; tambien en {', '.join(h['otras'])}" if h["otras"] else "") + f") {_url(h['url'])}\n"
            + "".join(f"   - {c}: {p}\n" for c, p in h["clientes"].items())
            for h in hallazgos(pe, cerebro, desde)]


def normas_datos(pe: sqlite3.Connection, desde: str) -> list[dict]:
    from noticias.temas import es_normativa_de_interes
    out = []
    for r in pe.execute(
            """SELECT n.titulo, n.resumen, n.url, n.tags, n.fecha_pub, f.pais FROM noticias n
               JOIN noticias_fuentes f ON f.id = n.fuente_id
               WHERE n.first_seen_at >= ? AND (n.tags LIKE '%normativa%' OR n.tags LIKE '%normas%')""",
            (desde,)):
        if _fresca(r) and es_normativa_de_interes(r["tags"], r["resumen"]) and not _pdf_viejo(r["url"]):
            out.append({"titulo": r["titulo"], "resumen": r["resumen"] or "", "url": _url(r["url"]), "pais": r["pais"]})
    return out[:MAX["normas"]]


def normas(pe: sqlite3.Connection, desde: str) -> list[str]:
    return [f"[{n['pais']}] {n['titulo']}: {n['resumen'][:250]} {n['url']}" for n in normas_datos(pe, desde)]


@lru_cache(maxsize=None)
def _matriz_nums(slug: str, pais: str) -> frozenset[str]:
    # La matriz es un xlsx: leerla por cada PL tardaba minutos.
    return frozenset(f["pl_numero"] for f in config.matriz(slug, pais))


def _clientes_de_pl(tema: str | None, numero: str, pais: str) -> list[str]:
    return [s for s in config.slugs(pais)
            if (tema and tema in config.todos()[s].get("categorias_pl", []))
            or numero in _matriz_nums(s, pais)]


def pls_datos(desde: datetime) -> list[dict]:
    """PL de clientes (categoria o matriz) que cambiaron de estado o comision."""
    from core import legislativo
    out = []
    for pais in legislativo.PAISES:
        for r in legislativo.cambios(pais, desde):
            cl = _clientes_de_pl(r["categoria"], r["numero"], pais)
            if cl:
                out.append({**r, "pais": pais, "clientes": cl})
    return out[:MAX["pls"]]


def pls(desde: datetime) -> list[str]:
    return [f"[{r['pais']}] PL {r['numero']} ({r['categoria']}; {', '.join(r['clientes'])}) {r['titulo'][:160]} "
            f"-> {r['campo']}: {r['valor']} ({r['fecha']}) {r['url'] or ''}".rstrip() for r in pls_datos(desde)]


def sesiones_datos(pe: sqlite3.Connection | None, desde: str) -> list[dict]:
    from congreso_live.resumenes_store import list_resumenes
    filas = {r[0]: r for r in pe.execute("SELECT video_id, fecha, titulo, tipo FROM sesiones_transcripciones")} if pe else {}
    minimo = (_lima_ahora() - timedelta(days=DIAS_FRESCO)).date().isoformat()
    out = []
    for vid, r in list_resumenes().items():
        _, fecha, titulo, tipo = filas.get(vid, ("", "", "", ""))
        if (r.get("generated_at") or "") >= desde and r["resumen"] and (fecha or "") >= minimo:
            out.append({"video_id": vid, "titulo": titulo, "tipo": tipo or "", "fecha": fecha, "resumen": r["resumen"],
                        "ideas": r["ideas_clave"]})
    return out[:MAX["sesiones"]]


def sesiones(pe: sqlite3.Connection | None, desde: str) -> list[str]:
    return [f"{s['resumen'][:500]} Ideas: {'; '.join(s['ideas'][:4])}" for s in sesiones_datos(pe, desde)]


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
