"""Seccion "Videos de autoridades" de las paginas de Noticias PE/EC.
Ver noticias/videos.py para de donde salen los videos y como se
transcriben."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from congreso_live.resumenes_store import list_resumenes
from noticias.videos import PEDIDOS_DIR, pedir_transcripcion

_RAIZ = Path(__file__).resolve().parent.parent


def _cargar(conn: sqlite3.Connection, pais: str) -> pd.DataFrame:
    try:
        return pd.read_sql_query(
            """SELECT v.video_id, v.autoridad, v.cargo, v.titulo, v.canal, v.duracion_seg,
                      v.first_seen_at, t.texto
               FROM videos_autoridades v
               LEFT JOIN sesiones_transcripciones t ON t.video_id = v.video_id
               WHERE v.pais = ? AND v.first_seen_at >= datetime('now', '-14 days')
               ORDER BY v.first_seen_at DESC, v.autoridad""",
            conn, params=(pais,))
    except Exception:  # tabla todavia no creada (primera corrida de backfill-auto pendiente)
        return pd.DataFrame()


def render(conn: sqlite3.Connection, pais: str) -> None:
    st.markdown("---")
    st.markdown("##### 🎥 Videos de autoridades")
    st.caption("Entrevistas y declaraciones en YouTube (TV, radio, medios) de las autoridades "
               "que seguimos, subidas en los últimos días. Se actualiza cada 6 horas.")
    df = _cargar(conn, pais)
    if df.empty:
        st.info("Todavía no hay videos. La primera búsqueda corre con el próximo backfill automático.")
        return

    autoridades = ["Todas"] + sorted(df["autoridad"].unique())
    sel = st.selectbox("Autoridad", autoridades, key=f"videos_aut_{pais}")
    if sel != "Todas":
        df = df[df["autoridad"] == sel]

    resumenes = list_resumenes()
    pedidos_ss = st.session_state.setdefault("videos_pedidos", set())

    for r in df.head(40).itertuples():
        url = f"https://www.youtube.com/watch?v={r.video_id}"
        mins = int((r.duracion_seg or 0) // 60)
        transcrito = isinstance(r.texto, str) and bool(r.texto)
        pedido = r.video_id in pedidos_ss or (_RAIZ / PEDIDOS_DIR / f"{r.video_id}.json").exists()
        estado = "✅ Transcrito" if transcrito else ("⏳ En cola" if pedido else "")
        with st.expander(f"{r.autoridad} · {r.titulo}  ({mins} min) {estado}"):
            st.markdown(f"[Abrir en YouTube]({url}) · {r.canal or ''} · {r.cargo or ''}")
            st.video(url)
            if transcrito:
                res = resumenes.get(r.video_id)
                if res:
                    st.markdown("**Resumen**")
                    st.write(res.get("resumen", ""))
                    for idea in res.get("ideas_clave", []):
                        st.markdown(f"- {idea}")
                else:
                    st.caption("El resumen se genera en la próxima corrida de la rutina de resúmenes.")
                st.download_button("Descargar transcripción (.txt)",
                                   data=f"{r.titulo}\n{url}\n\n{r.texto}",
                                   file_name=f"{r.autoridad} - {r.video_id}.txt".replace(" ", "_"),
                                   key=f"dl_{r.video_id}")
            elif pedido:
                st.caption("Pedido enviado. Tarda de 10 a 40 minutos según la duración del video.")
            elif st.button("Transcribir y resumir", key=f"tr_{r.video_id}"):
                try:
                    pedir_transcripcion(r.video_id, r.autoridad, pais, r.titulo)
                    pedidos_ss.add(r.video_id)
                    st.success("Pedido enviado. Tarda de 10 a 40 minutos según la duración del video.")
                except Exception as e:
                    st.error(f"No se pudo pedir la transcripción: {e}")
