"""Digest de noticias nuevas y relevantes (PE + EC) por WhatsApp, agrupando
articulos de distintas fuentes que cubren el MISMO evento en una sola
linea.

Nicolas 2026-09-17: "quiero saber que noticias nuevas salen" + "varias
del mismo tema me las manda... quiero tener LA NOTICIA, agruparla" +
"que me pueda avisar... por WhatsApp, porque estar entrando a la app...
es mucho, tanto en Peru como en Ecuador". Decidido con el: un solo
mensaje con las dos secciones (PE/EC), solo cuando hay algo relevante
(no por horario fijo) - se corre en cada pasada del sync de noticias
(15x/dia, ver noticias.cli) y compara contra la tabla
`noticias_digest_state` (ultimo id de noticia ya revisado, por pais)
para no repetir nada.

Relevancia: SOLO tema "Coyuntura política" (noticias.temas.clasificar).
Probado en vivo 2026-09-17 contra datos reales: sumar tambien el flag
`es_normativa` (que las paginas Noticias PE/EC si usan, para el badge
"Normativa" en pantalla) inunda el digest con cada resolucion
administrativa individual de El Peruano/Ministerio Publico -
designaciones de fiscales, viajes en comision de servicios, etc. Un
canal de WhatsApp es mas caro de interrumpir que un badge en la app, y
"varias del mismo tema" (el problema real que motivo esto) se referia a
cobertura de prensa duplicada, no a tramite administrativo.

El agrupado por similitud (TF-IDF) usa como corpus TODAS las noticias
relevantes nuevas de ese pais en esa corrida - con pocos items (2-3) el
TF-IDF no discrimina bien (ver noticias/avances_ec.py, misma leccion).
Probado en vivo contra el corpus real de produccion: agrupa bien casos
reales (6 notas de distintos medios sobre la ratificacion de Julio
Velarde en el BCRP, o Marco Rubio/Trump cubiertos por El Universo Y El
Comercio a la vez, cada caso en 1 sola linea).
"""
from __future__ import annotations

import sqlite3

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from noticias.temas import clasificar

UMBRAL_SIMILITUD = 0.35
MAX_GRUPOS_POR_PAIS = 12


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
    filas = conn.execute(
        """
        SELECT n.id, n.titulo, n.resumen, n.url, f.nombre AS fuente, n.tags
        FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
        WHERE f.pais = ? AND f.activa = 1 AND n.id > ?
        ORDER BY n.id
        """,
        (pais, desde_id),
    ).fetchall()
    return [
        {"id": r[0], "titulo": r[1], "resumen": r[2], "url": r[3], "fuente": r[4], "tags": r[5]}
        for r in filas
    ]


def _es_relevante(n: dict) -> bool:
    """Solo "Coyuntura política" (probado en vivo 2026-09-17 contra el
    corpus real: incluir tambien `es_normativa` inunda el digest con cada
    resolucion administrativa individual de El Peruano/Ministerio Publico
    - designaciones de fiscales, viajes en comision de servicios, etc.
    Eso ya se ve como badge "Normativa" en la app para quien lo busca; un
    canal de WhatsApp es mas caro de interrumpir que un badge, y no es lo
    que Nicolas pidio ("varias del mismo tema" se referia a cobertura de
    prensa duplicada, no a resoluciones administrativas)."""
    # tags='normas' son resoluciones administrativas de los feeds gobpe
    # (MINSA/MIDAGRI/SENASA/MEF...) - tramite interno (licencias,
    # designaciones) que a veces dispara "Coyuntura política" en
    # clasificar() solo por mencionar "Decreto Legislativo" de pasada, no
    # por ser noticia real (verificado en vivo 2026-09-17). No se toca
    # clasificar() porque tambien lo usan las paginas Noticias PE/EC.
    if n.get("tags") == "normas":
        return False
    # clasificar() puede devolver VARIOS temas a la vez, y "ministro"/
    # "presidente" (palabras de Coyuntura política) aparecen tal cual en
    # notas que son 100% Salud o Crop y solo mencionan a un ministro de
    # paso (verificado en vivo 2026-09-17, caso real: Nicolas - "todo lo
    # que es salud lo cataloga como si si, pero no nos interesa todo salud
    # en general, ahi el bluebook es claro. en agro igual"). Se exige
    # Coyuntura política PURA (sin ningun otro tema) para que esta pasada
    # general no cuele noticias de Salud/Crop/Tech/KYC que solo comparten
    # esa palabra - el interes real y especifico en esos verticales vive
    # en el bluebook de cada cliente (clientes/<cliente>/notas.md), no en
    # "toda noticia de Salud/Agro" en general.
    temas = clasificar(n["titulo"], n["resumen"])
    return temas == ["Coyuntura política"]


def _agrupar_por_similitud(items: list[dict], umbral: float = UMBRAL_SIMILITUD) -> list[list[dict]]:
    """Clustering greedy simple: cada item entra al primer grupo cuyo
    representante (el primero) supera el umbral de similitud de titulo,
    o abre uno nuevo. Corpus de todos los items juntos (no de a pares) -
    con pocos items el TF-IDF pierde poder discriminativo (ver
    noticias/avances_ec.py, misma leccion)."""
    if len(items) <= 1:
        return [[i] for i in items]
    titulos = [i["titulo"] or "" for i in items]
    matriz = TfidfVectorizer(min_df=1).fit_transform(titulos)
    sims = cosine_similarity(matriz)

    grupos: list[list[int]] = []
    asignado = [-1] * len(items)
    for i in range(len(items)):
        if asignado[i] != -1:
            continue
        asignado[i] = len(grupos)
        grupos.append([i])
        for j in range(i + 1, len(items)):
            if asignado[j] == -1 and sims[i][j] >= umbral:
                asignado[j] = asignado[i]
                grupos[-1].append(j)
    return [[items[k] for k in g] for g in grupos]


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
    """Noticias EC nuevas (sin filtrar por relevancia/tema - un PL de agro
    puede clasificar como "Crop", no "Coyuntura política", asi que el
    filtro _es_relevante de arriba no aplica aca) que parecen hablar de un
    PL que ya trackeamos (matriz Bayer Crop/Syngenta + Incode, ver
    clientes/matrices.py) - señal temprana antes de que el portal de la
    Asamblea (sync cada 4-6h) lo refleje. Pedido real de Nicolas
    2026-09-18/19: conectar esto a WhatsApp, no solo al tag visual que ya
    existia en pages/6_Noticias_EC.py."""
    from clientes.matrices import coincide_con_noticia, pls_trackeados_ec

    trackeados = pls_trackeados_ec()
    if not trackeados:
        return []
    # Agrupado por PL (no un renglon por articulo) - probado en vivo
    # 2026-09-19 contra el corpus real: sin esto, un solo PL con cobertura
    # de varios medios (COIP, INIAP) inundaba el mensaje con 34 renglones
    # para ~5 PL distintos. Mismo problema real que ya motivo el agrupado
    # por similitud del digest general, aca resuelto mas simple: la CLAVE
    # de agrupacion ya se sabe (el propio PL matcheado), no hace falta
    # TF-IDF.
    por_pl: dict[str, dict] = {}
    for n in vistas:
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
    # Mismo tope que armar_grupos - mas recientes primero (por id de la
    # noticia representante de cada PL).
    salida = sorted(por_pl.values(), key=lambda n: n["id"], reverse=True)
    return salida[:MAX_GRUPOS_POR_PAIS]


def _formatear_match_pl(n: dict) -> str:
    clientes = "/".join(n.get("clientes") or []) or "cliente"
    extra = f" (+{n['n_articulos'] - 1} más)" if n.get("n_articulos", 1) > 1 else ""
    return f"- [{clientes}] {n['pl_titulo']}: {n['titulo']}{extra}\n  {n['url']}"


def _formatear_grupo(g: list[dict]) -> str:
    principal = g[0]
    linea = f"- {principal['titulo']}"
    otras_fuentes = sorted({n["fuente"] for n in g[1:]} - {principal["fuente"]})
    if otras_fuentes:
        linea += f" ({principal['fuente']} + {', '.join(otras_fuentes)})"
    linea += f"\n  {principal['url']}"
    return linea


def formatear_mensaje(grupos_pe: list[list[dict]], grupos_ec: list[list[dict]],
                      matches_pl_ec: list[dict] = ()) -> str:
    """'' si no hay nada relevante en ninguno de los dos paises ni matches
    de PL trackeados de Ecuador."""
    secciones = []
    if grupos_pe:
        secciones.append("*PERÚ*\n" + "\n".join(_formatear_grupo(g) for g in grupos_pe))
    if grupos_ec:
        secciones.append("*ECUADOR*\n" + "\n".join(_formatear_grupo(g) for g in grupos_ec))
    if matches_pl_ec:
        secciones.append("*PL DE INTERÉS (ECUADOR)*\n" +
                         "\n".join(_formatear_match_pl(n) for n in matches_pl_ec))
    if not secciones:
        return ""
    return "📰 Noticias relevantes\n\n" + "\n\n".join(secciones)


def run(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Corre el digest completo: arma grupos PE+EC, cruza las noticias EC
    nuevas contra los PL trackeados de cliente, manda por WhatsApp si hay
    algo, y avanza el estado (siempre, haya o no algo relevante - lo visto
    sin relevancia no debe re-escanearse en la proxima corrida)."""
    from congreso_live.notify import enviar_whatsapp

    init_schema(conn)
    grupos_pe, ultimo_pe = armar_grupos(conn, "PE")
    grupos_ec, ultimo_ec = armar_grupos(conn, "EC")
    # Mismo lote de noticias EC nuevas que armar_grupos ya leyo (antes de
    # avanzar el estado abajo) - re-consultado aca porque el match de PL
    # NO pasa por el filtro _es_relevante (ver _matches_pl_ec).
    vistas_ec = _noticias_desde(conn, "EC", _ultimo_id(conn, "EC"))
    matches_pl = _matches_pl_ec(vistas_ec)
    mensaje = formatear_mensaje(grupos_pe, grupos_ec, matches_pl)

    enviado = False
    if mensaje and not dry_run:
        enviado = enviar_whatsapp(mensaje)

    if not dry_run:
        _guardar_ultimo_id(conn, "PE", ultimo_pe)
        _guardar_ultimo_id(conn, "EC", ultimo_ec)

    return {
        "grupos_pe": len(grupos_pe), "grupos_ec": len(grupos_ec),
        "matches_pl_ec": len(matches_pl), "mensaje": mensaje, "enviado": enviado,
    }


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT)""")
    conn.execute("INSERT INTO noticias_fuentes VALUES (1,'PE','Medio A','Coyuntura Politica',1)")
    conn.execute("INSERT INTO noticias_fuentes VALUES (2,'PE','Medio B','Coyuntura Politica',1)")
    conn.execute("INSERT INTO noticias_fuentes VALUES (3,'PE','Blog de cocina','Temas Salud',1)")
    conn.execute("INSERT INTO noticias_fuentes VALUES (4,'PE','MINSA','Temas Salud',1)")
    filas = [
        # Titulares reales (verificados en vivo 2026-09-17, mismo evento -
        # la ratificacion de Julio Velarde en el BCRP - cubierto por
        # distintos medios el mismo dia).
        (1, 1, "Pleno del Senado aprueba ratificación de Julio Velarde como presidente del BCRP", "http://a/1", None),
        (2, 2, "Julio Velarde es ratificado como presidente del BCR por el Pleno del Senado", "http://a/2", None),
        (3, 3, "Receta de ceviche para el verano", "http://a/3", None),
        # Relleno: con un corpus de solo 2 documentos relevantes el TF-IDF
        # no discrimina bien (cada palabra aparece en 1 de 2 docs, IDF
        # degenerado - mismo problema real que en noticias/avances_ec.py).
        # Con mas notas de vocabulario distinto, "Velarde"/"BCRP"/"Senado"
        # (compartidas) pesan menos que las palabras propias de cada nota -
        # igual que se verifico en vivo contra el corpus real de produccion.
        (4, 1, "Ejecutivo presenta proyecto de ley de reforma tributaria", "http://a/4", None),
        (5, 2, "El presidente del Consejo de Ministros anuncia nuevo gabinete", "http://a/5", None),
        (6, 1, "La presidenta encabeza ceremonia por el Día de la Bandera", "http://a/6", None),
        (7, 2, "El ministro de Economía presenta el presupuesto 2027 al Congreso", "http://a/7", None),
        # Caso real 2026-09-17: texto administrativo de tramite interno que
        # menciona "Decreto Legislativo" de pasada y clasifica (mal, para
        # este proposito) como Coyuntura política - tags='normas' lo saca.
        (8, 4, "CONCEDER licencia sin goce de haber a la servidora bajo el "
               "Decreto Legislativo N° 1057, como Asistente Administrativa",
         "http://a/8", "normas"),
        # Caso real 2026-09-17 (Nicolas: "todo lo que es salud lo cataloga
        # como si si, pero no nos interesa todo salud en general... en agro
        # igual"): clasificar() etiqueta esto ["Coyuntura política","Salud"]
        # a la vez porque menciona "ministro" - es una noticia de Salud
        # generica, no coyuntura real, y no debe colar en el digest general.
        (9, 4, "Ministro de Salud anuncia nueva campaña de vacunación contra el sarampión",
         "http://a/9", None),
    ]
    conn.executemany("INSERT INTO noticias (id, fuente_id, titulo, resumen, url, tags) "
                     "VALUES (?, ?, ?, NULL, ?, ?)", filas)

    grupos, ultimo = armar_grupos(conn, "PE")
    assert ultimo == 9, ultimo
    assert not any(n["id"] == 8 for g in grupos for n in g), \
        "el item tags='normas' no deberia colarse pese a clasificar como Coyuntura política"
    assert not any(n["id"] == 9 for g in grupos for n in g), \
        "una noticia de Salud/Crop generica no debe colar solo por co-tagear Coyuntura política"
    # Las 2 notas sobre Velarde se agrupan en 1; el resto (relleno + receta,
    # que no es relevante) quedan como grupos propios de 1 sola nota.
    grupo_velarde = next(g for g in grupos if len(g) > 1)
    assert len(grupo_velarde) == 2, grupo_velarde
    assert {n["id"] for n in grupo_velarde} == {1, 2}
    grupos = [grupo_velarde] + [g for g in grupos if g is not grupo_velarde]

    msg = formatear_mensaje(grupos, [])
    assert "*PERÚ*" in msg and "*ECUADOR*" not in msg
    assert "Pleno del Senado aprueba ratificación de Julio Velarde" in msg
    assert "Medio B" in msg  # la fuente adicional queda anotada

    # Sin nada relevante -> mensaje vacio, no se manda nada.
    assert formatear_mensaje([], []) == ""

    # El estado avanza y no re-trae lo ya visto.
    _guardar_ultimo_id(conn, "PE", ultimo)
    grupos2, ultimo2 = armar_grupos(conn, "PE")
    assert grupos2 == [] and ultimo2 == ultimo

    print("OK digest: agrupa notas del mismo evento y no repite lo ya visto")


def _test_matches_pl_ec():
    """Caso real verificado en vivo 2026-09-13 (ver clientes/matrices.py):
    una noticia sobre el INIAP matchea el PL trackeado por sigla, aunque
    la noticia no sea "Coyuntura política" (no pasa por _es_relevante) -
    y aparece en su propia seccion del mensaje de WhatsApp."""
    from unittest.mock import patch

    import noticias.digest as dg

    trackeados = [{"pl_numero": "473129", "titulo_matriz":
                   "Proyecto de ley reformatoria a la Ley Constitutiva del INIAP",
                   "clientes": ["bayer", "syngenta"]}]
    vistas = [
        {"id": 1, "titulo": "ECUADOR: Comisión aprueba informe para reformar la Ley del INIAP",
         "resumen": None, "url": "http://x/1", "fuente": "Medio X", "tags": None},
        # 2do articulo sobre el MISMO PL, otro medio - debe agruparse con el
        # primero (bug real 2026-09-19: sin agrupar, 34 noticias reales de
        # apenas ~5 PL distintos inundaban el mensaje de WhatsApp).
        {"id": 2, "titulo": "Pleno tramitó en primer debate la normativa para modernizar el INIAP",
         "resumen": None, "url": "http://x/2", "fuente": "Medio Z", "tags": None},
        {"id": 3, "titulo": "Presidenta Fujimori entrega ayuda humanitaria a población de Purús",
         "resumen": None, "url": "http://x/3", "fuente": "Medio Y", "tags": None},
    ]
    with patch("clientes.matrices.pls_trackeados_ec", lambda: trackeados):
        matches = dg._matches_pl_ec(vistas)
    assert len(matches) == 1, matches  # los 2 articulos de INIAP se agrupan en 1
    assert matches[0]["id"] == 1, matches  # se queda con el primero visto como representante
    assert matches[0]["n_articulos"] == 2, matches
    assert matches[0]["pl_titulo"] == trackeados[0]["titulo_matriz"]

    msg = dg.formatear_mensaje([], [], matches)
    assert "*PL DE INTERÉS (ECUADOR)*" in msg
    assert "INIAP" in msg
    assert "+1 más" in msg
    assert "bayer/syngenta" in msg

    # Sin matches, esta seccion no aparece (y sin nada mas, mensaje vacio).
    assert dg.formatear_mensaje([], [], []) == ""
    print("OK digest: matchea PL trackeado (INIAP) fuera del filtro de Coyuntura política")


if __name__ == "__main__":
    _demo()
    _test_matches_pl_ec()
