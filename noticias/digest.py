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
from datetime import datetime, timedelta, timezone

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from noticias.temas import FUENTES_MULTIPAIS, clasificar, es_deportivo, pais_por_contenido

UMBRAL_SIMILITUD = 0.35
MAX_GRUPOS_POR_PAIS = 12
# Bug real 2026-09-21 (Nicolas: "las noticias que envias tienen que ser
# de ese dia... no me puedes enviar una noticia de hace meses"): las
# fuentes "Google News PE/EC - <tema>" son busquedas por RELEVANCIA, no
# orden cronologico - un articulo viejo (verificado en produccion: 2017,
# 2019, 2022, 2023) puede aparecer HOY en los resultados de una busqueda
# guardada y entrar a la DB con first_seen_at=hoy aunque su fecha_pub
# real sea de hace años. El cursor del digest es por ID (nunca revisa lo
# ya visto), no por fecha - sin este chequeo, cualquier articulo asi
# pasa como si fuera noticia fresca. 2 dias de margen (no 1) para
# fin de semana/demoras de pipeline normales, no para colar contenido
# viejo.
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
    """Trae candidatos de `pais`, mas los de fuentes multi-pais (ver
    FUENTES_MULTIPAIS en noticias/temas.py) reclasificados por contenido -
    bug real 2026-09-20: "DPL News Ecuador" cubre TODO LATAM, y una
    noticia 100% peruana (renuncia de Rafael Rey, Ministro de Transportes)
    quedo archivada como si fuera de Ecuador solo porque asi esta
    catalogada la fuente, no el articulo."""
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
                     if fuente in FUENTES_MULTIPAIS else pais_fuente)
        if pais_real != pais:
            continue
        salida.append({"id": r[0], "titulo": r[1], "resumen": r[2], "url": r[3],
                        "fuente": fuente, "tags": r[5], "fecha_pub": r[7]})
    return salida


def _es_reciente(n: dict, dias: int = DIAS_FRESCURA) -> bool:
    """True si `fecha_pub` es de los ultimos `dias` dias, o si no tiene
    fecha_pub (tratado como reciente - mismo criterio ya usado en el
    resto del codigo, ej. Noticias PE/EC: COALESCE(fecha_pub,
    first_seen_at)). Ver DIAS_FRESCURA arriba para el bug real que
    motiva esto."""
    fecha_pub = n.get("fecha_pub")
    if not fecha_pub:
        return True
    try:
        fecha = datetime.fromisoformat(fecha_pub.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    return (datetime.now(timezone.utc) - fecha) <= timedelta(days=dias)


def _es_relevante(n: dict) -> bool:
    """Solo "Coyuntura política" (probado en vivo 2026-09-17 contra el
    corpus real: incluir tambien `es_normativa` inunda el digest con cada
    resolucion administrativa individual de El Peruano/Ministerio Publico
    - designaciones de fiscales, viajes en comision de servicios, etc.
    Eso ya se ve como badge "Normativa" en la app para quien lo busca; un
    canal de WhatsApp es mas caro de interrumpir que un badge, y no es lo
    que Nicolas pidio ("varias del mismo tema" se referia a cobertura de
    prensa duplicada, no a resoluciones administrativas)."""
    # tags='normas' (exacto) son resoluciones administrativas de los feeds
    # gobpe (MINSA/MIDAGRI/SENASA/MEF...) - tramite interno (licencias,
    # designaciones) que a veces dispara "Coyuntura política" en
    # clasificar() solo por mencionar "Decreto Legislativo" de pasada, no
    # por ser noticia real (verificado en vivo 2026-09-17). No se toca
    # clasificar() porque tambien lo usan las paginas Noticias PE/EC.
    #
    # Bug real encontrado 2026-09-20 (Nicolas: "matchea mal cosas que no
    # me interesan para nada"): este chequeo NUNCA agarraba las 476
    # noticias reales de `noticias/el_peruano.py`/`registro_oficial_ec.py`
    # (Diario Oficial El Peruano, Registro Oficial EC) - esos scrapers
    # taggean pipe-joined ("Coyuntura política|el-peruano|normativa"), no
    # el string exacto "normas". Resultado verificado contra la DB real:
    # decenas de resoluciones puramente administrativas (confirmaciones
    # del JNE, autorizaciones de viaje de jueces, nombramientos de
    # fiscales) inundaban el digest porque casi todas mencionan "JNE",
    # "fiscal" o "PCM" (palabras de Coyuntura política) solo por ser el
    # nombre de la entidad emisora, no por ser noticia real. Ambos
    # scrapers agregan el tag "normativa" (no "normas") a TODO lo que
    # producen - es la señal mas confiable que hay, mas confiable que
    # regex sobre el texto (`es_normativa()` de noticias/temas.py de hecho
    # tampoco agarra estos titulos: "resolución" pelado, sin calificar de
    # "ministerial"/"suprema"/etc., no esta en su lista de keywords).
    tags = (n.get("tags") or "").split("|")
    if "normas" in tags or "normativa" in tags:
        return False
    if not _es_reciente(n):
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
    if temas != ["Coyuntura política"]:
        return False
    # Bug real 2026-09-21 (Nicolas: "0 relevantes" en una alerta real) -
    # "presidente"/"presidenta" (Coyuntura política) matchea igual al
    # presidente de un club de futbol que al de la Republica. Verificado
    # contra produccion: 7 de 9 items de una alerta EC real eran
    # resultados/dirigencia de Liga Ecuabet (Barcelona SC, Emelec) colados
    # solo por mencionar a su presidente. Ver es_deportivo() en temas.py.
    return not es_deportivo(n["titulo"], n["resumen"])


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
    # Mismo tope que armar_grupos - mas recientes primero (por id de la
    # noticia representante de cada PL).
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
    # Bug real 2026-09-21 (Nicolas: "las alertas... a veces se mandan
    # incompletas por los tamaños largos de los links"): las URLs de
    # Google News (la fuente mas comun aca) llegan a pesar 500-700+
    # caracteres - con varias por mensaje se comian buena parte de
    # MENSAJE_MAX_CHARS y el resto se recortaba. Ver acortar_url().
    linea += f"\n  {acortar_url(principal['url'])}"
    return linea


# CallMeBot manda el mensaje via GET (la URL entera lleva el texto
# codificado como query param) - bug real 2026-09-19: la primera corrida
# real de este digest (backlog acumulado desde el 17/09 por el bug de
# sklearn de mas abajo) armo un mensaje de 13000+ caracteres y CallMeBot
# lo rechazo con "414 Request-URI Too Large" - fallo TOTAL, no se mando
# nada. MENSAJE_MAX_CHARS es el limite seguro por mensaje individual.
#
# Bug real 2026-09-21 (Nicolas: "recorta las alertas... si se va a
# cortar, envia mas de un mensaje"): el fix anterior recortaba duro al
# limite y perdia todo lo que sobraba. Ahora formatear_mensajes() reparte
# el contenido en varios mensajes de WhatsApp en vez de truncar - nunca
# se pierde una noticia.
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
    # Mismo lote de noticias EC nuevas que armar_grupos ya leyo (antes de
    # avanzar el estado abajo) - re-consultado aca porque el match de PL
    # NO pasa por el filtro _es_relevante (ver _matches_pl_ec).
    vistas_ec = _noticias_desde(conn, "EC", _ultimo_id(conn, "EC"))
    matches_pl = _matches_pl_ec(vistas_ec)
    mensajes = formatear_mensajes(grupos_pe, grupos_ec, matches_pl)
    # Bug real 2026-09-20 (Nicolas: "a veces no me dice nada, o sea me
    # llega sin ningun update"): antes esta funcion solo mandaba WhatsApp
    # cuando habia algo relevante - silencio total el resto de las veces,
    # indistinguible de un pipeline roto. Ahora que refrescar-pe.yml solo
    # llama a esto 2 veces al dia (9am/2pm Lima, horarios fijos - ver el
    # `if` de ese workflow), "sin novedades" es una respuesta explicita y
    # esperada en vez de silencio ambiguo.
    if not mensajes:
        mensajes = ["📰 Sin noticias relevantes nuevas desde el último chequeo."]

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


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT, fecha_pub TEXT)""")
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
        # Bug real 2026-09-20: titulo real de El Peruano, tags pipe-joined
        # como los produce noticias/el_peruano.py de verdad - "JNE"/"fiscal"
        # disparan Coyuntura política, y el viejo chequeo tags=="normas"
        # (exacto) nunca los agarraba porque el formato real es distinto.
        (10, 1, "JURADO NACIONAL DE ELECCIONES — RESOLUCIÓN N° 3255-2026-JNE: "
                "Confirman la Resolución Nº 00424-2026-JEE-HYLS/JNE",
         "http://a/10", "Coyuntura política|el-peruano|normativa"),
        # Bug real 2026-09-21 (Nicolas: "0 relevantes" en una alerta real):
        # "presidente de club" clasifica igual que "presidente de la
        # Republica" - caso real, Liga Ecuabet/Barcelona SC.
        (11, 1, "Miguel Montalvo, presidente de Barcelona SC, evalúa el "
                "cambio del club a sociedad anónima", "http://a/11", None),
    ]
    conn.executemany("INSERT INTO noticias (id, fuente_id, titulo, resumen, url, tags) "
                     "VALUES (?, ?, ?, NULL, ?, ?)", filas)

    grupos, ultimo = armar_grupos(conn, "PE")
    assert ultimo == 11, ultimo
    assert not any(n["id"] == 8 for g in grupos for n in g), \
        "el item tags='normas' no deberia colarse pese a clasificar como Coyuntura política"
    assert not any(n["id"] == 9 for g in grupos for n in g), \
        "una noticia de Salud/Crop generica no debe colar solo por co-tagear Coyuntura política"
    assert not any(n["id"] == 11 for g in grupos for n in g), \
        "un presidente de club de futbol no debe colar como Coyuntura política"
    assert not any(n["id"] == 10 for g in grupos for n in g), \
        "una resolucion administrativa de El Peruano (tags pipe-joined con "\
        "'normativa') no deberia colarse - bug real 2026-09-20"
    # Las 2 notas sobre Velarde se agrupan en 1; el resto (relleno + receta,
    # que no es relevante) quedan como grupos propios de 1 sola nota.
    grupo_velarde = next(g for g in grupos if len(g) > 1)
    assert len(grupo_velarde) == 2, grupo_velarde
    assert {n["id"] for n in grupo_velarde} == {1, 2}
    grupos = [grupo_velarde] + [g for g in grupos if g is not grupo_velarde]

    mensajes = formatear_mensajes(grupos, [])
    assert len(mensajes) == 1
    msg = mensajes[0]
    assert "*PERÚ*" in msg and "*ECUADOR*" not in msg
    assert "Pleno del Senado aprueba ratificación de Julio Velarde" in msg
    assert "Medio B" in msg  # la fuente adicional queda anotada

    # Sin nada relevante -> sin mensajes, no se manda nada.
    assert formatear_mensajes([], []) == []

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

    mensajes = dg.formatear_mensajes([], [], matches)
    assert len(mensajes) == 1
    msg = mensajes[0]
    assert "*PL DE INTERÉS (ECUADOR)*" in msg
    assert "INIAP" in msg
    assert "+1 más" in msg
    assert "bayer/syngenta" in msg

    # Sin matches, esta seccion no aparece (y sin nada mas, sin mensajes).
    assert dg.formatear_mensajes([], [], []) == []
    print("OK digest: matchea PL trackeado (INIAP) fuera del filtro de Coyuntura política")


def _test_pais_multipais():
    """Caso real 2026-09-20: 'DPL News Ecuador' cubre todo LATAM y estaba
    catalogada con pais='EC' - una noticia 100% peruana (Rafael Rey deja
    el MTC) quedaba archivada como si fuera de Ecuador y nunca llegaba al
    digest de Peru. `_noticias_desde` ahora reclasifica por contenido las
    fuentes de FUENTES_MULTIPAIS."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT, fecha_pub TEXT)""")
    conn.execute("INSERT INTO noticias_fuentes VALUES (1,'EC','DPL News Ecuador','Temas KYC/AML',1)")
    conn.execute("INSERT INTO noticias_fuentes VALUES (2,'EC','El Universo','Coyuntura Politica',1)")
    filas = [
        # Real (titulo real, DPL News Ecuador, catalogada pais='EC') - debe
        # aparecer en el stream de PE, no en el de EC.
        (1, 1, "Rafael Rey deja el Ministerio de Transportes y Comunicaciones de Perú", None, "http://a/1", None),
        # Real de Ecuador, misma fuente multi-pais - debe seguir en EC.
        (2, 1, "Ecuador: Fiscalía pidió vincular a la esposa de Aquiles Álvarez al caso Goleada", None, "http://a/2", None),
        # Fuente normal (no multi-pais), sin cambios de comportamiento.
        (3, 2, "Daniel Noboa llega a Estados Unidos para participar en la Asamblea General de la ONU", None, "http://a/3", None),
    ]
    conn.executemany("INSERT INTO noticias (id, fuente_id, titulo, resumen, url, tags) "
                     "VALUES (?, ?, ?, ?, ?, ?)", filas)

    vistas_pe = _noticias_desde(conn, "PE", 0)
    vistas_ec = _noticias_desde(conn, "EC", 0)
    assert {n["id"] for n in vistas_pe} == {1}, vistas_pe
    assert {n["id"] for n in vistas_ec} == {2, 3}, vistas_ec
    print("OK digest: reclasifica por contenido las fuentes multi-pais (caso real Rafael Rey/DPL)")


def _test_run_manda_sin_novedades_si_no_hay_nada():
    """Bug real 2026-09-20 (Nicolas: "a veces no me dice nada, o sea me
    llega sin ningun update"): con el digest corriendo solo 2x/dia ahora
    (9am/2pm Lima, gateado en refrescar-pe.yml), silencio total es
    indistinguible de un pipeline roto - run() debe mandar algo SIEMPRE."""
    from unittest.mock import patch

    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT, fecha_pub TEXT)""")
    enviados = []
    with patch("congreso_live.notify.enviar_whatsapp", lambda msg: enviados.append(msg) or True), \
         patch("clientes.matrices.pls_trackeados_ec", lambda: []):
        resultado = run(conn)
    assert len(enviados) == 1, "debe enviar aunque no haya nada relevante"
    assert "Sin noticias relevantes" in enviados[0]
    assert resultado["enviado"] is True
    print("OK digest: run() manda 'sin novedades' en vez de quedarse en silencio")


def _test_formatear_grupo_acorta_urls_largas():
    """Bug real 2026-09-21 (Nicolas: "las alertas... a veces se mandan
    incompletas por los tamaños largos de los links"): URLs de Google
    News reales llegan a pesar 500-700+ caracteres - _formatear_grupo()
    y _formatear_match_pl() deben acortarlas via congreso_live.notify."""
    from unittest.mock import patch

    larga = "https://news.google.com/rss/articles/" + "A" * 500
    with patch("congreso_live.notify.acortar_url", lambda u: "https://tinyurl.com/xyz"):
        linea = _formatear_grupo([{"titulo": "Un titulo", "fuente": "Medio",
                                    "url": larga}])
        assert "https://tinyurl.com/xyz" in linea
        assert larga not in linea

        linea_pl = _formatear_match_pl({"titulo": "Nota", "pl_titulo": "PL X",
                                         "url": larga, "clientes": ["bayer"]})
        assert "https://tinyurl.com/xyz" in linea_pl
        assert larga not in linea_pl
    print("OK digest: _formatear_grupo/_formatear_match_pl acortan URLs largas")


def _test_formatear_mensajes_parte_en_varios():
    """Bug real 2026-09-21 (Nicolas: "recorta las alertas... si se va a
    cortar, envia mas de un mensaje"): un backlog grande no debe
    truncarse - se reparte en varios mensajes de WhatsApp numerados, sin
    perder ninguna noticia."""
    grupos_ec = [
        [{"titulo": f"Noticia de prueba numero {i} con un titulo bastante "
                    "largo para simular contenido real de produccion",
          "fuente": "Medio X", "url": f"http://x/{i}"}]
        for i in range(30)
    ]
    mensajes = formatear_mensajes([], grupos_ec)
    assert len(mensajes) > 1, "un backlog grande debe partirse en varios mensajes"
    for i, m in enumerate(mensajes, 1):
        assert len(m) <= MENSAJE_MAX_CHARS + 150, \
            f"mensaje {i} se fue muy por encima del limite: {len(m)} chars"
        assert f"({i}/{len(mensajes)})" in m
    # Ninguna noticia se pierde - los 30 titulos aparecen en algun mensaje.
    todo = "\n".join(mensajes)
    for i in range(30):
        assert f"Noticia de prueba numero {i} " in todo, f"se perdio la noticia {i}"
    print("OK digest: formatear_mensajes reparte backlogs grandes sin perder contenido")


def _test_ignora_noticias_viejas():
    """Bug real 2026-09-21 (Nicolas: "las noticias que envias tienen que
    ser de ese dia... no me puedes enviar una noticia de hace meses"):
    verificado contra produccion, 123 articulos con fecha_pub de hace
    meses/años (2017, 2019, 2022, 2023) entraron a la DB como "nuevos"
    (first_seen_at reciente) via fuentes "Google News - <tema>" (buscan
    por relevancia, no cronologia) y pasaban el filtro de tema."""
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    conn.execute("""CREATE TABLE noticias_fuentes (id INTEGER PRIMARY KEY,
        pais TEXT, nombre TEXT, categoria TEXT, activa INTEGER DEFAULT 1)""")
    conn.execute("""CREATE TABLE noticias (id INTEGER PRIMARY KEY,
        fuente_id INTEGER, titulo TEXT, resumen TEXT, url TEXT, tags TEXT, fecha_pub TEXT)""")
    conn.execute("INSERT INTO noticias_fuentes VALUES (1,'EC','Google News EC','Coyuntura Politica',1)")
    filas = [
        # Caso real (parafraseado): articulo de 2017 sobre Odebrecht,
        # detectado HOY por una busqueda guardada de Google News - tema
        # real (menciona "Congreso"), pero la noticia NO es de hoy.
        (1, 1, "El Congreso de Ecuador debate el caso Odebrecht en sesion plenaria",
         None, "http://x/1", None, "2017-09-05T07:00:00Z"),
        # Contraste: mismo tema, pero realmente de hoy - debe pasar.
        (2, 1, "El Congreso aprueba en el Pleno la nueva ley de emergencia",
         None, "http://x/2", None, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        # Sin fecha_pub (NULL) - se trata como reciente (mismo criterio
        # que el resto del codigo, COALESCE con first_seen_at).
        (3, 1, "El presidente encabeza reunion de gabinete en el Congreso",
         None, "http://x/3", None, None),
    ]
    conn.executemany("INSERT INTO noticias (id, fuente_id, titulo, resumen, url, tags, fecha_pub) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)", filas)

    grupos, ultimo = armar_grupos(conn, "EC")
    assert ultimo == 3, ultimo
    ids_incluidos = {n["id"] for g in grupos for n in g}
    assert 1 not in ids_incluidos, "un articulo de 2017 no debe colar como noticia de hoy"
    assert 2 in ids_incluidos, "una noticia real de hoy si debe pasar"
    assert 3 in ids_incluidos, "sin fecha_pub se trata como reciente, no se excluye"
    print("OK digest: ignora noticias con fecha_pub vieja (busquedas de Google News no son cronologicas)")


if __name__ == "__main__":
    _demo()
    _test_matches_pl_ec()
    _test_pais_multipais()
    _test_run_manda_sin_novedades_si_no_hay_nada()
    _test_formatear_grupo_acorta_urls_largas()
    _test_formatear_mensajes_parte_en_varios()
    _test_ignora_noticias_viejas()
