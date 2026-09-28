"""Radar Legislativo - Ecuador - TV y entrevistas. Ver noticias/videos_ui.py."""
import sqlite3
from pathlib import Path

import streamlit as st

from noticias.videos_ui import pagina

_RAIZ = Path(__file__).resolve().parent.parent
_db = _RAIZ / "proyectos.db"
if not _db.exists():
    st.error("No encuentro proyectos.db.")
    st.stop()
_clientes = sorted(p.name for p in (_RAIZ / "clientes").iterdir()
                   if p.is_dir() and not p.name.startswith("_") and not p.name.startswith("__"))
pagina(sqlite3.connect(f"file:{_db}?mode=ro&immutable=1", uri=True, check_same_thread=False),
       "EC", "Ecuador", _clientes)
