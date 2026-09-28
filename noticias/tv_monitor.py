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
    "plaguicida", "pesticida", "agroquimico", "glifosato", "transgenico", "semillas",
    "sanidad agraria", "inocuidad", "medicamentos", "vacuna",
    "datos personales", "inteligencia artificial", "biometri", "identidad digital",
    "ciberseguridad", "lavado de activos", "open finance", "fintech",
    "fenomeno el nino", "fenomeno del nino",
]

POR_CANAL = 6          # ultimos N de /streams y de /videos por canal
NUEVOS_MAX = 40        # videos a leer por corrida (cada uno = 2 requests a YouTube)
DURACION_MIN = 300     # programas y entrevistas, no clips
VENTANA_SEG = 25       # contexto a cada lado de la mencion

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


def _patrones() -> list[tuple[str, re.Pattern]]:
    """(etiqueta, regex). Autoridades por nombre completo o apellido (los
    subtitulos suelen decir "el ministro Vinelli"), temas por frase."""
    pats = []
    for lista in AUTORIDADES.values():
        for nombre, _ in lista:
            apellido = re.escape(_norm(nombre.split()[-1]))
            # los subtitulos automaticos simplifican letras dobles ("Vineli")
            apellido = re.sub(r"(\w)\1", r"\1{1,2}", apellido)
            pats.append((nombre, re.compile(rf"\b{apellido}\b")))
    for t in TERMINOS:
        pats.append((t, re.compile(rf"\b{re.escape(t)}")))
    return pats


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
    salida = []
    for g in grupos:
        a, b = g["ini"] - VENTANA_SEG, g["fin"] + VENTANA_SEG
        frag = " ".join(txt for t, txt in lineas if a <= t <= b)
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
    nuevos = [c for c in _candidatos() if c["id"] not in ya][:max_n]
    res = {"leidos": 0, "sin_subtitulos": 0, "menciones": 0}
    for c in nuevos:
        try:
            lineas, _ = _subtitulos(c["id"])
        except Exception as e:
            log.warning("subtitulos de %s fallaron: %s", c["id"], e)
            continue
        if lineas is None:
            # Recien termino y YouTube no genero los subtitulos: no se marca
            # como visto, la proxima corrida lo reintenta.
            res["sin_subtitulos"] += 1
            continue
        menciones = buscar_menciones(lineas)
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


def _demo():
    assert buscar_menciones([(0, "el ministro Vineli dijo")])[0]["terminos"] == ["Marco Vinelli"]
    lineas = [(0, "buenas noches"), (10, "hoy nos acompaña el ministro Vinelli"),
              (20, "hablamos de las facultades legislativas"), (200, "pasamos a deportes"),
              (400, "el fenómeno El Niño y el Senasa")]
    ms = buscar_menciones(lineas)
    assert len(ms) == 2, ms
    assert ms[0]["terminos"] == ["Marco Vinelli", "facultades legislativas"], ms[0]
    assert "deportes" not in ms[0]["fragmento"]
    assert ms[1]["terminos"] == ["fenomeno el nino", "senasa"], ms[1]
    assert not buscar_menciones([(0, "gol de Cueva en el minuto 90")])
    assert parse_json3({"events": [{"tStartMs": 1500, "segs": [{"utf8": "hola "}, {"utf8": "mundo"}]},
                                   {"tStartMs": 2000}]}) == [(1.5, "hola mundo")]
    print("OK tv_monitor: menciones agrupadas por cercania, sin falsos positivos, json3")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 3 and sys.argv[1] == "escanear":
        print(f"tv_monitor: {escanear(sys.argv[2])}")
    else:
        _demo()
