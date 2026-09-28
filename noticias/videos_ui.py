"""Pagina "TV y entrevistas" (PE/EC): entrevistas de autoridades en YouTube
(noticias/videos.py) y menciones en programas de TV (noticias/tv_monitor.py),
con el mismo formato de tarjetas que las paginas de Noticias. Pedido de
Nicolas 2026-09-28: sin reproductor de video, solo resumen y transcripcion,
en su propia pagina (no arriba de Noticias)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from alerts.borradores_store import marcar_pendiente
from congreso_live.resumenes_store import list_resumenes
from noticias.videos import PEDIDOS_DIR, pedir_transcripcion
from ui_kit import inject_theme

_RAIZ = Path(__file__).resolve().parent.parent
VENTANAS = {"Últimos 3 días": 3, "Última semana": 7, "Últimas 2 semanas": 14}

_CSS = """<style>
.block-container { padding-top:2rem; padding-bottom:4rem; max-width:1400px; }
.country-eyebrow { font-size:11px; font-weight:800; letter-spacing:0.25em;
  text-transform:uppercase; color:var(--accent); margin-bottom:12px; }
.country-title { font-family: Georgia, 'Times New Roman', serif;
  font-size:clamp(2.5rem,5vw,3.75rem); font-weight:400; letter-spacing:-0.01em;
  line-height:0.98; color:var(--ink); margin:0 0 10px 0; }
.country-title .accent { color:var(--accent); }
.country-subtitle { font-size:1.15rem; color:var(--ink-soft); line-height:1.6; margin-bottom:36px; }
.categoria-eyebrow { font-size:11px; font-weight:800; letter-spacing:0.18em;
  text-transform:uppercase; color:var(--accent); margin: 30px 0 6px 0; }
.noticia-card { border: 1px solid var(--line-soft); border-radius: 10px; padding: 14px 16px; margin: 8px 0; }
.noticia-card:hover { border-color: var(--accent); }
.noticia-fuente { font-size:11px; font-weight:700; color:var(--ink-mute);
  text-transform:uppercase; letter-spacing:0.06em; }
.noticia-titulo { font-size:15px; font-weight:700; color:var(--ink); line-height:1.35; margin: 4px 0; }
.noticia-titulo a { color:var(--ink); text-decoration: none; }
.noticia-titulo a:hover { color: var(--accent-red); text-decoration: underline; }
.noticia-resumen { font-size:13px; color:var(--ink-soft); line-height:1.45; margin-top:4px; }
</style>"""


def _chips(etiquetas: list[str]) -> str:
    return "".join(
        f'<span style="display:inline-block;background:#EEF2F6;color:var(--ink);font-size:10px;'
        f'font-weight:700;letter-spacing:.04em;padding:2px 8px;border-radius:999px;'
        f'margin-right:6px;margin-top:6px;">{e}</span>' for e in etiquetas if e)


def _card(fuente: str, fecha: str, titulo: str, url: str, cuerpo: str, etiquetas: list[str]) -> None:
    st.markdown(
        f'<div class="noticia-card"><div class="noticia-fuente">{fuente} · {fecha[:10]}</div>'
        f'<div class="noticia-titulo"><a href="{url}" target="_blank" rel="noopener">{titulo}</a></div>'
        + (f'<div class="noticia-resumen">{cuerpo}</div>' if cuerpo else "")
        + f'<div style="margin-top:6px;">{_chips(etiquetas)}</div></div>',
        unsafe_allow_html=True)


def _marcar(key: str, pais: str, titulo: str, url: str, resumen: str | None, clientes: list[str]) -> None:
    with st.popover("📌 Marcar", help="Marcar para que se redacte una alerta de esto"):
        sel = st.multiselect("¿Para qué cliente(s)?", clientes, placeholder="Elige uno o más clientes",
                             key=f"marcar_cli_{key}")
        if st.button("Marcar", key=f"marcar_btn_{key}", disabled=not sel):
            try:
                email = st.user.get("email")
            except Exception:
                email = None
            marcar_pendiente(clientes=sel, item_id=key, item_tipo="video", pais=pais,
                             item_titulo=titulo, item_url=url, item_resumen=resumen, creado_por=email)
            st.success(f"Marcado para: {', '.join(sel)}.")


def _transcripcion(key: str, titulo: str, url: str, texto: str, nombre: str) -> None:
    with st.expander("Ver transcripción"):
        st.download_button("Descargar (.txt)", data=f"{titulo}\n{url}\n\n{texto}",
                           file_name=nombre.replace(" ", "_") + ".txt", key=f"dl_{key}")
        st.markdown(f'<div style="font-size:13px;line-height:1.55;white-space:pre-wrap;'
                    f'max-height:420px;overflow-y:auto;">{texto}</div>', unsafe_allow_html=True)


def _q(conn, sql: str, params: tuple) -> pd.DataFrame:
    try:
        return pd.read_sql_query(sql, conn, params=params)
    except Exception:  # tablas todavia no creadas (primera corrida pendiente)
        return pd.DataFrame()


def pagina(conn: sqlite3.Connection, pais: str, pais_label: str, clientes: list[str]) -> None:
    inject_theme()
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown('<div class="country-eyebrow">Radar Legislativo · TV y entrevistas</div>',
                unsafe_allow_html=True)
    st.markdown(f'<h1 class="country-title"><span class="accent">{pais_label}</span> · '
                f'TV y entrevistas</h1>', unsafe_allow_html=True)
    st.markdown('<p class="country-subtitle">Entrevistas de las autoridades que seguimos en medios '
                'de TV y radio, y lo que se dijo en los programas de noticias sobre ellas y sobre '
                'los temas de los clientes. Se lee lo que los medios publican en YouTube.</p>',
                unsafe_allow_html=True)

    f = st.columns([1, 1.4, 2.2])
    dias = VENTANAS[f[0].selectbox("Ventana", list(VENTANAS), index=1)]
    desde = f"-{dias} days"
    videos = _q(conn, """SELECT v.video_id, v.autoridad, v.cargo, v.titulo, v.canal, v.duracion_seg,
                                v.first_seen_at, t.texto
                         FROM videos_autoridades v
                         LEFT JOIN sesiones_transcripciones t ON t.video_id = v.video_id
                         WHERE v.pais = ? AND v.first_seen_at >= datetime('now', ?)
                         ORDER BY (t.texto IS NULL), v.first_seen_at DESC, v.duracion_seg DESC""",
                (pais, desde))
    menciones = _q(conn, """SELECT m.video_id, m.t_seg, m.canal, m.titulo, m.terminos, m.fragmento,
                                   m.first_seen_at, v.texto
                            FROM tv_menciones m LEFT JOIN tv_vistos v ON v.video_id = m.video_id
                            WHERE m.pais = ? AND m.first_seen_at >= datetime('now', ?)
                            ORDER BY m.first_seen_at DESC, m.video_id, m.t_seg""", (pais, desde))

    if not videos.empty:  # filas guardadas antes del filtro de medios formales
        from noticias.videos import MEDIOS, _norm
        videos = videos[videos["canal"].map(lambda c: any(m in _norm(c) for m in MEDIOS))]
    etiquetas = set(videos["autoridad"]) if not videos.empty else set()
    if not menciones.empty:
        etiquetas |= {t.strip() for ts in menciones["terminos"] for t in ts.split(",")}
    sel = f[1].selectbox("Autoridad o tema", ["Todos"] + sorted(etiquetas))
    buscar = f[2].text_input("Buscar en título o texto", placeholder="ej. facultades, Senasa")
    if sel != "Todos":
        if not videos.empty:
            videos = videos[videos["autoridad"] == sel]
        if not menciones.empty:
            menciones = menciones[menciones["terminos"].str.contains(sel, regex=False)]
    if buscar:
        b = buscar.lower()
        if not videos.empty:
            videos = videos[videos["titulo"].str.lower().str.contains(b, regex=False)
                            | videos["texto"].fillna("").str.lower().str.contains(b, regex=False)]
        if not menciones.empty:
            menciones = menciones[menciones["titulo"].str.lower().str.contains(b, regex=False)
                                  | menciones["fragmento"].str.lower().str.contains(b, regex=False)]

    k = st.columns(3)
    k[0].metric("Entrevistas", len(videos))
    k[1].metric("Transcritas", int(videos["texto"].notna().sum()) if not videos.empty else 0)
    k[2].metric("Menciones en TV", len(menciones))

    resumenes = list_resumenes()
    pedidos_ss = st.session_state.setdefault("videos_pedidos", set())

    st.markdown(f'<div class="categoria-eyebrow">Entrevistas de autoridades '
                f'<span style="color:var(--ink-mute);font-weight:500;">· {len(videos)}</span></div>',
                unsafe_allow_html=True)
    if videos.empty:
        st.info("Sin entrevistas con esos filtros.")
    for r in videos.head(60).itertuples():
        url = f"https://www.youtube.com/watch?v={r.video_id}"
        transcrito = isinstance(r.texto, str) and bool(r.texto)
        res = resumenes.get(r.video_id) or {}
        if res:
            cuerpo = res.get("resumen", "") + "".join(f"<br>• {i}" for i in res.get("ideas_clave", []))
        elif transcrito:
            cuerpo = "Transcrita. El resumen se genera en la próxima hora."
        else:
            cuerpo = ""
        _card(r.canal or "", r.first_seen_at, r.titulo, url, cuerpo,
              [r.autoridad, f"{int((r.duracion_seg or 0) // 60)} min"])
        c = st.columns([6, 2, 2])
        with c[1]:
            _marcar(f"video_{r.video_id}", pais, r.titulo, url, res.get("resumen"), clientes)
        pedido = r.video_id in pedidos_ss or (_RAIZ / PEDIDOS_DIR / f"{r.video_id}.json").exists()
        if transcrito:
            _transcripcion(r.video_id, r.titulo, url, r.texto, f"{r.autoridad} - {r.video_id}")
        elif pedido:
            c[2].caption("⏳ Transcribiendo (10 a 40 min)")
        elif c[2].button("Transcribir y resumir", key=f"tr_{r.video_id}"):
            try:
                pedir_transcripcion(r.video_id, r.autoridad, pais, r.titulo)
                pedidos_ss.add(r.video_id)
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo pedir la transcripción: {e}")

    st.markdown(f'<div class="categoria-eyebrow">Menciones en programas de TV '
                f'<span style="color:var(--ink-mute);font-weight:500;">· {len(menciones)}</span></div>',
                unsafe_allow_html=True)
    if menciones.empty:
        st.info("Sin menciones con esos filtros.")
    for r in menciones.head(80).itertuples():
        url = f"https://www.youtube.com/watch?v={r.video_id}&t={r.t_seg}s"
        mm, ss = divmod(int(r.t_seg), 60)
        hh, mm = divmod(mm, 60)
        minuto = f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"
        frag = r.fragmento if len(r.fragmento) <= 700 else r.fragmento[:700] + "…"
        _card(f"{r.canal} · minuto {minuto}", r.first_seen_at, r.titulo, url, f"«{frag}»",
              r.terminos.split(", "))
        c = st.columns([6, 2, 2])
        with c[1]:
            _marcar(f"tv_{r.video_id}_{r.t_seg}", pais, r.titulo, url, r.fragmento, clientes)
        if isinstance(r.texto, str) and r.texto:
            _transcripcion(f"{r.video_id}_{r.t_seg}", r.titulo, url, r.texto, f"{r.canal} - {r.video_id}")
