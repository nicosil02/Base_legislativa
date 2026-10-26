"""¿Le interesa a este cliente y por qué? Gemini juzga cada noticia nueva por
cliente, con su bluebook (notas.md) y las alertas que ya se le mandaron.

Corre en cerebro.yml despues de embeber: solo mira noticias de las ultimas
48 h que el cerebro ya acerca al perfil del cliente (UMBRAL_CANDIDATA o mas) y
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
# Puerta de entrada al juez. Con AFINIDAD_MEDIA (0.55) se quedaban afuera la replica de
# Salud con Lupa sobre plaguicidas (0.547 Bayer) y EsSalud sin oncologicos (0.542): el
# embedding solo ve el titulo. El juez es el filtro estricto; esto solo decide a quien ve.
# ponytail: umbral fijo, si Gemini se queda sin cupo subir a 0.52 (~2/3 de candidatas).
UMBRAL_CANDIDATA = 0.50

SYSTEM = ("Sos analista de asuntos publicos en Vali Consultores (Peru y Ecuador). Decidis si "
          "una noticia merece una alerta para un cliente puntual, segun su perfil real. Se "
          "estricto: interesa solo si hay una decision o propuesta publica concreta (norma, "
          "proyecto de ley, accion de un regulador o ministerio, compra publica, cambio de "
          "autoridad) sobre sus temas, un actor de su perfil, o un eje que el perfil pide "
          "explicitamente (ej. relacion con EE.UU. o anuncios de gobierno, si el perfil los "
          "nombra). Encuestas, tendencias de mercado, columnas de opinion, coyuntura general "
          "o algo que solo comparte palabras con su sector, no.")

# Primero el tipo, despues el veredicto: el modelo lite se salta el "no" del
# SYSTEM (encuestas y viajes oficiales salian como "interesa"), asi que los
# tipos que nunca merecen alerta se descartan en codigo.
TIPOS = ["decision_publica", "proyecto_o_debate", "cambio_de_autoridad", "compra_publica",
         "declaracion_de_autoridad", "investigacion_periodistica", "encuesta_o_estudio", "opinion_o_analisis",
         "tramite_administrativo", "evento_o_protocolo", "otro"]
# evento_o_protocolo no: el perfil de Google pide visitas de EE.UU. explicitamente.
TIPOS_NO = {"encuesta_o_estudio", "opinion_o_analisis", "tramite_administrativo"}

SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "indice": {"type": "integer"}, "tipo": {"type": "string", "enum": TIPOS},
    "interesa": {"type": "boolean"}, "por_que": {"type": "string"}},
    "required": ["indice", "tipo", "interesa", "por_que"]}}


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

Para CADA noticia de abajo responde {{"indice", "tipo", "interesa", "por_que"}}.
"tipo": decision_publica (norma, resolucion, medida de un regulador o ministerio), proyecto_o_debate
(PL, dictamen, debate o consulta publica de una norma), cambio_de_autoridad (designacion, renuncia,
censura), compra_publica, declaracion_de_autoridad (un ministro, regulador o embajador anuncia o
fija posicion), investigacion_periodistica (un medio documenta hechos nuevos, como documentos,
reuniones o cifras, sobre una decision publica o un actor del perfil, incluida su replica a un
desmentido; NO es opinion), encuesta_o_estudio (cifras, rankings, sondeos, reportes de mercado),
opinion_o_analisis (columna, entrevista a un experto, nota explicativa, consejos),
tramite_administrativo (viajes oficiales, licencias, encargos internos, modificaciones
presupuestarias), evento_o_protocolo (visitas, ceremonias, premios, reuniones sin resultado), otro.
"por_que" es una frase corta y concreta (que le toca al cliente y por que), sin repetir el titulo.

{lista}"""


def juzgar(slug: str, items: list[dict], generar=llm.generar) -> dict[int, tuple[bool, str]]:
    """{indice (1..n): (interesa, por_que)}. Indices que Gemini no devuelve no aparecen."""
    notas = (ROOT / "clientes" / slug / "notas.md").read_text(encoding="utf-8")
    alertas = [e["encabezado"] + " " + e["cuerpo"].split("\n", 1)[0] for e in historial.entradas(slug)]
    texto = generar(prompt(slug, notas, alertas, items), system=SYSTEM, modelo=llm.LITE, schema=SCHEMA)
    out = {}
    for v in json.loads(texto or "[]"):
        if isinstance(v, dict) and isinstance(v.get("indice"), int) and 1 <= v["indice"] <= len(items):
            out[v["indice"]] = (bool(v.get("interesa")) and v.get("tipo") not in TIPOS_NO,
                                str(v.get("por_que") or "").strip())
    return out


def candidatos(cerebro: sqlite3.Connection, noticias: sqlite3.Connection, slug: str) -> list[dict]:
    from cerebro.embeddings import afinidad
    from noticias.digest import _es_reciente
    desde = (datetime.now(timezone.utc) - timedelta(hours=VENTANA_HORAS)).strftime("%Y-%m-%dT%H:%M:%S")
    filas = {r[0]: r for r in noticias.execute(
        """SELECT n.id, n.titulo, n.resumen, COALESCE(n.fecha_pub, n.first_seen_at), f.nombre, f.pais
           FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
           WHERE f.activa = 1 AND n.first_seen_at >= ?""", (desde,))}
    ya = {r[0] for r in cerebro.execute("SELECT clave FROM relevancia WHERE cliente = ?", (slug,))}
    af = afinidad([f"noticia_{i}" for i in filas if f"noticia_{i}" not in ya], slug, cerebro)
    elegidas = sorted((c for c, v in af.items() if v >= UMBRAL_CANDIDATA), key=af.get, reverse=True)
    out = []
    cubiertos = historial.paises(slug)
    for clave in elegidas:
        _, titulo, resumen, fecha, fuente, pais = filas[int(clave.split("_", 1)[1])]
        # first_seen_at es cuando el sistema la vio: las busquedas de Google
        # News traen notas de hace años. Lo que cuenta es cuando se publico.
        if pais not in cubiertos or not _es_reciente({"fecha_pub": fecha}, VENTANA_HORAS // 24):
            continue
        if len(out) == MAX_POR_CLIENTE:
            break
        out.append({"clave": clave, "titulo": titulo, "resumen": (resumen or "")[:500],
                    "fecha": (fecha or "")[:10], "fuente": fuente, "pais": pais})
    return out


def run(rejuzgar: bool = False) -> dict:
    from cerebro.embeddings import _db, conectar
    pe = _db("proyectos.db")
    if not pe:
        raise SystemExit("[filtro] falta proyectos.db")
    cerebro = conectar()
    asegurar_tabla(cerebro)
    if rejuzgar:  # tras cambiar el criterio: lo de la ventana se vuelve a juzgar
        desde = (datetime.now(timezone.utc) - timedelta(hours=VENTANA_HORAS)).isoformat(timespec="seconds")
        print(f"[filtro] rejuzgo {cerebro.execute('DELETE FROM relevancia WHERE evaluado_at >= ?', (desde,)).rowcount}")
        cerebro.commit()
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
    ap.add_argument("--rejuzgar", action="store_true", help="borra y rejuzga lo de las ultimas 48 h")
    run(ap.parse_args().rejuzgar)
