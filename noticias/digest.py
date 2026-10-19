"""Digest de noticias nuevas y relevantes (PE + EC) por WhatsApp: un
mensaje con secciones PE/EC, donde la cobertura de varios medios sobre el
MISMO evento va en una sola linea. Solo manda si hay algo nuevo; el estado
(ultimo id revisado por pais) vive en `noticias_digest_state`.

Relevancia: solo "Coyuntura política" pura (noticias.temas.clasificar), mas
las normas que tocan a un cliente. Sumar todo `es_normativa` inundaba el
canal con resoluciones administrativas; eso queda como badge en la app.

El agrupado por similitud (TF-IDF) usa como corpus TODAS las noticias
relevantes nuevas del pais en esa corrida: con 2-3 items el TF-IDF no
discrimina bien.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from noticias.historias import agrupar
from noticias.temas import (FUENTES_MULTIPAIS, clasificar, es_fuente_multipais,
                            es_normativa_de_interes, es_seccion_fuera_de_foco, pais_por_contenido)

UMBRAL_SIMILITUD = 0.35
MAX_GRUPOS_POR_PAIS = 12
# Las busquedas de Google News van por relevancia, no por fecha: un articulo
# de hace años entra hoy a la DB como nuevo. 2 dias de margen por fines de
# semana y demoras del pipeline.
DIAS_FRESCURA = 2


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS noticias_digest_state (
            pais TEXT PRIMARY KEY,
            ultimo_id INTEGER NOT NULL
        )
    """)


def _ultimo_id(conn: sqlite3.Connection, pais: str) -> int:
    row = conn.execute(
        "SELECT ultimo_id FROM noticias_digest_state WHERE pais=?", (pais,)
    ).fetchone()
    return row[0] if row else 0


def _guardar_ultimo_id(conn: sqlite3.Connection, pais: str, ultimo_id: int) -> None:
    conn.execute(
        "INSERT INTO noticias_digest_state (pais, ultimo_id) VALUES (?, ?) "
        "ON CONFLICT(pais) DO UPDATE SET ultimo_id=excluded.ultimo_id",
        (pais, ultimo_id),
    )
    conn.commit()


def _noticias_desde(conn: sqlite3.Connection, pais: str, desde_id: int) -> list[dict]:
    """Candidatos de `pais`, mas los de fuentes multipais (FUENTES_MULTIPAIS)
    reclasificados por contenido: el pais catalogado es de la fuente, no del
    articulo."""
    placeholders = ",".join("?" for _ in FUENTES_MULTIPAIS)
    filas = conn.execute(
        f"""
        SELECT n.id, n.titulo, n.resumen, n.url, f.nombre AS fuente, n.tags, f.pais, n.fecha_pub
        FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
        WHERE (f.pais = ? OR f.nombre IN ({placeholders}))
          AND f.activa = 1 AND n.id > ?
        ORDER BY n.id
        """,
        (pais, *FUENTES_MULTIPAIS, desde_id),
    ).fetchall()
    salida = []
    for r in filas:
        fuente, pais_fuente = r[4], r[6]
        pais_real = (pais_por_contenido(r[1], r[2], pais_fuente)
                     if es_fuente_multipais(fuente) else pais_fuente)
        if pais_real != pais or es_seccion_fuera_de_foco(r[3]):
            continue
        salida.append({"id": r[0], "titulo": r[1], "resumen": r[2], "url": r[3],
                        "fuente": fuente, "tags": r[5], "fecha_pub": r[7]})
    return salida


def _es_reciente(n: dict, dias: int = DIAS_FRESCURA) -> bool:
    """True si `fecha_pub` es de los ultimos `dias` dias, o si no tiene
    fecha_pub (como COALESCE(fecha_pub, first_seen_at) en las paginas)."""
    fecha_pub = n.get("fecha_pub")
    if not fecha_pub:
        return True
    try:
        fecha = datetime.fromisoformat(fecha_pub.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    if fecha.tzinfo is None:  # "2026-10-18" o sin zona: tumbaba el filtro de clientes
        fecha = fecha.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fecha) <= timedelta(days=dias)


def _es_relevante(n: dict) -> bool:
    """Coyuntura política pura y reciente, o una norma que toca a un cliente."""
    # Normas (tag "normas" de gobpe, "normativa" de El Peruano/RO EC): el
    # tramite administrativo nombra "JNE"/"fiscal"/"PCM" por la entidad
    # emisora y pasaria como Coyuntura política. Solo pasan las de interes.
    tags = (n.get("tags") or "").split("|")
    if "normas" in tags or "normativa" in tags:
        return es_normativa_de_interes(n.get("tags"), n.get("resumen")) and _es_reciente(n)
    if not _es_reciente(n):
        return False
    # Coyuntura política PURA: una nota de Salud o Crop que nombra a un
    # ministro de paso no es coyuntura; esos temas van por el bluebook.
    temas = clasificar(n["titulo"], n["resumen"], n.get("url"))
    return temas == ["Coyuntura política"]


def _agrupar_por_similitud(items: list[dict], umbral: float = UMBRAL_SIMILITUD) -> list[list[dict]]:
    """Grupos de items con titulos parecidos (TF-IDF, greedy por
    representante: historias.agrupar)."""
    if len(items) <= 1:
        return [[i] for i in items]
    idx = agrupar([i["titulo"] or "" for i in items], umbral=umbral, modelo=False)
    grupos: list[list[dict]] = [[] for _ in range(max(idx) + 1)]
    for item, g in zip(items, idx):
        grupos[g].append(item)
    return grupos


def armar_grupos(conn: sqlite3.Connection, pais: str) -> tuple[list[list[dict]], int]:
    """Devuelve (grupos, nuevo_ultimo_id). `nuevo_ultimo_id` avanza sobre
    TODO lo visto (relevante o no) para no re-escanear siempre lo mismo -
    se guarda solo si el caller decide continuar (ver run())."""
    desde = _ultimo_id(conn, pais)
    vistas = _noticias_desde(conn, pais, desde)
    if not vistas:
        return [], desde

    relevantes = [n for n in vistas if _es_relevante(n)]
    grupos = _agrupar_por_similitud(relevantes)
    # Mas recientes primero - si hay mas de MAX_GRUPOS_POR_PAIS, importa
    # mas lo que acaba de pasar que lo mas viejo del lote sin revisar.
    grupos.sort(key=lambda g: max(n["id"] for n in g), reverse=True)
    return grupos[:MAX_GRUPOS_POR_PAIS], max(n["id"] for n in vistas)


def _matches_pl_ec(vistas: list[dict]) -> list[dict]:
    """Noticias EC nuevas (de cualquier tema: un PL de agro es "Crop") que
    parecen hablar de un PL de las matrices de clientes (clientes/matrices.py):
    la prensa lo cuenta antes que el portal de la Asamblea. Agrupadas por PL."""
    from clientes.matrices import coincide_con_noticia, pls_trackeados_ec

    trackeados = pls_trackeados_ec()
    if not trackeados:
        return []
    por_pl: dict[str, dict] = {}
    for n in vistas:
        if not _es_reciente(n):
            continue
        texto = f"{n['titulo'] or ''} {n['resumen'] or ''}"
        for pl in trackeados:
            if coincide_con_noticia(pl.get("titulo_matriz"), texto, noticia_titulo=n["titulo"]):
                clave = pl["titulo_matriz"]
                if clave in por_pl:
                    por_pl[clave]["n_articulos"] += 1
                else:
                    por_pl[clave] = {**n, "pl_titulo": clave, "clientes": pl.get("clientes", []),
                                     "n_articulos": 1}
                break
    # Mismo tope que armar_grupos, mas recientes primero.
    salida = sorted(por_pl.values(), key=lambda n: n["id"], reverse=True)
    return salida[:MAX_GRUPOS_POR_PAIS]


def _formatear_match_pl(n: dict) -> str:
    from congreso_live.notify import acortar_url

    clientes = "/".join(n.get("clientes") or []) or "cliente"
    extra = f" (+{n['n_articulos'] - 1} más)" if n.get("n_articulos", 1) > 1 else ""
    return f"- [{clientes}] {n['pl_titulo']}: {n['titulo']}{extra}\n  {acortar_url(n['url'])}"


def _formatear_grupo(g: list[dict]) -> str:
    from congreso_live.notify import acortar_url

    principal = g[0]
    linea = f"- {principal['titulo']}"
    otras_fuentes = sorted({n["fuente"] for n in g[1:]} - {principal["fuente"]})
    if otras_fuentes:
        linea += f" ({principal['fuente']} + {', '.join(otras_fuentes)})"
    # Las URLs de Google News pesan 500-700 caracteres.
    linea += f"\n  {acortar_url(principal['url'])}"
    return linea


# CallMeBot manda el texto en la URL (GET): un mensaje largo da "414
# Request-URI Too Large". Lo que no entra va en mensajes siguientes.
MENSAJE_MAX_CHARS = 1500


def formatear_mensajes(grupos_pe: list[list[dict]], grupos_ec: list[list[dict]],
                        matches_pl_ec: list[dict] = ()) -> list[str]:
    """Lista de mensajes de WhatsApp a mandar - [] si no hay nada relevante,
    normalmente 1 mensaje, y varios (numerados, con "(cont.)" en el titulo
    de continuacion) si el contenido no entra en MENSAJE_MAX_CHARS. Cada
    _formatear_grupo/_formatear_match_pl es una unidad atomica - nunca se
    parte una noticia a la mitad entre dos mensajes."""
    secciones: list[tuple[str, list[str]]] = []
    if grupos_pe:
        secciones.append(("*PERÚ*", [_formatear_grupo(g) for g in grupos_pe]))
    if grupos_ec:
        secciones.append(("*ECUADOR*", [_formatear_grupo(g) for g in grupos_ec]))
    if matches_pl_ec:
        secciones.append(("*PL DE INTERÉS (ECUADOR)*",
                          [_formatear_match_pl(n) for n in matches_pl_ec]))
    if not secciones:
        return []

    titulo = "📰 Noticias relevantes"
    mensajes: list[str] = []
    partes: list[str] = [titulo]
    largo = len(titulo)

    def _cerrar_mensaje() -> None:
        nonlocal partes, largo
        mensajes.append("\n\n".join(partes))
        partes = [f"{titulo} (cont.)"]
        largo = len(partes[0])

    for header, items in secciones:
        header_en_mensaje = False
        for item in items:
            bloque = item if header_en_mensaje else f"{header}\n{item}"
            # len(partes) > 1: nunca cerramos un mensaje vacio (si el
            # primer item de un mensaje nuevo ya excede el limite solo,
            # lo dejamos pasar igual - mejor un mensaje largo que perder
            # la noticia).
            if len(partes) > 1 and largo + 2 + len(bloque) > MENSAJE_MAX_CHARS:
                _cerrar_mensaje()
                header_en_mensaje = False
                bloque = f"{header}\n{item}"
            partes.append(bloque)
            largo += 2 + len(bloque)
            header_en_mensaje = True
    mensajes.append("\n\n".join(partes))

    if len(mensajes) > 1:
        mensajes = [f"{m}\n\n({i}/{len(mensajes)})" for i, m in enumerate(mensajes, 1)]
    return mensajes


def run(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Corre el digest completo: arma grupos PE+EC, cruza las noticias EC
    nuevas contra los PL trackeados de cliente, manda por WhatsApp si hay
    algo, y avanza el estado (siempre, haya o no algo relevante - lo visto
    sin relevancia no debe re-escanearse en la proxima corrida)."""
    from congreso_live.notify import enviar_whatsapp

    init_schema(conn)
    grupos_pe, ultimo_pe = armar_grupos(conn, "PE")
    grupos_ec, ultimo_ec = armar_grupos(conn, "EC")
    # Mismo lote EC que leyo armar_grupos, sin el filtro _es_relevante.
    vistas_ec = _noticias_desde(conn, "EC", _ultimo_id(conn, "EC"))
    matches_pl = _matches_pl_ec(vistas_ec)
    mensajes = formatear_mensajes(grupos_pe, grupos_ec, matches_pl)
    # Sin nada relevante no se manda nada (mismo criterio que el correo).
    enviado = False
    if not dry_run:
        # Lista (no generador): `all()` corta en el primer False y se
        # saltaria el envio de los mensajes siguientes si el primero falla.
        resultados = [enviar_whatsapp(m) for m in mensajes]
        enviado = all(resultados)

    if not dry_run:
        _guardar_ultimo_id(conn, "PE", ultimo_pe)
        _guardar_ultimo_id(conn, "EC", ultimo_ec)

    return {
        "grupos_pe": len(grupos_pe), "grupos_ec": len(grupos_ec),
        "matches_pl_ec": len(matches_pl),
        "mensaje": "\n\n---\n\n".join(mensajes), "mensajes": mensajes,
        "enviado": enviado,
    }
