"""Monitor de TV: lee los subtitulos automaticos de YouTube de los programas
(transmisiones ya terminadas y videos subidos) de los canales de noticias
PE/EC y guarda los fragmentos donde se menciona a una autoridad o un tema
que seguimos. Pedido de Nicolas 2026-09-28: "que sea como un tracker de TV,
cuando escucha algo de valor, lo transcribe".

Por que subtitulos y no Whisper: YouTube genera subtitulos en español de
cada transmision minutos despues de que termina (verificado con "Al Dia con
Willax" del mismo dia, 3 h). Leerlos es un request de texto por video; pasar
Whisper por 17 canales todo el dia no entra en GitHub Actions.
ponytail: no es en vivo - un programa aparece recien cuando termina y YouTube
publica sus subtitulos. En vivo de verdad = Whisper continuo sobre 1-2
canales clave (mismo camino que vigilar-congreso.yml), si hace falta.

Uso: python -m noticias.tv_monitor escanear DB_PATH
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from noticias.videos import AUTORIDADES

log = logging.getLogger(__name__)

# (nombre, url del canal). Resueltos por busqueda de canales de YouTube
# 2026-09-28. Canal N no aparece como canal propio en YouTube.
CANALES: dict[str, list[tuple[str, str]]] = {
    "PE": [
        ("RPP Noticias", "https://www.youtube.com/@RPPNoticias"),
        ("Epicentro TV", "https://www.youtube.com/@EpicentroTV"),
        ("Willax", "https://www.youtube.com/@WillaxTV"),
        ("América Noticias", "https://www.youtube.com/channel/UCPhm2I2wk4vqjENwhn3px8A"),
        ("Latina Noticias", "https://www.youtube.com/channel/UCpSJ5fGhmAME9Kx2D3ZvN3Q"),
        ("Panamericana Noticias", "https://www.youtube.com/channel/UCOyD-kV3zB8Cm4LI4qtd9tA"),
        ("Exitosa Noticias", "https://www.youtube.com/channel/UCxgO_rak_BKZP8VNVmYqbWg"),
        ("TVPerú Noticias", "https://www.youtube.com/channel/UCkZCoc42IipR1ucqJmIehsA"),
        ("ATV Noticias", "https://www.youtube.com/channel/UCYG5uXS3xdsoaXIxum1pAEw"),
    ],
    "EC": [
        ("Ecuavisa", "https://www.youtube.com/channel/UCRUV3nUNSc-xpBrTwQOCQQg"),
        ("Teleamazonas", "https://www.youtube.com/channel/UCCwRtme3lumNRQXMO2EvCvw"),
        ("TC Televisión", "https://www.youtube.com/channel/UCMDsWeFwRQ5BRzNLFzpc-ew"),
        ("Radio Pichincha", "https://www.youtube.com/channel/UCK0WHZbs_ZJ4r7DMuft7p-g"),
        ("Radio Centro", "https://www.youtube.com/channel/UCA_UqlgBTc824rRCLv6J_xA"),
        ("El Universo", "https://www.youtube.com/channel/UCLwBAR1YA6bQRNVCLYOM6Sg"),
        ("Diario Expreso", "https://www.youtube.com/channel/UCtAaSHcfws-hQzg98XEQYvw"),
        ("RTS", "https://www.youtube.com/channel/UCbJlOuKPXNgdSk4CjEgqvjA"),
    ],
}

# Temas de clientes (Bayer, Syngenta, Google, Incode) que vale la pena
# escuchar aunque no hable una autoridad de la lista. Frases, no palabras
# sueltas: "salud" o "agro" solos saltan en cualquier noticiero.
TERMINOS = [
    "facultades legislativas", "delegacion de facultades",
    "midagri", "senasa", "digemid", "minsa", "essalud", "agrocalidad", "arcsa",
    "plaguicida", "pesticida", "agroquimico", "glifosato", "transgenico",
    # "semillas" suelta saltaba en un segmento de maquillaje (Teleamazonas)
    "ley de semillas", "semilla certificada", "semillas certificadas", "semillas mejoradas",
    "sanidad agraria", "inocuidad", "medicamentos", "vacuna",
    "datos personales", "inteligencia artificial", "biometri", "identidad digital",
    "ciberseguridad", "lavado de activos", "open finance", "fintech",
    "fenomeno el nino", "fenomeno del nino",
]

POR_CANAL = 6          # ultimos N de /streams y de /videos por canal
NUEVOS_MAX = 40        # videos a leer por corrida (cada uno = 2 requests a YouTube)
DURACION_MIN = 300     # programas y entrevistas, no clips
VENTANA_SEG = 25       # contexto a cada lado de la mencion
DIAS_MAX = 7           # programas mas viejos no se procesan

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS tv_vistos (
      video_id TEXT PRIMARY KEY, pais TEXT, canal TEXT, titulo TEXT,
      duracion_seg INTEGER, n_menciones INTEGER, texto TEXT, first_seen_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS tv_menciones (
      video_id TEXT, t_seg INTEGER, pais TEXT, canal TEXT, titulo TEXT,
      terminos TEXT, fragmento TEXT, first_seen_at TEXT,
      PRIMARY KEY (video_id, t_seg))""",
    # Avisos de WhatsApp ya enviados: para no repetir la misma historia
    # contada por otro canal (noticias/historias.ya_avisado).
    """CREATE TABLE IF NOT EXISTS tv_avisos (
      ts TEXT, canal TEXT, video_id TEXT, que TEXT, PRIMARY KEY (ts, video_id))""",
]


def _norm(s: str | None) -> str:
    from congreso_live.detector import _norm as n
    return n(s)


# Se nombran en casi todos los programas (451 menciones de Keiko en 37
# programas, primera corrida 2026-09-28): solas no dicen nada, solo cuentan
# junto a un tema de clientes o un ministro.
CONTEXTO = {"Keiko Fujimori", "Luis Galarreta", "Daniel Noboa"}
# Apellidos que tambien son palabras o nombres comunes ("Cuba" el pais,
# "Valencia", "Espa" contra otras palabras en subtitulos): exigen nombre
# completo o el cargo delante.
AMBIGUOS = {"cuba", "valencia", "espa", "luque", "dyer"}


def _patrones() -> list[tuple[str, re.Pattern]]:
    """(etiqueta, regex). Autoridades por apellido (los subtitulos suelen
    decir "el ministro Vinelli"), temas por frase."""
    pats = []
    for lista in AUTORIDADES.values():
        for nombre, _ in lista:
            ap = _norm(nombre.split()[-1])
            if ap in AMBIGUOS:
                rx = r"\b(" + re.escape(_norm(nombre)) + r"|(ministr[oa]|canciller) " + re.escape(ap) + r")\b"
            else:
                # los subtitulos automaticos simplifican letras dobles ("Vineli")
                rx = re.sub(r"(\w)\1", r"\1{1,2}", re.escape(ap))
                # y confunden b/v ("Novoa" por Noboa)
                rx = r"\b" + re.sub(r"[bv]", "[bv]", rx) + r"\b"
            pats.append((nombre, re.compile(rx)))
    for t in TERMINOS:
        pats.append((t, re.compile(r"\b" + re.escape(t))))
    return pats


def terminos_de(texto: str) -> list[str]:
    n = _norm(texto)
    return sorted({etiqueta for etiqueta, p in _patrones() if p.search(n)})


def relevante(terminos: list[str]) -> bool:
    return any(t not in CONTEXTO for t in terminos)


def parse_json3(data: dict) -> list[tuple[float, str]]:
    """Subtitulos json3 de YouTube -> [(segundo, texto)]."""
    out = []
    for ev in data.get("events") or []:
        txt = "".join(s.get("utf8", "") for s in ev.get("segs") or []).strip()
        if txt:
            out.append((ev.get("tStartMs", 0) / 1000, txt.replace("\n", " ")))
    return out


def buscar_menciones(lineas: list[tuple[float, str]]) -> list[dict]:
    """Fragmentos de ~50 s alrededor de cada mencion; menciones a menos de
    VENTANA_SEG de la anterior se juntan en el mismo fragmento."""
    pats = _patrones()
    hits: list[tuple[float, str]] = []
    for t, txt in lineas:
        n = _norm(txt)
        for etiqueta, p in pats:
            if p.search(n):
                hits.append((t, etiqueta))
    grupos: list[dict] = []
    for t, etiqueta in sorted(hits):
        if grupos and t - grupos[-1]["fin"] <= VENTANA_SEG:
            grupos[-1]["fin"] = t
            grupos[-1]["terminos"].add(etiqueta)
        else:
            grupos.append({"ini": t, "fin": t, "terminos": {etiqueta}})
    salida, vistos = [], set()
    for g in grupos:
        if not relevante(g["terminos"]):
            continue
        a, b = g["ini"] - VENTANA_SEG, g["fin"] + VENTANA_SEG
        frag = " ".join(txt for t, txt in lineas if a <= t <= b)
        # Publicidad que se repite en el programa (ej. la promo de "El After"
        # de Teleamazonas nombra la IA cada tanda): mismo texto, una sola vez.
        huella = " ".join(_norm(frag).split()[5:25])
        if huella in vistos:
            continue
        vistos.add(huella)
        salida.append({"t_seg": int(max(a, 0)), "terminos": sorted(g["terminos"]), "fragmento": frag})
    return salida


def _subtitulos(video_id: str) -> tuple[list[tuple[float, str]] | None, dict]:
    """(lineas, info). lineas None = todavia no hay subtitulos en español."""
    from congreso_live.detector import _ydl
    with _ydl({}) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        caps = info.get("automatic_captions") or {}
        pistas = caps.get("es-orig") or caps.get("es") or (info.get("subtitles") or {}).get("es")
        if not pistas:
            return None, info
        url = next((p["url"] for p in pistas if p.get("ext") == "json3"), None)
        if not url:
            return None, info
        data = json.loads(ydl.urlopen(url).read().decode("utf-8"))
    return parse_json3(data), info


def _candidatos() -> list[dict]:
    from congreso_live.detector import _ydl
    out = []
    for pais, canales in CANALES.items():
        for canal, url in canales:
            for tab in ("streams", "videos"):
                try:
                    with _ydl({"extract_flat": True, "playlistend": POR_CANAL,
                               "extractor_args": {"youtube": {"lang": ["es"]}}}) as ydl:
                        info = ydl.extract_info(f"{url}/{tab}", download=False)
                except Exception as e:
                    log.warning("no pude listar %s/%s: %s", canal, tab, e)
                    continue
                for e in info.get("entries") or []:
                    if (e.get("id") and e.get("live_status") not in ("is_live", "is_upcoming")
                            and (e.get("duration") or 0) >= DURACION_MIN):
                        out.append({"id": e["id"], "pais": pais, "canal": canal,
                                    "titulo": e.get("title") or "", "duracion": e.get("duration")})
    return out


def escanear(db_path: str | Path, max_n: int = NUEVOS_MAX) -> dict:
    conn = sqlite3.connect(str(db_path))
    for s in SCHEMA:
        conn.execute(s)
    ya = {r[0] for r in conn.execute("SELECT video_id FROM tv_vistos")}
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pend = [c for c in _candidatos() if c["id"] not in ya]
    # Intercalar paises: con el tope por corrida, Peru (primero en CANALES)
    # se comia todo y Ecuador no entraba (primera corrida 2026-09-28).
    por_pais = [[c for c in pend if c["pais"] == p] for p in CANALES]
    nuevos = [c for tanda in __import__("itertools").zip_longest(*por_pais) for c in tanda if c][:max_n]
    res = {"leidos": 0, "sin_subtitulos": 0, "menciones": 0}
    for c in nuevos:
        try:
            lineas, _info = _subtitulos(c["id"])
        except Exception as e:
            log.warning("subtitulos de %s fallaron: %s", c["id"], e)
            continue
        if lineas is None:
            # Recien termino y YouTube no genero los subtitulos: no se marca
            # como visto, la proxima corrida lo reintenta.
            res["sin_subtitulos"] += 1
            continue
        # Los canales dejan transmisiones viejas en /streams (ej. la
        # juramentacion del gabinete de julio entro el 2026-09-28): lo subido
        # hace mas de DIAS_MAX se marca visto sin menciones.
        subido = _info.get("timestamp") or _info.get("release_timestamp")
        viejo = bool(subido) and (datetime.now(timezone.utc).timestamp() - subido) > DIAS_MAX * 86400
        menciones = [] if viejo else buscar_menciones(lineas)
        texto = "\n".join(txt for _, txt in lineas) if menciones else None
        conn.execute("INSERT OR REPLACE INTO tv_vistos VALUES (?,?,?,?,?,?,?,?)",
                     (c["id"], c["pais"], c["canal"], c["titulo"], c["duracion"],
                      len(menciones), texto, ahora))
        for m in menciones:
            conn.execute("INSERT OR IGNORE INTO tv_menciones VALUES (?,?,?,?,?,?,?,?)",
                         (c["id"], m["t_seg"], c["pais"], c["canal"], c["titulo"],
                          ", ".join(m["terminos"]), m["fragmento"], ahora))
        conn.commit()
        res["leidos"] += 1
        res["menciones"] += len(menciones)
    conn.close()
    return res


# ---------- En vivo: escuchar el directo mientras sale al aire ----------
# Pedido de Nicolas 2026-09-28: "RPP, Canal 4, Canal N". Canal N no se puede:
# es de cable (exclusivo Movistar), sin señal publica en su web ni en YouTube.
# Mismo camino que el Congreso en vivo (congreso_live.live_transcribe):
# tramos de audio via yt-dlp + Whisper. Cada canal = un hilo.
# Canales candidatos en orden de prioridad (Nicolas: RPP, Canal 4, Willax,
# Exitosa primero). Se escuchan los MAX_VIVOS que esten transmitiendo
# noticias en ese momento (ver vivos_noticias): a las 3 pm RPP/Exitosa
# estaban en deportes y Willax en novela, mientras America, TVPeru y
# Latina tenian noticiero (2026-09-28).
PRIORIDAD = ["RPP Noticias", "América Noticias", "Willax", "Exitosa Noticias",
             "Latina Noticias", "TVPerú Noticias", "ATV Noticias", "Panamericana Noticias",
             "Epicentro TV", "Ecuavisa", "Teleamazonas", "TC Televisión", "Radio Pichincha",
             "Radio Centro", "El Universo", "Diario Expreso", "RTS"]
EN_VIVO: list[tuple[str, list[str], str]] = sorted(
    [(c, [u], p) for p, lista in CANALES.items() for c, u in lista],
    key=lambda x: PRIORIDAD.index(x[0]) if x[0] in PRIORIDAD else 99)
MAX_VIVOS = 4  # de la lista de prioridad
# Ecuador con lugar propio (pedido de Nicolas 2026-09-28): sus noticieros de
# la mañana se escuchan siempre que esten al aire, aparte de los MAX_VIVOS
# (si no, los 4 de Peru los dejaban siempre afuera). 4 + 2 = 6 canales,
# repartidos en las 3 maquinas del workflow.
EC_SIEMPRE = ["Ecuavisa", "Teleamazonas"]
N_GRUPOS = 3
# Titulos de directos que no son noticias.
NO_NOTICIAS = re.compile(r"deporte|futbol|seleccion|mundial|amor y fuego|novela|podcast|happy hour|"
                         r"after office|musica|reality|esto es guerra|cocina|farandula|magaly|"
                         r"beto a saber")  # opinion pura (primer aviso inutil, 28/09)
# Titulos que justifican escuchar fuera de las franjas (hay-vivo-interes).
TITULO_INTERES = re.compile(r"entrevista|ministr|president|premier|congreso|facultades|"
                            r"conferencia de prensa|mensaje a la nacion|asamblea")
TRAMO_SEG = 60
RECHEQUEO_SEG = 600  # RPP abre un video nuevo por programa: re-mirar /live cada 10 min


def _vivo_actual(urls: list[str]) -> dict | None:
    from congreso_live.detector import _ydl
    for u in urls:
        try:
            with _ydl({"extractor_args": {"youtube": {"lang": ["es"]}}}) as ydl:
                info = ydl.extract_info(f"{u}/live", download=False)
        except Exception:
            continue  # "The channel is not currently live" o bloqueo transitorio
        if info.get("is_live"):
            return {"id": info["id"], "titulo": info.get("title") or "",
                    "inicio": info.get("release_timestamp") or info.get("timestamp")}
    return None


def vivos_noticias(max_n: int = MAX_VIVOS) -> list[dict]:
    """Directos de noticias en este momento, en orden de PRIORIDAD."""
    out, extra = [], []
    for canal, urls, pais in EN_VIVO:
        cupo = canal in EC_SIEMPRE
        if not cupo and len(out) >= max_n:
            continue
        v = _vivo_actual(urls)
        if v and not NO_NOTICIAS.search(_norm(v["titulo"])):
            (extra if cupo else out).append({"canal": canal, "urls": urls, "pais": pais, "vivo": v})
    return out + extra


def hay_vivo_interes() -> bool:
    """Para las vueltas horarias fuera de franja: un directo de noticias cuyo
    titulo nombra a una autoridad o dice entrevista/ministro/Congreso..."""
    for v in vivos_noticias(max_n=len(EN_VIVO)):
        t = _norm(v["vivo"]["titulo"])
        if TITULO_INTERES.search(t) or terminos_de(t):
            print(f"vivo de interes: {v['canal']} | {v['vivo']['titulo'][:80]}")
            return True
    return False


# WhatsApp de menciones en vivo (Nicolas 2026-09-28: "y tambien me envia
# alertas? eso tmb habria que incluir"). Solo lo especifico: una autoridad
# que no sea contexto o un tema de cliente; lo general (El Niño, IA...)
# queda en la app. Maximo un aviso cada AVISO_CADA_SEG por programa.
NO_AVISAR = {"fenomeno del nino", "fenomeno el nino", "inteligencia artificial", "vacuna", "minsa"}
AVISO_CADA_SEG = 1200


def vale_aviso(terminos: list[str]) -> bool:
    """Solo un TEMA de cliente dispara el aviso. Un ministro nombrado solo no
    alcanza: primer aviso real (2026-09-28) fue Beto Ortiz opinando sobre
    Astudillo, que con la censura en curso sale en todos los programas.
    Nicolas: 'esa alerta es horrible, no me dice nada'."""
    nombres = {n for lista in AUTORIDADES.values() for n, _ in lista}
    return any(t not in CONTEXTO and t not in NO_AVISAR and t not in nombres for t in terminos)


SYSTEM_AVISO = (
    "Sos analista de asuntos publicos en Peru y Ecuador para una consultora cuyos clientes son "
    "Bayer (farma y agro), Syngenta (agro), Google e Incode (tecnologia, identidad digital, datos "
    "personales, KYC). Recibis un fragmento transcrito automaticamente de un programa de TV o radio "
    "en vivo. Decidi si es algo que el equipo querria saber YA: un anuncio, dato nuevo, decision o "
    "posicion concreta de una autoridad o actor directo (ministro, congresista, regulador, gremio) "
    "sobre normas, proyectos de ley, facultades, regulacion o politicas que tocan a esos clientes. "
    "NO es relevante: opinion o comentario de conductores y analistas, repeticion de noticias ya "
    "conocidas, farandula, publicidad. Responde SOLO JSON: "
    '{"relevante": true/false, "quien": "quien habla, con cargo, o vacio si no se sabe", '
    '"que": "que dijo en concreto, una oracion", "por_que": "por que importa y a que cliente, una oracion"}. '
    "Español simple, sin dos puntos como conector, sin inventar nada que no este en el fragmento."
)


def resumir_aviso(canal: str, vivo: dict, m: dict) -> dict | None:
    """Gemini (flash-lite, gratis) decide si vale avisar y arma el texto.
    None = no avisar (irrelevante o sin respuesta usable). Sin GEMINI_API_KEY
    no se avisa: un fragmento crudo es justo lo que Nicolas no quiere."""
    import json
    import os
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        prompt = (f"Canal: {canal}\nPrograma: {vivo['titulo']}\nTemas detectados: "
                  f"{', '.join(m['terminos'])}\nFragmento: {m['fragmento']}")
        resp = client.models.generate_content(
            model="gemini-3.5-flash-lite", contents=prompt,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_AVISO,
                                               response_mime_type="application/json"))
        d = json.loads(resp.text or "{}")
        if os.environ.get("TV_AVISO_DEBUG"):
            print(f"[tv-en-vivo] Gemini: {d}", flush=True)
    except Exception as e:
        print(f"[tv-en-vivo] resumen del aviso fallo: {e}", flush=True)
        return None
    return d if d.get("relevante") and d.get("que") else None


def mensaje_aviso(canal: str, vivo: dict, m: dict, r: dict) -> str:
    hora = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("America/Lima")).strftime("%H:%M")
    quien = f"{r['quien']}. " if r.get("quien") else ""
    return (f"📺 {canal} en vivo, {hora}\n{quien}{r['que']}\n{r.get('por_que', '')}\n"
            f"https://www.youtube.com/watch?v={vivo['id']}")


def guardar_tramo(conn: sqlite3.Connection, pais: str, canal: str, vivo: dict,
                  lineas: list[tuple[float, str]]) -> list[dict]:
    """Suma un tramo transcrito al video en vivo: texto acumulado en
    tv_vistos y menciones nuevas en tv_menciones. Devuelve las menciones."""
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    menciones = buscar_menciones(lineas)
    tramo = " ".join(t for _, t in lineas)
    if conn.execute("SELECT 1 FROM tv_vistos WHERE video_id=?", (vivo["id"],)).fetchone():
        conn.execute("UPDATE tv_vistos SET texto = COALESCE(texto,'') || ' ' || ?, "
                     "n_menciones = n_menciones + ? WHERE video_id=?",
                     (tramo, len(menciones), vivo["id"]))
    else:
        conn.execute("INSERT INTO tv_vistos VALUES (?,?,?,?,?,?,?,?)",
                     (vivo["id"], pais, canal, vivo["titulo"], None, len(menciones), tramo, ahora))
    for m in menciones:
        conn.execute("INSERT OR IGNORE INTO tv_menciones VALUES (?,?,?,?,?,?,?,?)",
                     (vivo["id"], m["t_seg"], pais, canal, vivo["titulo"],
                      ", ".join(m["terminos"]), m["fragmento"], ahora))
    conn.commit()
    return menciones


def _avisar_si_vale(conn, canal: str, vivo: dict, ms: list[dict], ultimo_aviso: dict,
                    pais: str = "PE") -> None:
    """WhatsApp de una mencion de cliente, resumida por Gemini, sin repetir
    historias ya avisadas (tv_avisos, ultimas 6 h) ni mas de uno cada
    AVISO_CADA_SEG por programa."""
    import time
    buena = next((m for m in ms if vale_aviso(m["terminos"])), None)
    if not buena or time.time() - ultimo_aviso.get(vivo["id"], 0) <= AVISO_CADA_SEG:
        return
    r = resumir_aviso(canal, vivo, buena)
    recientes = [q for (q,) in conn.execute(
        "SELECT que FROM tv_avisos WHERE ts >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-6 hours')")]
    from noticias.historias import ya_avisado, ya_en_prensa
    if r is None:
        print(f"[tv-en-vivo] {canal}: mencion sin valor para aviso (Gemini)", flush=True)
    elif ya_avisado(r["que"], recientes):
        print(f"[tv-en-vivo] {canal}: misma historia ya avisada, no repito", flush=True)
    elif (prensa := ya_en_prensa(r["que"], pais)):
        # La idea es captar lo que la prensa escrita todavia no publico (la TV
        # suele salir antes); si ya esta en Google News, ya lo tenemos en Noticias.
        print(f"[tv-en-vivo] {canal}: ya en prensa ({prensa[:80]}), no aviso", flush=True)
    else:
        from congreso_live.notify import enviar_whatsapp
        if enviar_whatsapp(mensaje_aviso(canal, vivo, buena, r)):
            ultimo_aviso[vivo["id"]] = time.time()
            conn.execute("INSERT OR IGNORE INTO tv_avisos VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'),?,?,?)",
                         (canal, vivo["id"], r["que"]))
            conn.commit()
            print(f"[tv-en-vivo] {canal}: aviso WhatsApp enviado", flush=True)


_LOCK_WARP = __import__("threading").Lock()


def _url_hls(video_id: str) -> str | None:
    """URL del manifiesto HLS del directo (el formato de menor calidad: solo
    necesitamos el audio y asi se baja menos)."""
    from congreso_live.detector import _ydl, es_bloqueo_bot, rotar_warp
    info = None
    for intento in (1, 2):
        try:
            with _ydl({}) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            break
        except Exception as e:
            print(f"[tv-en-vivo] no pude resolver el HLS de {video_id}: {str(e)[:120]}", flush=True)
            # "Sign in to confirm you're not a bot": depende de la IP de salida
            # de WARP (prueba del 28/09, 1 de 3 maquinas bloqueada). IP nueva y
            # un reintento, como en el monitor del Congreso. Un solo hilo rota a
            # la vez: rotar corta la conexion de los demas por unos segundos.
            if intento == 1 and es_bloqueo_bot(str(e)):
                with _LOCK_WARP:
                    rotar_warp()
                continue
            return None
    if info is None:
        return None
    hls = [f for f in info.get("formats") or [] if "m3u8" in (f.get("protocol") or "")]
    hls.sort(key=lambda f: f.get("tbr") or f.get("height") or 0)
    return hls[0]["url"] if hls else info.get("url")


def _lanzar_ffmpeg(url: str, carpeta: Path):
    """ffmpeg lee el directo sin parar y lo corta en wav de TRAMO_SEG
    segundos (16 kHz mono, lo que espera Whisper)."""
    import os
    import subprocess
    from congreso_live.live_transcribe import _ffmpeg_bin
    cmd = [str(_ffmpeg_bin()), "-hide_banner", "-loglevel", "error"]
    proxy = os.environ.get("FFMPEG_HTTP_PROXY")  # privoxy: ffmpeg no entiende socks5://
    if proxy:
        cmd += ["-http_proxy", proxy]
    cmd += ["-i", url, "-vn", "-ac", "1", "-ar", "16000", "-f", "segment",
            "-segment_time", str(TRAMO_SEG), "-reset_timestamps", "1", str(carpeta / "seg%05d.wav")]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            start_new_session=(os.name != "nt"))


def _parar(proc) -> None:
    import os
    import signal
    if proc and proc.poll() is None:
        try:
            if os.name == "nt":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()


def escuchar_canal(canal: str, urls: list[str], db_path: str | Path, hasta: float,
                   pais: str = "PE") -> dict:
    """Loop bloqueante hasta `hasta` (epoch). Captura continua: ffmpeg graba
    el directo sin parar en tramos de TRAMO_SEG y este loop transcribe los
    tramos ya cerrados en paralelo. Antes (captura y transcripcion en serie)
    se perdian ~15-20 s por minuto mientras corria Whisper (punto 2 de la
    revision de repos de monitoreo de medios, 2026-09-28)."""
    import shutil
    import tempfile
    import time
    from congreso_live.live_transcribe import transcribir_audio
    conn = sqlite3.connect(str(db_path), timeout=30)
    for s in SCHEMA:
        conn.execute(s)
    modelo, vivo, visto_en, proc, carpeta, t_ffmpeg, hechos = None, None, 0.0, None, None, 0.0, set()
    fallos_hls = 0
    res = {"tramos": 0, "menciones": 0}
    ultimo_aviso: dict[str, float] = {}
    try:
        while time.time() < hasta:
            if vivo is None or time.time() - visto_en > RECHEQUEO_SEG:
                nuevo, visto_en = _vivo_actual(urls), time.time()
                if not nuevo or not vivo or nuevo["id"] != vivo["id"]:
                    _parar(proc)
                    proc = None  # cambio de programa (RPP abre un video por programa) o termino
                vivo = nuevo
                if vivo:
                    print(f"[tv-en-vivo] {canal}: {vivo['id']} {vivo['titulo'][:70]}", flush=True)
            if not vivo:
                time.sleep(120)
                continue
            if proc is None or proc.poll() is not None:
                if proc is not None:
                    err = (proc.stderr.read() or b"").decode("utf-8", "replace")[-300:]
                    print(f"[tv-en-vivo] {canal}: ffmpeg termino ({proc.returncode}) {err}", flush=True)
                    time.sleep(30)
                url = _url_hls(vivo["id"])
                if not url:
                    # espera creciente (30 s, 1, 2, 4, 5 min): martillar a
                    # YouTube cada 30 s con la IP bloqueada solo empeora el bloqueo
                    fallos_hls += 1
                    vivo = None
                    time.sleep(min(30 * 2 ** (fallos_hls - 1), 300))
                    continue
                fallos_hls = 0
                if carpeta:
                    shutil.rmtree(carpeta, ignore_errors=True)
                carpeta, hechos = Path(tempfile.mkdtemp(prefix="tv_vivo_")), set()
                proc, t_ffmpeg = _lanzar_ffmpeg(url, carpeta), time.time()
            # Todos los tramos menos el ultimo (ffmpeg lo esta escribiendo).
            listos = sorted(carpeta.glob("seg*.wav"))[:-1]
            pendientes = [p for p in listos if p.name not in hechos]
            if not pendientes:
                time.sleep(5)
                continue
            for wav in pendientes:
                hechos.add(wav.name)
                if modelo is None:
                    from faster_whisper import WhisperModel
                    modelo = WhisperModel("small", device="cpu", compute_type="int8")
                segs = transcribir_audio(wav, modelo)
                wav.unlink(missing_ok=True)
                if not segs:
                    continue
                # inicio del tramo = arranque de ffmpeg + n * TRAMO_SEG; t_seg
                # relativo al inicio de la transmision (sirve para &t= luego).
                n = int(wav.stem.replace("seg", ""))
                base = t_ffmpeg + n * TRAMO_SEG - (vivo["inicio"] or t_ffmpeg)
                ms = guardar_tramo(conn, pais, canal, vivo, [(base + s["start"], s["text"]) for s in segs])
                res["tramos"] += 1
                res["menciones"] += len(ms)
                if ms:
                    print(f"[tv-en-vivo] {canal}: {len(ms)} mencion(es)", flush=True)
                _avisar_si_vale(conn, canal, vivo, ms, ultimo_aviso, pais)
            if len(pendientes) > 3:
                print(f"[tv-en-vivo] {canal}: {len(pendientes)} tramos en cola, Whisper no alcanza el ritmo", flush=True)
    finally:
        _parar(proc)
        if carpeta:
            shutil.rmtree(carpeta, ignore_errors=True)
        conn.close()
    return res


def en_vivo(db_path: str | Path, minutos: float, publicar_cada_min: float = 15,
            grupo: int | None = None, n_grupos: int = N_GRUPOS) -> dict:
    """Un hilo por cada directo de noticias elegido (vivos_noticias). Con
    `grupo` (1..n_grupos) cada maquina del workflow toma su parte de la
    lista. Con TV_PUBLICAR=1 publica la base en `datos` cada
    `publicar_cada_min` para que la app vea las menciones sin esperar."""
    import os
    import subprocess
    import threading
    import time
    hasta = time.time() + minutos * 60
    elegidos = vivos_noticias()
    if grupo:
        elegidos = elegidos[grupo - 1::n_grupos]
    print("[tv-en-vivo] escucho:", [e["canal"] for e in elegidos], flush=True)
    resultados: dict = {}
    hilos = [threading.Thread(target=lambda e=e: resultados.__setitem__(
                 e["canal"], escuchar_canal(e["canal"], e["urls"], db_path, hasta, e["pais"])),
             daemon=True) for e in elegidos]
    for h in hilos:
        h.start()
    while any(h.is_alive() for h in hilos):
        time.sleep(min(publicar_cada_min * 60, max(hasta - time.time(), 1)))
        if os.environ.get("TV_PUBLICAR"):
            subprocess.run(["bash", "scripts/publicar_db.sh", "base_remota", str(db_path)], check=False)
    return resultados


def _demo():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        c = sqlite3.connect(str(Path(td) / "t.db"))
        for s in SCHEMA:
            c.execute(s)
        vivo = {"id": "LIVE1", "titulo": "RPP en vivo", "inicio": 0}
        assert guardar_tramo(c, "PE", "RPP Noticias", vivo, [(10, "hola")]) == []
        ms = guardar_tramo(c, "PE", "RPP Noticias", vivo, [(70, "el ministro Vinelli y el Senasa")])
        assert len(ms) == 1 and vale_aviso(ms[0]["terminos"])  # Senasa = tema de cliente
        r = {"relevante": True, "quien": "Marco Vinelli, ministro de Agricultura",
             "que": "Anunció cambios en el Senasa.", "por_que": "Toca a Bayer y Syngenta."}
        txt = mensaje_aviso("RPP Noticias", vivo, ms[0], r)
        assert txt.startswith("📺 RPP Noticias en vivo") and "Marco Vinelli" in txt
        assert not vale_aviso(["fenomeno del nino", "Keiko Fujimori"])  # general: queda en la app
        assert not vale_aviso(["César Astudillo"])  # ministro solo: queda en la app (aviso de Beto Ortiz)
        assert c.execute("SELECT texto, n_menciones FROM tv_vistos").fetchone() == (
            "hola el ministro Vinelli y el Senasa", 1)
        c.close()
    assert buscar_menciones([(0, "el ministro Vineli dijo")])[0]["terminos"] == ["Marco Vinelli"]
    assert terminos_de("el presidente Novoa") == ["Daniel Noboa"]
    assert NO_NOTICIAS.search(_norm("EXITOSA DEPORTES ⚽ con ÓSCAR PAZ"))
    assert NO_NOTICIAS.search(_norm("Willax en vivo - AMOR Y FUEGO - 28/09/2026"))
    assert not NO_NOTICIAS.search(_norm("🔴 América Noticias - EN VIVO | 28/09/26"))
    assert EN_VIVO[0][0] == "RPP Noticias" and EN_VIVO[1][0] == "América Noticias"
    promo = "no vea el acto si quiere ver candidatos abusar de la inteligencia artificial de una manera ridicula"
    assert len(buscar_menciones([(0, promo), (300, promo), (600, promo)])) == 1
    assert not buscar_menciones([(0, "maquillaje hecho con semillas y flores")])
    lineas = [(0, "buenas noches"), (10, "hoy nos acompaña el ministro Vinelli"),
              (20, "hablamos de las facultades legislativas"), (200, "pasamos a deportes"),
              (400, "el fenómeno El Niño y el Senasa")]
    ms = buscar_menciones(lineas)
    assert len(ms) == 2, ms
    assert ms[0]["terminos"] == ["Marco Vinelli", "facultades legislativas"], ms[0]
    assert "deportes" not in ms[0]["fragmento"]
    assert ms[1]["terminos"] == ["fenomeno el nino", "senasa"], ms[1]
    assert not buscar_menciones([(0, "gol de Cueva en el minuto 90")])
    assert not buscar_menciones([(0, "la presidenta Keiko Fujimori viajo")])  # solo contexto
    assert buscar_menciones([(0, "Keiko Fujimori y el fenomeno El Niño")])
    assert not buscar_menciones([(0, "viajo a Cuba y a Valencia, mas esta diciendo")])
    assert buscar_menciones([(0, "el canciller Espa dijo")])[0]["terminos"] == ["Carlos Espá"]
    assert parse_json3({"events": [{"tStartMs": 1500, "segs": [{"utf8": "hola "}, {"utf8": "mundo"}]},
                                   {"tStartMs": 2000}]}) == [(1.5, "hola mundo")]
    print("OK tv_monitor: menciones agrupadas por cercania, sin falsos positivos, json3")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 3 and sys.argv[1] == "escanear":
        print(f"tv_monitor: {escanear(sys.argv[2])}")
    elif len(sys.argv) in (4, 5) and sys.argv[1] == "en-vivo":
        # 5to argumento opcional: grupo 1 o 2 (el workflow reparte los canales
        # en dos maquinas; 4 Whisper en una sola se atrasaban)
        grupo = int(sys.argv[4]) if len(sys.argv) == 5 else None
        print(f"tv_monitor en vivo: {en_vivo(sys.argv[2], float(sys.argv[3]), grupo=grupo)}")
    elif len(sys.argv) == 2 and sys.argv[1] == "probar-aviso":
        # Prueba real de resumir_aviso con Gemini (tv-en-vivo.yml, input prueba):
        # opinion de conductor -> no avisa; anuncio de un ministro -> avisa.
        casos = [
            ("Willax", {"id": "U8tjtLL7KkA", "titulo": "Willax en vivo - CONTRACORRIENTE - BETO A SABER"},
             "entregan la cabeza de Oscar Arreola, el comandante general de la policia. Y permiten ademas que "
             "fustiguen a ministros del interior, ahorita al borde de una censura, a 50 dias de haber empezado "
             "el gobierno, un heroe de la patria como Cesar Astudillo. Eso es absolutamente inaceptable."),
            ("TVPerú Noticias", {"id": "So8nGfsTN44", "titulo": "Aliados por la seguridad: estado de emergencia"},
             "habla el ministro de Trabajo. La preocupacion del gobierno es como le damos acceso a los derechos "
             "laborales al 70 por ciento de peruanos en la informalidad, sin vacaciones, sin CTS, sin seguro "
             "social. La idea en la delegacion de facultades es que nos permitan legislar en ese sentido. "
             "Podriamos hacerlo via proyectos de ley, pero los tiempos parlamentarios son mucho mas lentos."),
            ("RPP Noticias", {"id": "x", "titulo": "Ampliacion de Noticias"},
             "esta con nosotros el ministro de Desarrollo Agrario Marco Vinelli. Ministro, que va a cambiar? Vamos "
             "a modificar la Ley de Inocuidad de los Alimentos para regular con mas exigencia el uso de plaguicidas "
             "altamente toxicos y darle al Senasa mas facultades de control y fiscalizacion. El decreto sale este mes."),
        ]
        from noticias.historias import ya_en_prensa
        for que in ["Resolvió rechazar el pedido de facultades legislativas presentado por el gobierno "
                    "de Keiko Fujimori por considerarlo amplio y sin acreditar urgencia.",
                    "Vinelli anunció que el Senasa prohibirá tres plaguicidas altamente tóxicos desde noviembre."]:
            print(f"== ya en prensa? {que[:60]} -> {ya_en_prensa(que)}")
        for canal, vivo, frag in casos:
            m = {"terminos": terminos_de(frag) or ["delegacion de facultades"], "fragmento": frag, "t_seg": 0}
            os.environ["TV_AVISO_DEBUG"] = "1"
            r = resumir_aviso(canal, vivo, m)
            print(f"== {canal}: {'AVISA' if r else 'NO AVISA'}")
            if r:
                print(mensaje_aviso(canal, vivo, m, r))
    elif len(sys.argv) == 2 and sys.argv[1] == "hay-vivo-interes":
        sys.exit(0 if hay_vivo_interes() else 1)
    else:
        _demo()
