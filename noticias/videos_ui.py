"""Pestaña "TV y entrevistas" de Noticias (PE/EC): entrevistas de autoridades en YouTube
(noticias/videos.py) y menciones en programas de TV (noticias/tv_monitor.py),
con el mismo formato de tarjetas que las paginas de Noticias. Pedido de
Nicolas 2026-09-28: sin reproductor de video, solo resumen y transcripcion,
como pestaña dentro de Noticias, igual que Agenda parlamentaria."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


_RAIZ = Path(__file__).resolve().parent.parent


def _q(conn, sql: str, params: tuple) -> pd.DataFrame:
    try:
        return pd.read_sql_query(sql, conn, params=params)
    except Exception:  # tablas todavia no creadas (primera corrida pendiente)
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def _historias(fragmentos: tuple[str, ...]) -> list[int]:
    from noticias.historias import agrupar
    # TF-IDF y no el modelo: cargarlo en Streamlit Cloud costaba ~600 MB por
    # abrir Noticias y tumbo la app por memoria (2026-09-29).
    return agrupar(list(fragmentos), modelo=False)


def _donde(r) -> tuple[str, str]:
    """("minuto 12:30" o "en vivo · 16:11", enlace al momento)."""
    mm, ss = divmod(int(r.t_seg), 60)
    hh, mm = divmod(mm, 60)
    if hh >= 12:
        # Escuchado en vivo en una señal de 24 h (tv_monitor.en_vivo): el
        # minuto desde que arranco la señal no sirve, se muestra la hora.
        hora = pd.Timestamp(r.first_seen_at).tz_convert("America/Lima").strftime("%H:%M")
        return f"en vivo · {hora}", f"https://www.youtube.com/watch?v={r.video_id}"
    minuto = f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"
    return f"minuto {minuto}", f"https://www.youtube.com/watch?v={r.video_id}&t={r.t_seg}s"
