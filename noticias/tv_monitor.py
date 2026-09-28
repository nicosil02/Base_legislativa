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
                         r"after office|musica|reality|esto es guerra|cocina|farandula|magaly")
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
    return any(t not in CONTEXTO and t not in NO_AVISAR for t in terminos)


def mensaje_aviso(canal: str, vivo: dict, m: dict) -> str:
    hora = datetime.now(timezone.utc).astimezone(__import__("zoneinfo").ZoneInfo("America/Lima")).strftime("%H:%M")
    frag = m["fragmento"] if len(m["fragmento"]) <= 400 else m["fragmento"][:400] + "…"
    return (f"📺 En vivo · {canal} · {hora}\n{vivo['titulo'][:90]}\n"
            f"Menciona: {', '.join(m['terminos'])}\n«{frag}»\n"
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


def escuchar_canal(canal: str, urls: list[str], db_path: str | Path, hasta: float,
                   pais: str = "PE") -> dict:
    """Loop bloqueante hasta `hasta` (epoch): captura TRAMO_SEG de audio del
    directo, lo transcribe y guarda menciones.
    ponytail: captura y transcripcion van en serie, asi que entre tramos se
    pierden los ~15-20 s que tarda Whisper; con un hilo capturando y otro
    transcribiendo no se perderia nada, si hiciera falta."""
    import time
    from congreso_live.live_transcribe import capturar_audio_en_vivo, transcribir_audio
    conn = sqlite3.connect(str(db_path), timeout=30)
    for s in SCHEMA:
        conn.execute(s)
    modelo, vivo, visto_en = None, None, 0.0
    res = {"tramos": 0, "menciones": 0}
    ultimo_aviso: dict[str, float] = {}
    while time.time() < hasta:
        if vivo is None or time.time() - visto_en > RECHEQUEO_SEG:
            vivo, visto_en = _vivo_actual(urls), time.time()
            if vivo:
                print(f"[tv-en-vivo] {canal}: {vivo['id']} {vivo['titulo'][:70]}", flush=True)
        if not vivo:
            time.sleep(120)
            continue
        t0 = time.time()
        wav = capturar_audio_en_vivo(vivo["id"], segundos=TRAMO_SEG)
        if wav is None:
            # termino o fallo: volver a mirar /live, sin martillar a YouTube
            # (la primera prueba en CI reintentaba cada 6 s)
            vivo = None
            time.sleep(30)
            continue
        if modelo is None:
            from faster_whisper import WhisperModel
            modelo = WhisperModel("small", device="cpu", compute_type="int8")
        segs = transcribir_audio(wav, modelo)
        if not segs:
            continue
        # t_seg relativo al inicio de la transmision: el mismo minuto sirve
        # para el enlace &t= cuando YouTube la guarde como video.
        base = t0 - (vivo["inicio"] or t0)
        ms = guardar_tramo(conn, pais, canal, vivo, [(base + s["start"], s["text"]) for s in segs])
        res["tramos"] += 1
        res["menciones"] += len(ms)
        if ms:
            print(f"[tv-en-vivo] {canal}: {len(ms)} mencion(es)", flush=True)
        buena = next((m for m in ms if vale_aviso(m["terminos"])), None)
        if buena and time.time() - ultimo_aviso.get(vivo["id"], 0) > AVISO_CADA_SEG:
            from congreso_live.notify import enviar_whatsapp
            if enviar_whatsapp(mensaje_aviso(canal, vivo, buena)):
                ultimo_aviso[vivo["id"]] = time.time()
                print(f"[tv-en-vivo] {canal}: aviso WhatsApp enviado", flush=True)
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
        assert len(ms) == 1 and vale_aviso(ms[0]["terminos"])
        assert "📺 En vivo · RPP Noticias" in mensaje_aviso("RPP Noticias", vivo, ms[0])
        assert not vale_aviso(["fenomeno del nino", "Keiko Fujimori"])  # general: queda en la app
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
    elif len(sys.argv) == 2 and sys.argv[1] == "hay-vivo-interes":
        sys.exit(0 if hay_vivo_interes() else 1)
    else:
        _demo()
