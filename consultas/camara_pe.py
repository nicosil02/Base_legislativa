"""Camara (Senado / Diputados / Conjunta) de una sesion de comision vista en
YouTube, y las sesiones que solo salieron en YouTube (el visor del Congreso
no las cargo). Antes vivia dentro de pages/3_Agenda_PE.py."""
from __future__ import annotations

import datetime as dt
import sqlite3

import pandas as pd
import streamlit as st

from consultas import hora_a_minutos
from consultas.agenda_pe import get_conn


# Catalogo oficial de comisiones ordinarias 2026-2027 (fuente:
# comunicaciones.congreso.gob.pe, Res. Leg. 005-2025-2026-CR/El Peruano) -
# cada camara le puso un nombre COMPLETO distinto a su comite del mismo
# tema, asi que un fragmento del titulo alcanza para distinguirlas SIN
# que el titulo de YouTube diga "Senado"/"Diputados" (pasa seguido, ver
# Cz5LEnuU_VQ 2026-09-18: "Comision en asuntos de Salud, Educacion,
# Cultura, Mujer y Desarrollo Social" sin mencionar la camara). El Senado
# junta varios temas en comites "en/de asuntos de X" (unico de esos 3
# combos: nadie mas los junta asi); Diputados los mantiene separados con
# nombres propios que el Senado no usa.
_SENADO_COMBOS: tuple[tuple[str, ...], ...] = (
    ("desarrollo productivo",),  # exclusivo del Senado (Energia y Minas + Infraestructura + Trabajo)
    ("salud", "educacion"), ("salud", "cultura"),
    ("salud", "mujer"), ("salud", "desarrollo social"),  # mega-comite unico del Senado
    ("economia", "consumidor"),  # "...Medio Ambiente y Defensa al Consumidor" (Senado)
)
_DIPUTADOS_KEYWORDS: tuple[str, ...] = (
    "agrario", "pueblos andinos", "amazonicos", "afroperuanos",
    "comercio exterior", "ciencia", "innovacion tecnologica", "deporte",
    "banca", "inteligencia financiera",  # "...Banca, Finanzas e Inteligencia Financiera" (Diputados)
    "regulacion de los servicios publicos", "vivienda y transportes",
    "seguridad social", "modernizacion",
)

# Catalogo oficial de comisiones ORDINARIAS 2026-2027, en el mismo orden
# que el informe semanal real que arma Nicolas (pedido 2026-09-18: "las
# sesiones... podrian aparecer siempre en el orden que tengo en mi doc...
# y si no sesionaron colocar que no sesionaron"). No incluye las
# no-legislativas (Etica, Procedimientos Especiales, Control Politico,
# Inteligencia, Acusaciones Constitucionales, Seguimiento Legislativo) -
# esas aparecen solo si tuvieron sesion real esa semana, al final de la
# tabla de su camara.
_SENADO_COMISIONES_ORDEN: tuple[str, ...] = (
    "Constitución, Reglamento y Relaciones Exteriores",
    "Defensa Nacional y Orden Interno",
    "Desarrollo Productivo, Energía y Minas, Infraestructura y Trabajo",
    "Economía, Medio Ambiente y Defensa al Consumidor",  # el titulo real dice "al", no "del" - ver Defensa del Consumidor de Diputados, comite distinto
    "Salud, Educación, Cultura, Mujer y Desarrollo Social y Digital",
    "Gestión del Estado y Contraloría",
    "Justicia y Derechos Humanos",
)
_DIPUTADOS_COMISIONES_ORDEN: tuple[str, ...] = (
    "Constitución, Reglamento y Relaciones Exteriores",
    "Defensa Nacional y Orden Interno",
    "Desarrollo Agrario",
    "Defensa del Consumidor y Regulación de los Servicios Públicos",
    "Modernización de la Gestión del Estado y Contraloría",
    "Economía, Banca, Finanzas e Inteligencia Financiera",
    "Educación, Cultura y Deporte",
    "Energía y Minas",
    "Justicia y Derechos Humanos",
    "Inclusión Social, Familia, Mujer y Pueblos Andinos, Amazónicos y Afroperuanos",
    "Producción, Comercio Exterior y Turismo",
    "Medio Ambiente y Sostenibilidad",
    "Salud",
    "Trabajo y Seguridad Social",
    "Infraestructura, Vivienda y Transportes",
    "Ciencia, Innovación Tecnológica y Sociedad Digital",
)


def _tipo_de_comision_oficial(nombre: str) -> str | None:
    """El mismo clasificador que ya usa detector.py sobre titulos reales
    de YouTube, aplicado al nombre OFICIAL del catalogo - encuentra que
    palabra clave corta (tipo) le corresponderia a esta comision."""
    from congreso_live.detector import clasificar_titulo
    return clasificar_titulo(f"Comisión de {nombre}")


# Casos puntuales donde ni el titulo ni la agenda real (`sesiones`) alcanzan
# (agenda sin ese dia registrado) - confirmados a mano por Nicolas leyendo
# la DESCRIPCION del video en YouTube (el titulo no siempre la trae, la
# descripcion a veces si). No vale la pena un pipeline de yt-dlp para leer
# descripciones por estos pocos casos - se agregan aca a mano si aparecen.
_OVERRIDES_CAMARA: dict[str, str] = {
    "GEpUFqa-9hY": "Diputados",  # "Constitucion...| 09/09/2026" - confirmado 2026-09-18
}


@st.cache_data(ttl=None, show_spinner=False)
def _camara_de_descripcion(video_id: str) -> str | None:
    """Ultimo fallback: baja la DESCRIPCION real del video (no el
    titulo) via yt-dlp - a veces el titulo omite la camara pero la
    descripcion si la trae (caso real GEpUFqa-9hY, confirmado a mano por
    Nicolas 2026-09-18 leyendo la descripcion en YouTube: "no, tu
    tendrias que revisar la descripcion... y alli lo ves"). Solo se llama
    para las pocas sesiones que ni el titulo, ni el catalogo oficial, ni
    la agenda real resolvieron - un extract_info completo por video no es
    gratis, no vale la pena para las que ya resuelven antes. Cacheado
    para siempre (la descripcion de un video publicado no cambia). None
    si falla (sin red, o el mismo bloqueo de IP de datacenter que YouTube
    le pone a GitHub Actions/Streamlit Cloud - ver congreso_live/detector.py
    - o la descripcion tampoco la menciona)."""
    import os

    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "socket_timeout": 15}
    proxy = os.environ.get("YT_DLP_PROXY")
    if proxy:
        opts["proxy"] = proxy
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception:
        return None
    from congreso_live.detector import _norm
    t = _norm(info.get("description"))
    en_senado, en_diputados = "senado" in t, "diputados" in t
    if en_senado and not en_diputados:
        return "Senado"
    if en_diputados and not en_senado:
        return "Diputados"
    return None


def _camara_del_texto(texto: str | None) -> str | None:
    """Cuenta menciones de 'senador(a)'/'diputado(a)' en la transcripcion
    real - la sala esta llena de gente que se llama a si misma por su
    cargo real durante el pase de lista, senal mas confiable que la
    agenda cuando 2 sesiones reales distintas caen en la ventana de
    fecha de la MISMA fila de agenda. Bug real 2026-09-18: EM7fr1Txae4
    (Diputados, "diputado" x70, "senador" x0 en el texto) resolvia mal a
    "Senado" via camara_de_agenda porque esa semana la agenda solo tenia
    registrada la sesion del Senado, y las dos sesiones (Senado +
    Diputados) caian en su ventana de +-1 dia."""
    if not texto:
        return None
    t = texto.lower()
    n_senado = t.count("senador")
    n_diputados = t.count("diputado")
    if n_senado >= 5 and n_senado > 3 * n_diputados:
        return "Senado"
    if n_diputados >= 5 and n_diputados > 3 * n_senado:
        return "Diputados"
    return None


def _clasificar_camara(tipo: str, titulo: str, fecha: str | None = None,
                       video_id: str | None = None, texto: str | None = None,
                       usar_agenda: bool = True) -> str:
    """'Senado' / 'Diputados' / 'Congreso' (Pleno solemne/conjunto) /
    'Conjunta' (comision BICAMERAL real, ej. Presupuesto) / 'Sin
    confirmar'. Un Pleno ya lo dice en `tipo` (detector.clasificar_titulo).
    Una Comision NO trae la camara en `tipo` (es solo la palabra clave,
    ej. "Comision: Justicia") - se busca primero un marcador explicito en
    el titulo, despues el catalogo oficial de arriba.

    Solo 5 comites se llaman EXACTAMENTE igual en las dos camaras
    (Constitucion, Defensa Nacional, Justicia, Etica Parlamentaria,
    Procedimientos Especiales) - sin "Senado"/"Diputados" explicito en
    el titulo esos quedan ambiguos por texto solo. Para esos, si se pasa
    `fecha`, se cruza contra la agenda real (tabla `sesiones`, ver
    congreso_live.agenda_preview.camara_de_agenda) - pedido real de
    Nicolas 2026-09-18: "cruzando con la agenda de cada cámara". Sin
    `fecha` o sin match en la agenda, "Sin confirmar" en vez de adivinar."""
    if video_id and video_id in _OVERRIDES_CAMARA:
        return _OVERRIDES_CAMARA[video_id]
    if tipo.startswith("Pleno:"):
        return tipo.split(":", 1)[1].strip()
    from congreso_live.detector import _norm
    t = _norm(titulo)
    if "bicameral" in t or "comision permanente" in t or "senadores y camara de diputados" in t:
        return "Conjunta"
    en_senado, en_diputados = "senado" in t, "diputados" in t
    if en_senado and not en_diputados:
        return "Senado"
    if en_diputados and not en_senado:
        return "Diputados"
    if any(all(kw in t for kw in combo) for combo in _SENADO_COMBOS):
        return "Senado"
    if any(kw in t for kw in _DIPUTADOS_KEYWORDS):
        return "Diputados"
    if "asuntos de" in t:  # convencion real del Senado no cubierta arriba
        return "Senado"
    camara = _camara_del_texto(texto)
    if camara:
        return camara
    if not usar_agenda:
        return "Sin confirmar"
    from congreso_live.agenda_preview import camara_de_agenda
    try:
        camara = camara_de_agenda(get_conn(), tipo, titulo, fecha)
    except sqlite3.OperationalError:
        camara = None
    if camara:
        return camara
    if video_id:
        camara = _camara_de_descripcion(video_id)
    return camara or "Sin confirmar"


from core.db import ROOT
_LIVE_STATE = ROOT / "data" / "congreso_live_state.json"


def _hora_12(d: dt.datetime) -> str:
    """"9:34AM" - mismo formato que la API (ver hora_a_minutos)."""
    return d.strftime("%I:%M%p").lstrip("0")


@st.cache_data(ttl=300, show_spinner=False)
def load_sesiones_youtube(fec_inicio: dt.date | None, fec_fin: dt.date | None,
                          ya_en_agenda: frozenset) -> pd.DataFrame:
    """Sesiones de comision que salieron en el YouTube del Congreso pero que
    el Congreso nunca cargo en su visor de sesiones. Caso real 2026-09-30:
    Constitucion de Diputados (facultades) sesiono el 29 y el 30 y el visor
    solo tiene sus sesiones del 31/08 y 07/09 - la API no las devuelve.

    Fuentes: data/congreso_live_state.json (lo que el vigilante vio en vivo,
    con la hora real) + sesiones_transcripciones (el texto sirve para saber
    la camara). `ya_en_agenda` = {(fecha, camara, tipo, minutos)} de la API,
    para no duplicar las que si estan."""
    import json
    import re
    import zlib

    vistos: dict[str, dict] = {}
    try:
        for s in json.loads(_LIVE_STATE.read_text(encoding="utf-8")).get("sesiones", []):
            if s.get("pais", "PE") == "PE" and str(s.get("tipo", "")).startswith("Comision:"):
                vistos[s["id"]] = dict(s)
    except (OSError, ValueError):
        pass
    try:
        rows = get_conn().execute(
            "SELECT video_id, tipo, titulo, fecha, texto FROM sesiones_transcripciones "
            "WHERE tipo LIKE 'Comision:%' AND tipo NOT LIKE '%(EC)%'").fetchall()
    except sqlite3.OperationalError:
        rows = []
    for vid, tipo, titulo, fecha, texto in rows:
        v = vistos.setdefault(vid, {"id": vid, "tipo": tipo, "titulo": titulo,
                                    "url": f"https://www.youtube.com/watch?v={vid}"})
        v["texto"], v["fecha_tx"] = texto, fecha

    out = []
    for vid, v in vistos.items():
        titulo = v.get("titulo") or ""
        hora = None
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", titulo)
        if m:
            fecha = f"{m[3]}-{m[2]}-{m[1]}"
        elif v.get("visto_at"):
            fecha = None
        else:
            fecha = v.get("fecha_tx")
        if v.get("visto_at"):
            # visto_at es UTC; Lima = UTC-5 sin horario de verano.
            lima = dt.datetime.fromisoformat(v["visto_at"].replace("Z", "")) - dt.timedelta(hours=5)
            hora = _hora_12(lima)
            fecha = fecha or lima.date().isoformat()
        if not fecha:
            continue
        if (fec_inicio and fecha < fec_inicio.isoformat()) or (fec_fin and fecha > fec_fin.isoformat()):
            continue
        tipo = v["tipo"]
        # Sin video_id: evita el fallback de yt-dlp (_camara_de_descripcion),
        # que baja cada video uno por uno y colgaba la carga de la tabla.
        # Sin agenda: estas sesiones justamente NO estan en la agenda, y el
        # cruce +-1 dia las pegaba a la otra camara (caso real 30/09:
        # Constitucion de Diputados salia como Senado por la sesion del
        # Senado del 29). Sin titulo ni texto que lo digan, "Sin confirmar".
        camara = _OVERRIDES_CAMARA.get(vid) or _clasificar_camara(
            tipo, titulo, fecha, None, v.get("texto"), usar_agenda=False)
        if any((f, c, t) == (fecha, camara, tipo) for f, c, t, _m in ya_en_agenda):
            continue
        # Camara dudosa: es la misma sesion solo si la hora se parece (el
        # 29/09 Constitucion tuvo Senado 10am en la agenda y Diputados 3pm
        # solo en YouTube).
        mins = hora_a_minutos(hora)
        if camara in ("Sin confirmar", "Conjunta") and any(
                f == fecha and t == tipo and (mins < 0 or m < 0 or abs(m - mins) <= 120)
                for f, _c, t, m in ya_en_agenda):
            continue
        # Nombre oficial solo si el titulo lo trae: el tipo del detector es
        # una palabra clave y "Acusaciones Constitucionales" tambien cae en
        # "Comision: Constitucion".
        from congreso_live.detector import _norm
        orden = {"Senado": _SENADO_COMISIONES_ORDEN,
                 "Diputados": _DIPUTADOS_COMISIONES_ORDEN}.get(camara, ())
        comision = next((n for n in orden if _norm(f"comision de {n}") in _norm(titulo)), None)
        if not comision:
            comision = re.sub(r"^.*?EN VIVO:?\s*|\s*(?:[|l]\s*)?\d{2}/\d{2}/\d{2,4}.*$", "", titulo)
            comision = re.sub(r"^Sesi[oó]n de la\s+", "", comision.strip()) or tipo
        out.append({
            "ID": -(zlib.crc32(vid.encode()) % 10**9), "_fuente": "youtube",
            "Fecha": fecha, "Hora": hora, "Comisión": comision, "Cámara": camara,
            "Tipo": "Solo en YouTube", "Estado": "Transmitida",
            "Nombre": titulo, "_n_pls": 0, "PLs en agenda": "—",
            "_link_teams": None, "_link_video": v.get("url"),
        })
    return pd.DataFrame(out)
