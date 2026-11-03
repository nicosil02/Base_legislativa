"""Datos y acciones de la interfaz propia (front/*.js).

Un hilo arma cada seccion por detras y la guarda en memoria: leer los PDF, las
matrices y cruzar con el cerebro tarda, y nadie debe esperarlo. El navegador
pide una seccion con `atender()`, la filtra alla y solo vuelve aqui para lo que
escribe algo o necesita calcularse (transcripciones, chat, busqueda).
"""
from __future__ import annotations

import datetime as dt
import html
import importlib
import json
import re
import sqlite3
import threading
import sys
import time
import types
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from alerts import historial
from alerts import que_paso_hoy as q
from alerts.chat import contexto_relacionado, mensaje_inicial, responder
from cerebro.ui import afinidad_claves, afinidad_noticias, afinidad_tema_noticias, conexion, historias_noticias, le_interesa
from consultas import agenda_ec, agenda_pe, camara_pe, ecuador, hora_a_minutos, matriz_pls, peru
from core import legislativo, store
from core.db import connect_ro
from noticias import pagina
from noticias.feedback_store import deshacer_descarte, list_descartadas, registrar_combinadas, registrar_descarte
from noticias.temas import clasificar, todos_los_temas
from scraper.categorias import CATEGORIA_CLIENTES_PL
from scraper.sync import FECHA_INICIO_BICAMERAL

MAX_ATRASO_H = 6  # los datos se refrescan varias veces al dia: mas que esto es que se trabaron
DIAS_AGENDA = 7
CADA_SEG = 300
TIPOS = {"norma": "Norma", "pl": "Proyecto", "noticia": "Noticia"}
DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
BORRADORES = "data/alertas_borradores.json"
VENTANA_NOTICIAS = "date('now', '-7 days')"
MAX_NOTICIAS = 6000  # ponytail: alcanza para la semana completa hoy; si crece, bajar a 3 dias o paginar
LARGO_RESUMEN = 400


def _filas(df: pd.DataFrame) -> list[dict]:
    """Sin NaN: JSON.parse no los acepta."""
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _resumen_limpio(resumen: str | None, titulo: str) -> str:
    """Google News manda de resumen un enlace con el mismo titulo: eso no aporta."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", resumen or "")).strip()
    return "" if t[:40].lower() == titulo[:40].lower() else t[:LARGO_RESUMEN]


# ------------------------------------------------------------------ Panel
def _ventanas() -> dict[str, datetime]:
    ahora = q._lima_ahora()
    hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"Hoy": hoy, "Desde ayer 4 p. m.": hoy - timedelta(hours=8), "Últimos 2 días": ahora - timedelta(days=2)}


def _datos(desde: datetime, pe: sqlite3.Connection, cerebro: sqlite3.Connection | None) -> dict:
    desde_utc = desde.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return {"sin_cerebro": cerebro is None, "noticias": q.hallazgos(pe, cerebro, desde_utc) if cerebro else [],
            "normas": q.normas_datos(pe, desde_utc),
            "pls": q.pls_datos(desde), "sesiones": q.sesiones_datos(pe, desde_utc),
            "entradas": dict(pe.execute(
                """SELECT f.pais, count(*) FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
                   WHERE n.first_seen_at >= ? GROUP BY 1""", (desde_utc,)).fetchall()),
            "ultimo": pe.execute("SELECT max(first_seen_at) FROM noticias").fetchone()[0]}


def _tramite() -> list[dict]:
    return [{**p, "clientes": q._clientes_de_pl(p["categoria"], p["numero"], p["pais"])}
            for pais in legislativo.PAISES for p in legislativo.tramite(pais)]


def _agenda(cerebro: sqlite3.Connection | None) -> list[dict]:
    hoy = q._lima_ahora().date()
    try:
        puntos = {c: json.loads(p or "[]") for c, p in cerebro.execute("SELECT clave, puntos FROM agenda_avisada")} if cerebro else {}
    except sqlite3.OperationalError:  # agenda_interes aun no corrio en este cerebro.db
        puntos = {}
    filas = [{**a, "puntos": puntos.get(a["clave"], [])}
             for pais in legislativo.PAISES for a in legislativo.agendas(pais, hoy, hoy + timedelta(days=DIAS_AGENDA))]
    return sorted(filas, key=lambda a: (a["fecha"], a["hora"] or ""))


def _dia(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{DIAS[d.weekday()]} {d.day}/{d.month}"


def _sesion(s: dict) -> str:
    """Ecuador titula "SESION ORDINARIA Nro. 095...": el tipo dice mejor que comision es."""
    if "(EC)" in s["tipo"]:
        titulo = s["tipo"].replace("Comision: ", "Comisión de ").replace("Pleno: ", "Pleno de la ").replace(" (EC)", ", Ecuador")
    else:
        titulo = re.sub(r"^\W*EN VIVO:?\s*", "", s["titulo"]).strip() or "Sesión"
    # los titulos de Peru ya traen la fecha
    return titulo if re.search(r"\d/\d", titulo) or not s["fecha"] else f"{titulo}, {_dia(s['fecha'])}"


def _cuando(a: dict) -> str:
    hora = (a["hora"] or "").replace("AM", " a. m.").replace("PM", " p. m.")
    return ", ".join(x for x in [_dia(a["fecha"]), hora] if x)


def _alertas(datos: dict) -> list[dict]:
    """Todo junto y con la misma forma: normas y proyectos primero, son hechos oficiales."""
    out = [{"tipo": "norma", "titulo": n["titulo"], "url": n["url"], "pais": n["pais"], "fecha": None,
            "porque": {}, "resumen": n["resumen"], "fuente": "Norma publicada", "otras": [], "id": None, "tema": None}
           for n in datos["normas"]]
    out += [{"tipo": "pl", "titulo": f"Proyecto {p['numero']}: {p['titulo']}", "url": p["url"], "pais": p["pais"],
             "fecha": p["fecha"], "porque": {c: f"Pasó a {p['valor']}" for c in p["clientes"]},
             "resumen": p["valor"], "fuente": "Proyecto de ley", "otras": [], "id": None, "tema": p["categoria"]}
            for p in datos["pls"] if p["clientes"]]
    out += [{"tipo": "norma" if h["es_norma"] else "noticia", "titulo": h["titulo"], "url": h["url"], "pais": h["pais"], "fecha": h["fecha"],
             "porque": h["clientes"], "resumen": None, "fuente": h["fuente"], "otras": h["otras"], "fuentes": h.get("fuentes", []), "id": h["id"],
             "tema": next(iter(clasificar(h["titulo"], None, h["url"])), None)}
            for h in datos["noticias"] if h["clientes"]]
    for a in out:
        if a["tipo"] == "norma":
            a["titulo"], doc = q.titular_norma(a["titulo"])
            a["fuente"] = doc or a["fuente"]
    # sorted es estable: dentro de cada tipo queda lo mas reciente primero
    return sorted(out, key=lambda a: list(TIPOS).index(a["tipo"]))


def _sesiones(datos: dict) -> list[dict]:
    return [{"tipo": "sesion", "titulo": _sesion(s), "pais": "EC" if "(EC)" in s["tipo"] else "PE", "fecha": s["fecha"],
             "resumen": s["resumen"], "ideas": s["ideas"][:5], "fuente": "Sesión",
             "url": None if s["video_id"].startswith("fb_") else f"https://www.youtube.com/watch?v={s['video_id']}"}
            for s in datos["sesiones"]]


def _proyecto(p: dict) -> dict:
    titulo = re.sub(r"^(PROPOSICIÓN LEGISLATIVA|PROYECTO DE LEY)( ORGÁNICA)? (QUE )?", "", p["titulo"]).capitalize()
    return {"pais": p["pais"], "numero": p["numero"], "titulo": titulo, "etapa": p["etapa"], "clientes": p["clientes"],
            "url": p["url"], "cambio": (p["cambio"] or p["fecha"] or "")[:10]}


def panel() -> dict | None:
    pe = q._ro("proyectos.db")
    if pe is None:
        return None
    cerebro = conexion()
    ventanas = {v: _datos(d, pe, cerebro) for v, d in _ventanas().items()}
    tramite, agenda = _tramite(), _agenda(cerebro)
    datos = next(iter(ventanas.values()))
    atraso = (datetime.now(timezone.utc)
              - datetime.fromisoformat(datos["ultimo"].replace("Z", "+00:00")).astimezone(timezone.utc)).total_seconds() / 3600
    return {
        "ahora": q._lima_ahora().strftime("%d/%m/%Y, %H:%M"), "atrasada": atraso > MAX_ATRASO_H,
        "ultima": f"última noticia hace {atraso:.0f} h" if atraso >= 1 else "última noticia hace menos de 1 h",
        "sin_cerebro": datos["sin_cerebro"], "etapas": legislativo.ETAPAS, "dias_agenda": DIAS_AGENDA,
        "agenda": [{**a, "cuando": _cuando(a)} for a in agenda],
        "proyectos": [_proyecto(p) for p in tramite if p["clientes"]],
        "total_tramite": {p: sum(x["pais"] == p for x in tramite) for p in legislativo.PAISES},
        "ventanas": {v: {"alertas": _alertas(d), "sesiones": _sesiones(d), "entradas": d["entradas"]}
                     for v, d in ventanas.items()},
    }


# ------------------------------------------------------------------ Noticias
def noticias(pais: str) -> dict:
    from cerebro.embeddings import AFINIDAD_MEDIA, AFINIDAD_SECTOR, nivel_afinidad
    clientes = historial.clientes(pais)
    df = pagina.load_noticias(pais, VENTANA_NOTICIAS, limit=MAX_NOTICIAS).reset_index(drop=True)
    ids = tuple(int(i) for i in df["ID"])
    # misma regla de load_noticias(cliente=...): "todos" cuenta para cualquiera
    conn = pagina.get_conn()
    de_fuente = {f: t or "" for f, t in conn.execute("SELECT nombre, clientes FROM noticias_fuentes WHERE pais = ?", (pais,))}
    afinidad = {c: afinidad_noticias(ids, c) for c in clientes}
    interesa = le_interesa(ids)
    temas = todos_los_temas()
    sector = {t: afinidad_tema_noticias(ids, t) for t in temas}
    grupos = historias_noticias(ids, tuple(pagina._s(t) for t in df["Título"]), tuple(df["Fuente"])) if len(df) > 1 else [0] * len(df)
    filas = []
    for r, grupo in zip(_filas(df), grupos):
        i = int(r["ID"])
        filas.append({
            "id": i, "titulo": (r["Título"] or "").strip(), "resumen": _resumen_limpio(r["Resumen"], (r["Título"] or "").strip()), "url": r["Enlace"],
            "fecha": (r["Fecha"] or "")[:10], "fuente": r["Fuente"], "cat": r["Categoría fuente"], "temas": r["Temas"],
            "norma": bool(r["EsNormativa"]), "pl": r["PL_relacionado"] if isinstance(r["PL_relacionado"], str) else None,
            "para": [c for c in clientes if c in de_fuente.get(r["Fuente"], "") or "todos" in de_fuente.get(r["Fuente"], "")], "grupo": int(grupo),
            "af": {c: round(v, 3) for c in clientes if (v := afinidad[c].get(i)) is not None},
            "nivel": {c: nivel_afinidad(afinidad[c].get(i)) for c in clientes if afinidad[c].get(i) is not None},
            "sector": {t: round(v, 3) for t in temas if (v := sector[t].get(i)) is not None and v >= AFINIDAD_SECTOR},
            "interesa": dict(interesa.get(i, [])),
        })
    cortes = {k: conn.execute(f"SELECT {v}").fetchone()[0] for k, v in pagina.VENTANAS.items()}
    salida = {"filas": filas, "kpis": pagina.load_kpis(pais), "clientes": clientes, "temas": temas, "cortes": cortes,
              "categorias": pagina.load_categorias_fuente(pais), "fuentes": pagina.load_fuentes(pais),
              "umbral": AFINIDAD_MEDIA}
    if pais == "EC":
        salida["seguimiento"] = _filas(pagina._seguimiento_pl_ec())
    return salida


def tv(pais: str) -> dict:
    from congreso_live.resumenes_store import list_resumenes
    from noticias.videos import MEDIOS, PEDIDOS_DIR, _norm
    from noticias.tv_monitor import relevante, terminos_de
    from noticias.videos_ui import _RAIZ, _donde, _q

    conn = pagina.get_conn()
    desde = "-14 days"
    videos = _q(conn, """SELECT v.video_id, v.autoridad, v.cargo, v.titulo, v.canal, v.duracion_seg, v.first_seen_at,
                                t.texto IS NOT NULL AS transcrito
                         FROM videos_autoridades v LEFT JOIN sesiones_transcripciones t ON t.video_id = v.video_id
                         WHERE v.pais = ? AND v.first_seen_at >= datetime('now', ?)
                         ORDER BY (t.texto IS NULL), v.first_seen_at DESC, v.duracion_seg DESC""", (pais, desde))
    menciones = _q(conn, """SELECT m.video_id, m.t_seg, m.canal, m.titulo, m.terminos, m.fragmento, m.first_seen_at,
                                   v.texto IS NOT NULL AS transcrito
                            FROM tv_menciones m LEFT JOIN tv_vistos v ON v.video_id = m.video_id
                            WHERE m.pais = ? AND m.first_seen_at >= datetime('now', ?)
                            ORDER BY m.first_seen_at DESC, m.video_id, m.t_seg""", (pais, desde))
    if not videos.empty:
        videos = videos[videos["canal"].map(lambda c: any(m in _norm(c) for m in MEDIOS))]
    if not menciones.empty:
        menciones["terminos"] = menciones["fragmento"].map(lambda f: ", ".join(terminos_de(f)))
        menciones = menciones[menciones["terminos"].map(lambda t: relevante(t.split(", ")) if t else False)]
    resumenes = list_resumenes()
    salida_v = []
    for r in videos.itertuples():
        res = resumenes.get(r.video_id) or {}
        salida_v.append({"video_id": r.video_id, "autoridad": r.autoridad, "titulo": r.titulo, "canal": r.canal or "",
                         "min": int((r.duracion_seg or 0) // 60), "fecha": r.first_seen_at[:10], "transcrito": bool(r.transcrito),
                         "resumen": res.get("resumen"), "ideas": res.get("ideas_clave", []),
                         "pedido": (_RAIZ / PEDIDOS_DIR / f"{r.video_id}.json").exists()})
    salida_m = []
    if not menciones.empty:
        menciones = menciones.head(1000).reset_index(drop=True)
        from noticias.videos_ui import _historias
        menciones["historia"] = _historias(tuple(menciones["fragmento"]))
        for r in menciones.itertuples():
            donde, url = _donde(r)
            salida_m.append({"video_id": r.video_id, "canal": r.canal, "titulo": r.titulo, "terminos": r.terminos,
                             "fragmento": r.fragmento, "fecha": r.first_seen_at[:10], "donde": donde, "url": url,
                             "transcrito": bool(r.transcrito), "historia": int(r.historia)})
    return {"videos": salida_v, "menciones": salida_m}


# ------------------------------------------------------------------ Proyectos de ley
def _clientes_pl(pais: str, claves: list[str], temas: list[str]) -> list[dict]:
    """Misma regla de las paginas viejas: tema del cliente, o su matriz puntual,
    o afinidad alta por significado. {cliente: [nivel, afinidad, en_matriz]}."""
    from cerebro.embeddings import AFINIDAD_ALTA, nivel_afinidad
    matriz = matriz_pls(pais)
    salida: list[dict] = [{} for _ in claves]
    for c in historial.clientes(pais):
        temas_c = set(CATEGORIA_CLIENTES_PL.get(c, []))
        mat = matriz.get(c, set())
        af = afinidad_claves(tuple(f"pl_{pais}_{k}" for k in claves), c)
        for i, (k, tema) in enumerate(zip(claves, temas)):
            a = af.get(f"pl_{pais}_{k}")
            if tema in temas_c or k in mat or (a or 0) >= AFINIDAD_ALTA:
                salida[i][c] = [nivel_afinidad(a), round(a, 3) if a is not None else None, k in mat]
    return salida


def _evolucion(df: pd.DataFrame) -> list[dict]:
    d = df.reset_index()
    return [{"mes": str(r.iloc[0])[:7], "presentados": int(r.iloc[1]), "leyes": int(r.iloc[2])} for _, r in d.iterrows()]


def proyectos_pe() -> dict:
    df = peru.load_proyectos(None, None)
    clientes = _clientes_pl("PE", [str(p) for p in df["PL"]], list(df["Tema"]))
    filas = []
    for r, cli in zip(_filas(df), clientes):
        autores = str(r["Autor(es)"] or "")
        filas.append({"pl": r["PL"], "camara": r["Cámara"], "titulo": r["Título"], "presentado": r["Presentado"],
                      "cambio": r["Último cambio"], "estado": r["Estado"], "autor": autores.split(";")[0].strip(), "autores": autores,
                      "bancada": r["Partido"], "proponente": r["Proponente"], "comision": r["Comisión"],
                      "comisiones": r["_comisiones_all"] if isinstance(r["_comisiones_all"], list) else [], "tema": r["Tema"],
                      "url": r["Portal"], "pdf": r["PDF"], "clientes": cli})
    pls_hoy, noticias_hoy = peru.documentos_hoy()
    cats = peru.load_catalogs()
    estado = peru._sync_status()
    return {"filas": filas, "kpis": {**peru.kpi_totals(), "PLs nuevos hoy": pls_hoy, "Noticias hoy": noticias_hoy},
            "evolucion": _evolucion(peru.evolucion_mensual()), "sugerencias": peru.sugerencias_pendientes(),
            "comisiones": cats.get("comisiones_catalogo", []), "especiales": peru.COMISIONES_ESPECIALES_LABEL,
            "minimo": cats["fec_min"], "maximo": cats["fec_max"], "clientes": historial.clientes("PE"),
            "sync": {"corriendo": estado["running"], "minutos": estado["mins_ago"], "ultimo": estado["last"]}}


def proyectos_ec() -> dict:
    df = ecuador.load_proyectos(None, None)
    claves = [str(t) for t in df["_n_tramite_label"]]
    clientes = _clientes_pl("EC", claves, list(df["Tema"]))
    filas = []
    for r, cli in zip(_filas(df), clientes):
        prop = str(r["Proponentes"] or "")
        filas.append({"pl": str(r["_n_tramite_label"]), "titulo": r["Título"], "presentado": r["Presentado"], "cambio": r["Último cambio"],
                      "estado": r["Estado"], "tipo_prop": r["Tipo proponente"], "proponente": prop.split("/")[0].strip(), "proponentes": prop,
                      "comision": r["Comisión"], "tema": r["Tema"], "unificado": r["Unificado con"],
                      "es_unificado": bool(r["_es_unificado_portal"] or 0) or bool(r["Unificado con"]),
                      "url": str(r["N. Trámite"] or "").split("#")[0], "pdf": r["PDF"], "clientes": cli})
    pls_hoy, noticias_hoy = ecuador.documentos_hoy()
    cats = ecuador.load_catalogs()
    return {"filas": filas, "kpis": {**ecuador.kpi_totals(), "PLs nuevos hoy": pls_hoy, "Noticias hoy": noticias_hoy},
            "evolucion": _evolucion(ecuador.evolucion_mensual()), "candidatas": [dict(c) for c in ecuador._noticias_tramite_recientes()],
            "minimo": cats["fec_min"], "maximo": cats["fec_max"], "clientes": historial.clientes("EC"), "sync": ecuador.last_sync()}


def _detalle_pl_ec(tramite: str) -> dict:
    docs, unif, marcado = ecuador.detalle_pl(tramite)
    grupo = None
    if unif:
        miembros = [m for m in (unif["miembros"] or "").split(",") if m]
        grupo = {"nombre": unif["nombre"], "descripcion": unif["descripcion"], "principal": unif["n_tramite_principal"],
                 "miembros": [{"pl": m["n_tramite"], "titulo": (m["titulo"] or "")[:160], "estado": m["estado"] or "—"}
                              for m in ecuador.proyectos_por_tramite(miembros)]}
    return {"docs": [dict(d) for d in docs], "grupo": grupo, "marcado": bool(marcado)}


# ------------------------------------------------------------------ Agenda
def _transcripciones(df: pd.DataFrame, camara: bool) -> list[dict]:
    from congreso_live.resumenes_store import list_resumenes
    resumenes = list_resumenes()
    salida = []
    for r in _filas(df):
        res = resumenes.get(r["video_id"]) or {}
        salida.append({"video_id": r["video_id"], "tipo": r["tipo"], "titulo": r["titulo"], "fecha": r["fecha"],
                       "dur": r["duracion_seg"], "temas": [t for t in (r.get("temas") or "").split(",") if t],
                       "resumen": res.get("resumen"), "ideas": res.get("ideas_clave", []), "cumplida": res.get("agenda_cumplida"),
                       "extracto": (r["texto"] or "")[:180],
                       "camara": camara_pe._clasificar_camara(r["tipo"], r["titulo"], r["fecha"], r["video_id"], r["texto"]) if camara else None})
    return salida


def agenda_peru() -> dict:
    from alerts.seguimiento_store import list_seguidas
    hoy = dt.date.today()
    fin = hoy + dt.timedelta(days=30)
    cats = agenda_pe.load_catalogs()
    ini = dt.date.fromisoformat(cats["fec_min"] or "2023-08-15")
    df = agenda_pe.load_sesiones(ini, fin)
    ya = frozenset((r["Fecha"], r["Cámara"], camara_pe._tipo_de_comision_oficial(r["Comisión"]), hora_a_minutos(r["Hora"]))
                   for _, r in df[(df["_fuente"] == "comision") & (df["Fecha"] >= FECHA_INICIO_BICAMERAL)].iterrows())
    yt = camara_pe.load_sesiones_youtube(ini, fin, ya)
    if not yt.empty:
        df = pd.concat([df, yt], ignore_index=True)
        df["_h"] = df["Hora"].apply(hora_a_minutos)
        df = df.sort_values(["Fecha", "_h"], ascending=[False, False], kind="mergesort").drop(columns=["_h"])
    kpis = agenda_pe.kpi_totals()
    kpis.pop("Referencias totales", None)
    try:
        seguidas = sorted(list_seguidas())
    except Exception as e:
        print(f"[agenda] seguimiento: {e}")
        seguidas = []
    por_comision = agenda_pe.load_pls_por_comision(ini, fin)
    catalogo = lambda orden: [[n, camara_pe._tipo_de_comision_oficial(n)] for n in orden]
    return {"sesiones": [{"id": int(r["ID"]) if r["ID"] is not None else None, "fuente": r["_fuente"], "fecha": r["Fecha"], "hora": r["Hora"],
                          "comision": r["Comisión"], "camara": r["Cámara"], "tipo": r["Tipo"], "estado": r["Estado"], "nombre": r["Nombre"],
                          "n_pls": int(r["_n_pls"] or 0), "pls": r["PLs en agenda"], "teams": r["_link_teams"], "video": r["_link_video"]}
                         for r in _filas(df)],
            "kpis": kpis, "por_comision": _filas(por_comision), "mesas": _filas(agenda_pe.load_mesas(limit=120)) if agenda_pe.has_mesas_table() else [],
            "transcripciones": _transcripciones(agenda_pe.load_transcripciones(), True),
            "senado": catalogo(camara_pe._SENADO_COMISIONES_ORDEN), "diputados": catalogo(camara_pe._DIPUTADOS_COMISIONES_ORDEN),
            "comisiones": cats["comisiones"], "seguidas": seguidas, "minimo": cats["fec_min"], "clientes": historial.clientes("PE"),
            "temas_cliente": {c: CATEGORIA_CLIENTES_PL.get(c, []) for c in historial.clientes("PE")},
            "matriz": {c: sorted(v) for c, v in matriz_pls("PE").items()}}


def _clave_organo(nombre: str | None) -> str:
    import unicodedata
    t = (nombre or "").split(":", 1)[-1].replace("(EC)", "").strip().lower()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return "pleno" if t.startswith("asamblea nacional") else t


def agenda_ecuador() -> dict:
    from congreso_live.facebook_ec import url_video
    hoy = dt.date.today()
    cats = agenda_ec.load_catalogs()
    ini = dt.date.fromisoformat(cats["fec_min"] or "2025-05-01")
    fin = hoy + dt.timedelta(days=30)
    df = agenda_ec.load_sesiones(ini, fin)
    trans = _transcripciones(agenda_ec.load_sesiones_ec_transcritas(), False)
    for t in trans:
        t["url"] = url_video(t["video_id"])
        t["clave"] = f"{_clave_organo(t['tipo'])}|{t['fecha'] or ''}"
    return {"sesiones": [{"uid": r["UID"], "fecha": r["Fecha"], "hora": r["Hora"], "comision": r["Comisión"], "n_pls": int(r["_n_pls"] or 0),
                          "pls": r["PLs en agenda"], "nombre": r["Nombre de sesión"],
                          "clave": f"{_clave_organo(r['Comisión'])}|{r['Fecha'] or ''}"} for r in _filas(df)],
            "kpis": {k: v for k, v in agenda_ec.kpi_totals().items() if k != "Referencias totales"},
            "por_comision": _filas(agenda_ec.load_pls_agenda_ec(ini, fin)), "transcripciones": trans,
            "minimo": cats["fec_min"], "clientes": historial.clientes("EC"),
            "temas_cliente": {c: CATEGORIA_CLIENTES_PL.get(c, []) for c in historial.clientes("EC")},
            "matriz": {c: sorted(v) for c, v in matriz_pls("EC").items()}}


def _organo(tipo: str) -> str:
    """Los tipos vienen sin tildes ("Comision: Gestion Del Estado"): se arreglan los casos que se repiten."""
    t = re.sub(r" (Del|De|La|Y|E) ", lambda m: f" {m[1].lower()} ", tipo.replace(" (EC)", "").strip())
    t = re.sub(r"cion\b", "ción", t)
    for sin, con in (("Politic", "Polític"), ("Economia", "Economía"), ("Energia", "Energía"), ("Gestion ", "Gestión "),
                     ("Inclusion ", "Inclusión "), ("Etica ", "Ética "), (": Mujer", ": la Mujer")):
        t = t.replace(sin, con)
    if t.startswith("Pleno: "):
        x = t[7:]
        return "Pleno de la Asamblea Nacional" if x.startswith("Asamblea") else f"Pleno del {x}" if x in ("Senado", "Congreso") else f"Pleno de {x}"
    if t.startswith("Comision: "):
        x = t[10:]
        return x[0].upper() + x[1:] if x.lower().startswith("mesa") else "Comisión Agraria" if x == "Agrario" else f"Comisión de {x}"
    return t


def transcripciones() -> dict:
    """Todas las sesiones de los dos paises, para la seccion propia. El texto
    completo se pide aparte al abrir una; aqui solo el inicio, que basta para
    el extracto y para saber la camara."""
    from congreso_live.facebook_ec import url_video
    # ponytail: 8000 caracteres alcanzan para la camara; si _camara_del_texto empieza a fallar, subirlo
    df = pd.read_sql_query("""SELECT video_id, tipo, titulo, fecha, duracion_seg, temas, substr(texto, 1, 8000) AS texto
                              FROM sesiones_transcripciones WHERE tipo NOT LIKE 'Entrevista:%'
                              ORDER BY fecha DESC, video_id DESC""", connect_ro("proyectos.db"))
    ec = df["tipo"].str.endswith("(EC)")
    filas = []
    for pais, parte in (("PE", df[~ec]), ("EC", df[ec])):
        for t in _transcripciones(parte, pais == "PE"):
            # los titulos de YouTube conservan "EN VIVO" aunque la sesion ya termino
            filas.append({**t, "pais": pais, "organo": _organo(t["tipo"]),
                          "titulo": re.sub(r"^\W*EN VIVO\s*:?\s*", "", t["titulo"] or "", flags=re.I).strip() or "Sesión",
                          "url": url_video(t["video_id"]) if pais == "EC" else f"https://www.youtube.com/watch?v={t['video_id']}"})
    filas.sort(key=lambda t: (t["fecha"] or "", t["video_id"]), reverse=True)
    return {"filas": filas}


# ------------------------------------------------------------------ Ficha de un proyecto
def _noticias_de_pl(pe: sqlite3.Connection, pais: str, n: int | None, titulo: str) -> list[dict]:
    """Noticias que nombran el PL (Peru, por numero) o lo describen (Ecuador, por palabras)."""
    filas = pe.execute("""SELECT n.id, n.titulo, n.resumen, n.url, COALESCE(n.fecha_pub, n.first_seen_at), f.nombre
                          FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
                          WHERE f.pais = ? AND n.first_seen_at >= date('now', '-180 days')""", (pais,)).fetchall()
    if n is not None:
        # "PL 709", "proyecto de ley N.° 00709", "proposición legislativa 709/2026"
        pat = re.compile(rf"\b(?:pl|proyecto de ley|proposici[oó]n legislativa)\s*(?:n\.?\s*[°º]\s*)?0*{n}\b", re.I)
        hay = [f for f in filas if pat.search(f"{f[1]} {f[2] or ''}")]
    else:
        from clientes.matrices import coincide_con_noticia
        # Solo el titular: los sumarios del Registro Oficial nombran de todo y empataban con cualquier PL
        # y en minusculas: con titulos en MAYUSCULAS cada palabra contaba como sigla compartida
        hay = [f for f in filas if coincide_con_noticia(titulo.lower(), f[1].lower(), noticia_titulo=f[1].lower())]
    hay.sort(key=lambda f: f[4] or "", reverse=True)
    return [{"id": i, "titulo": t, "url": u, "fecha": (fe or "")[:10], "fuente": fu} for i, t, _r, u, fe, fu in hay[:15]]


def ficha_pl(pais: str, pl: str) -> dict:
    """Todo lo del proyecto en un lugar: tramite, sesiones, votaciones y noticias."""
    pe = connect_ro("proyectos.db")
    if pais == "PE":
        fila = pe.execute("SELECT per_par_id, cod_tipo_parl, pley_num FROM proyectos WHERE proyecto_ley = ?", (pl,)).fetchone()
        if not fila:
            return {"error": "No está en la base"}
        per, tipo, num = fila
        tramite = [{"fecha": (f or "")[:10], "estado": e, "detalle": ", ".join(x for x in (c, d) if x)}
                   for f, e, c, d in pe.execute("""SELECT fecha, estado, comisiones, detalle FROM seguimientos
                       WHERE per_par_id = ? AND cod_tipo_parl = ? AND pley_num = ? ORDER BY fecha DESC""", (per, tipo, num))]
        sesiones = [{"fecha": f, "organo": o, "que": (c or "")[:220]} for f, o, c in pe.execute(
            """SELECT DISTINCT s.fecha, s.nombre_comision, r.contexto FROM sesion_pl_referenciado r
               JOIN sesiones s ON s.id_sesion = r.id_sesion WHERE r.pley_num = ? AND r.per_par_id = ?
               ORDER BY s.fecha DESC LIMIT 20""", (num, per))]
        votos = []
        for vid, f, asunto, si, no, ab in pe.execute(
                """SELECT id, fecha, asunto, si, no, abst FROM votacion_pleno
                   WHERE pley_num = ? AND pl_cod_tipo_parl = ? ORDER BY fecha DESC""", (num, tipo)):
            bancadas: dict[str, dict] = {}
            for b, v, k in pe.execute("SELECT bancada, voto, count(*) FROM voto_pleno_nominal WHERE votacion_id = ? GROUP BY 1, 2", (vid,)):
                bancadas.setdefault(b or "Sin bancada", {})[v] = k
            votos.append({"fecha": f, "asunto": (asunto or "")[:260], "si": si, "no": no, "abst": ab, "bancadas": bancadas})
        noticias = _noticias_de_pl(pe, "PE", num, "")
    else:
        ec = connect_ro("proyectos_ec.db")
        fila = ec.execute("SELECT titulo FROM proyectos WHERE n_tramite = ?", (pl,)).fetchone()
        if not fila:
            return {"error": "No está en la base"}
        tramite = [{"fecha": (f or "")[:10], "estado": d, "detalle": f"antes: {a}" if a else ""}
                   for f, a, d in ec.execute("""SELECT changed_at, valor_antes, valor_despues FROM historial_cambios
                       WHERE n_tramite = ? AND campo = 'estado' ORDER BY changed_at DESC""", (pl,))]
        sesiones = [{"fecha": (f or "")[:10], "organo": o, "que": (s or "")[:220]} for f, o, s in ec.execute(
            """SELECT DISTINCT s.fecha, s.nombre_comision, s.summary FROM sesion_ec_pl_referenciado r
               JOIN sesiones_ec s ON s.uid = r.uid WHERE r.n_tramite = ? ORDER BY s.fecha DESC LIMIT 20""", (pl,))]
        votos = []
        noticias = _noticias_de_pl(pe, "EC", None, fila[0])
    from alerts import pls_seguidos
    return {"tramite": tramite, "sesiones": sesiones, "votos": votos, "noticias": noticias,
            "seguido": pls_seguidos.clave(pais, pl) in pls_seguidos.lista()}


def _texto_video(video_id: str) -> str:
    conn = connect_ro("proyectos.db")
    for tabla in ("sesiones_transcripciones", "tv_vistos"):
        try:
            f = conn.execute(f"SELECT texto FROM {tabla} WHERE video_id = ?", (video_id,)).fetchone()
        except sqlite3.OperationalError:
            continue
        if f and f[0]:
            return f[0]
    return ""


def _vivos() -> list[dict]:
    from congreso_live.detector import vivos_de_interes
    from congreso_live.resumenes_store import list_resumenes
    resumenes = list_resumenes()
    salida = []
    for v in vivos_de_interes():
        estado = agenda_pe._estado_transcripcion_vivo(v["id"])
        salida.append({"pais": v.get("pais") or "PE", "tipo": v["tipo"], "titulo": v["titulo"], "url": v["url"], "id": v["id"],
                       "minutos": int((estado or {}).get("duracion_seg") or 0) // 60 if estado else None,
                       "hora": (estado or {}).get("fetched_at"), "resumen": resumenes.get(v["id"])})
    return salida


# ------------------------------------------------------------------ Alertas, Buscar, Resumen
def _responder(cliente: str, historia: list, prompt: str) -> str:
    return responder(cliente, historia, prompt)


def _resumen() -> dict:
    conn = conexion()
    if conn is None:
        return {"nota": "El cerebro todavía no está publicado (lo arma el workflow «Cerebro» en GitHub)."}
    try:
        fila = conn.execute("SELECT fecha, texto FROM resumen_dia ORDER BY fecha DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        fila = None
    return {"fecha": fila[0], "texto": fila[1]} if fila else {"nota": "Todavía no hay resumen guardado. Usa el botón para armar el de hoy."}


def _buscar(a: dict) -> list[dict]:
    from cerebro.embeddings import buscar
    filas = buscar(a["q"], k=int(a["k"]), tipo=a["tipo_doc"] or None, pais=a["pais"] or None, conn=conexion())
    salida = []
    for r in filas:
        extra = json.loads(r["extra"] or "{}")
        salida.append({"tipo": r["tipo"], "pais": r["pais"], "fecha": r["fecha"], "url": r["url"], "titulo": r["titulo"],
                       "detalle": [str(v) for v in (extra.get("fuente"), extra.get("organo"), extra.get("tema"), extra.get("estado")) if v]})
    return salida


def _preguntar_cerebro(pregunta: str) -> str:
    from cerebro.grafo import descargar_si_falta, preguntar
    if not descargar_si_falta():
        return "El grafo todavía no está publicado (lo arma el workflow «Cerebro» en GitHub)."
    return preguntar(pregunta)


def _traer_en_vivo() -> None:
    """Lo que antes frenaba cada pagina con "Sincronizando...": ahora por detras."""
    for nombre, fn in (("pe", peru.fetch_live_pe), ("agenda pe", lambda: agenda_pe.fetch_live_agenda_pe(periodo_leg=dt.date.today().year)),
                       ("agenda ec", agenda_ec.fetch_live_agenda_ec), ("sync", peru.maybe_fire_background_sync)):
        try:
            fn()
        except Exception as e:
            print(f"[front] en vivo {nombre}: {e}")


SECCIONES = {
    "panel": panel, "transcripciones": transcripciones,  # el orden es el de armado al arrancar
    "proyectos_pe": proyectos_pe, "proyectos_ec": proyectos_ec,
    "agenda_pe": agenda_peru, "agenda_ec": agenda_ecuador,
    "noticias_pe": lambda: noticias("PE"), "noticias_ec": lambda: noticias("EC"),
    "tv_pe": lambda: tv("PE"), "tv_ec": lambda: tv("EC"),
}


def _sanar(e: Exception) -> bool:
    """Tras un push, Streamlit Cloud borra los modulos de sys.modules mientras
    otras sesiones importan (ver _importar en app.py). Este hilo vive entre
    recargas y puede quedar con un modulo a medio cargar: "module
    'alerts.que_paso_hoy' has no attribute 'hallazgos'" (3/11/2026) en cada
    vuelta. Se vuelve a importar y se cambia la referencia de este modulo."""
    m = re.match(r"module '([\w.]+)' has no attribute", str(e))
    if not isinstance(e, AttributeError) or not m:
        return False
    viejo = sys.modules.pop(m[1], None)
    nuevo = importlib.import_module(m[1])
    for k, v in list(globals().items()):
        if isinstance(v, types.ModuleType) and (v is viejo or v.__name__ == m[1]):
            globals()[k] = nuevo
    print(f"[front] {m[1]} reimportado tras: {e}")
    return True


def _armar(fn):
    try:
        return fn()
    except AttributeError as e:
        if not _sanar(e):
            raise
        return fn()


def _renovar(almacen: dict) -> None:
    while True:
        for nombre, fn in SECCIONES.items():
            t0 = time.time()
            try:
                datos = _armar(fn)
                if datos is not None:
                    almacen[nombre] = {"v": t0, "datos": datos}
            except Exception as e:
                print(f"[front] {nombre}: {type(e).__name__}: {e}")
                almacen.setdefault(nombre, {"error": f"{type(e).__name__}: {e}"})
            print(f"[front] {nombre} {time.time() - t0:.1f}s")
        completo = "panel" in almacen and not almacen["panel"]["datos"]["sin_cerebro"]
        _traer_en_vivo()
        time.sleep(CADA_SEG if completo else 20)


def _vigilar_vivos(almacen: dict) -> None:
    while True:
        try:
            almacen["vivos"] = {"v": time.time(), "datos": _vivos()}
        except Exception as e:
            print(f"[front] vivos: {e}")
        time.sleep(90)


@st.cache_resource
def almacen() -> dict:
    """Una por proceso, compartida entre sesiones."""
    d: dict = {}
    threading.Thread(target=_renovar, args=(d,), daemon=True).start()
    threading.Thread(target=_vigilar_vivos, args=(d,), daemon=True).start()
    return d


def atender(a: dict, usuario: str | None) -> dict | list | str | None:
    """Una peticion del navegador. Lo que falle vuelve como error y se muestra alla."""
    tipo = a["tipo"]
    if tipo == "seccion":
        hecha = almacen().get(a["nombre"])
        if hecha is None:
            return {"espera": True}
        from alerts import bandeja, pls_seguidos
        return {**hecha, "fuera": sorted(list_descartadas()), "bandeja": bandeja.estados(), "seguidos": sorted(pls_seguidos.lista())}
    if tipo == "texto":
        return _texto_video(a["video_id"])
    if tipo == "sesion_pe":
        pls = agenda_pe.load_pls_de_sesion(a["id"], fuente=a["fuente"])
        return {"pls": _filas(pls), "puntos": agenda_pe.load_puntos_agenda(a["id"], fuente=a["fuente"])}
    if tipo == "sesion_ec":
        descripcion, lugar, _f, _h = agenda_ec.load_descripcion(a["uid"])
        return {"descripcion": descripcion, "lugar": lugar, "pls": _filas(agenda_ec.load_pls_de_sesion(a["uid"]).drop(columns=["_score"], errors="ignore"))}
    if tipo == "pl_ec":
        return _detalle_pl_ec(a["pl"])
    if tipo == "pl_en_agendas":
        return _filas(agenda_pe.buscar_pl_en_agendas(int(a["num"])).drop(columns=["_id_sesion", "_raw"]))
    if tipo == "live_pe":
        peru.fetch_live_pe.clear()
        live = peru.fetch_live_pe()
        return {"error_api": live.get("error"), "nuevos": live.get("nuevos") or [], "total_api": live.get("total_api"), "total_db": live.get("total_db")}
    if tipo == "preguntar_sesion":
        from congreso_live.qa_chat import preguntar
        return preguntar(a["pregunta"], _texto_video(a["video_id"]), titulo=a["titulo"])
    if tipo == "descartar":
        registrar_descarte(int(a["id"]), usuario, a.get("titulo"), a.get("clientes"))
        pagina.load_noticias.clear()
    elif tipo == "ficha_pl":
        return ficha_pl(a["pais"], str(a["pl"]))
    elif tipo == "seguir_pl":
        from alerts import pls_seguidos
        if a.get("si"):
            pls_seguidos.seguir(a["pais"], str(a["pl"]), a["titulo"], a.get("estado"), a.get("url"), usuario)
        else:
            pls_seguidos.dejar(a["pais"], str(a["pl"]))
    elif tipo == "bandeja":
        from alerts import bandeja
        bandeja.marcar(a["clave"], a.get("estado"), usuario, a.get("titulo"))
    elif tipo == "deshacer":
        deshacer_descarte(int(a["id"]))
        pagina.load_noticias.clear()
    elif tipo == "combinadas":
        registrar_combinadas([int(i) for i in a["ids"]], usuario)
    elif tipo == "sugerencia":
        from clasificador.decisiones_store import registrar_decision
        registrar_decision(sugerencia_id=a["id"], decision=a["decision"])
        peru.sugerencias_pendientes.clear()
    elif tipo == "seguir":
        from alerts.seguimiento_store import set_seguidas
        set_seguidas(set(a["comisiones"]))
    elif tipo == "transcribir":
        from noticias.videos import pedir_transcripcion
        pedir_transcripcion(a["video_id"], a["autoridad"], a["pais"], a["titulo"])
    elif tipo == "borradores":
        return store.cargar(BORRADORES, [], ttl=30)
    elif tipo == "borrador_fuera":
        store.actualizar(BORRADORES, lambda bs: [b for b in bs if b.get("id") != a["id"]], f"alertas: borrador {a['id']} fuera", [])
    elif tipo == "chat_inicio":
        material = a["material"]
        primero = material["items"][0]
        contexto = contexto_relacionado(f"{primero['titulo']}. {primero.get('resumen') or ''}", pais=primero.get("pais"),
                                        excluir_url=primero.get("url"))
        prompt = mensaje_inicial(material, contexto)
        # con el prompt de vuelta aunque falle Gemini: si no, el material se pierde y no hay como reintentar
        try:
            return {"prompt": prompt, "respuesta": _responder(a["cliente"], [], prompt)}
        except Exception as e:
            return {"prompt": prompt, "error": str(e)}
    elif tipo == "chat":
        return {"respuesta": _responder(a["cliente"], a["historia"], a["prompt"])}
    elif tipo == "guardar_alerta":
        historial.agregar(a["cliente"], historial.entrada(a["titulo"], a["texto"], a["pais"], a["url"] or None, a["linea"] or None), autor=usuario)
        if a.get("borrador"):
            store.actualizar(BORRADORES, lambda bs: [b for b in bs if b.get("id") != a["borrador"]], f"alertas: borrador {a['borrador']} fuera", [])
    elif tipo == "buscar":
        return _buscar(a)
    elif tipo == "total_cerebro":
        conn = conexion()
        return conn.execute("SELECT count(*) FROM items").fetchone()[0] if conn else None
    elif tipo == "preguntar_cerebro":
        return _preguntar_cerebro(a["pregunta"])
    elif tipo == "resumen":
        return _resumen()
    elif tipo == "resumen_nuevo":
        m = q.material(conexion())
        return {"fecha": q._lima_ahora().strftime("%d/%m %H:%M"), "texto": q.escribir(m).strip(), "cuenta": {k: len(v) for k, v in m.items()}}
    else:
        raise ValueError(f"accion desconocida: {tipo}")
    return None
