"""Dashboard Streamlit para los proyectos de ley.

Corre con:
    streamlit run app.py

Lee proyectos.db (SQLite) en read-only. Filtros: tema, estado, comisión,
partido, proponente, búsqueda por título. Botón para forzar sync incremental.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "proyectos.db"
PAGE_SIZE_DEFAULT = 50

st.set_page_config(
    page_title="Proyectos de Ley — Congreso del Perú",
    page_icon="📜",
    layout="wide",
)


@st.cache_resource
def get_conn() -> sqlite3.Connection:
    if not DB_PATH.exists():
        st.error(f"No se encontró {DB_PATH}. Corre `python -m scraper.cli init` primero.")
        st.stop()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=60)
def load_catalogs() -> dict[str, list[str]]:
    conn = get_conn()
    cats = {
        "temas": sorted(
            {r[0] for r in conn.execute("SELECT DISTINCT tema FROM proyectos WHERE tema IS NOT NULL")}
        ),
        "estados": sorted(
            {r[0] for r in conn.execute("SELECT DISTINCT estado FROM proyectos WHERE estado IS NOT NULL")}
        ),
        "proponentes": sorted(
            {r[0] for r in conn.execute("SELECT DISTINCT proponente FROM proyectos WHERE proponente IS NOT NULL")}
        ),
        "partidos": sorted(
            {r[0] for r in conn.execute("SELECT DISTINCT grupo_parlamentario FROM proyectos WHERE grupo_parlamentario IS NOT NULL")}
        ),
        "comisiones": [
            {"id": r["comision_id"], "nombre": r["nombre"]}
            for r in conn.execute("SELECT comision_id, nombre FROM comisiones ORDER BY nombre")
        ],
    }
    return cats


@st.cache_data(ttl=60)
def query_proyectos(
    temas: tuple[str, ...],
    estados: tuple[str, ...],
    proponentes: tuple[str, ...],
    partidos: tuple[str, ...],
    comision_id: int | None,
    texto: str,
    limit: int,
) -> pd.DataFrame:
    conn = get_conn()
    sql = """
      SELECT p.pley_num, p.proyecto_ley, p.titulo, p.sumilla, p.estado,
             p.proponente, p.grupo_parlamentario AS partido,
             p.tema, p.tema_manual, p.fec_presentacion, p.last_changed_at,
             p.url_portal, p.url_pdf,
             (SELECT GROUP_CONCAT(pc.nombre, ' | ') FROM proyecto_comision pc
              WHERE pc.per_par_id=p.per_par_id AND pc.pley_num=p.pley_num) AS comisiones
      FROM proyectos p
    """
    clauses, params = [], []
    if temas:
        clauses.append(f"p.tema IN ({','.join('?' * len(temas))})")
        params.extend(temas)
    if estados:
        clauses.append(f"p.estado IN ({','.join('?' * len(estados))})")
        params.extend(estados)
    if proponentes:
        clauses.append(f"p.proponente IN ({','.join('?' * len(proponentes))})")
        params.extend(proponentes)
    if partidos:
        clauses.append(f"p.grupo_parlamentario IN ({','.join('?' * len(partidos))})")
        params.extend(partidos)
    if comision_id:
        clauses.append(
            "EXISTS (SELECT 1 FROM proyecto_comision pc WHERE pc.per_par_id=p.per_par_id "
            "AND pc.pley_num=p.pley_num AND pc.comision_id=?)"
        )
        params.append(comision_id)
    if texto:
        clauses.append("(LOWER(p.titulo) LIKE ? OR LOWER(p.sumilla) LIKE ?)")
        like = f"%{texto.lower()}%"
        params.extend([like, like])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY p.fec_presentacion DESC LIMIT ?"
    params.append(limit)
    return pd.read_sql_query(sql, conn, params=params)


@st.cache_data(ttl=60)
def kpi_totals() -> dict[str, int]:
    conn = get_conn()
    r = conn.execute(
        "SELECT COUNT(*) c, "
        "       SUM(CASE WHEN estado='PRESENTADO' THEN 1 ELSE 0 END) presentados, "
        "       SUM(CASE WHEN estado='EN COMISIÓN' THEN 1 ELSE 0 END) en_comision, "
        "       SUM(CASE WHEN estado='DICTAMEN' THEN 1 ELSE 0 END) dictamen, "
        "       SUM(CASE WHEN estado='AUTÓGRAFA' THEN 1 ELSE 0 END) autografa, "
        "       SUM(CASE WHEN estado='PUBLICADO EL PERUANO' OR estado='LEY PUBLICADA' THEN 1 ELSE 0 END) ley "
        "FROM proyectos"
    ).fetchone()
    return {
        "Total": r["c"],
        "Presentados": r["presentados"] or 0,
        "En comisión": r["en_comision"] or 0,
        "Con dictamen": r["dictamen"] or 0,
        "Autógrafas": r["autografa"] or 0,
        "Ley publicada": r["ley"] or 0,
    }


@st.cache_data(ttl=60)
def last_sync() -> dict | None:
    conn = get_conn()
    r = conn.execute(
        "SELECT started_at, finished_at, proyectos_nuevos, proyectos_actualizados, errores, mensaje "
        "FROM sync_runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(r) if r else None


def run_update_now() -> tuple[int, str]:
    """Lanza el sync incremental en proceso aparte y devuelve (returncode, output)."""
    cmd = [sys.executable, "-m", "scraper.cli", "update"]
    res = subprocess.run(cmd, cwd=str(Path(__file__).parent), capture_output=True, text=True, timeout=600)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


# ============ UI ============

st.title("📜 Proyectos de Ley — Congreso del Perú")
st.caption("Período 2021-2026 · datos desde api.congreso.gob.pe · clasificación temática híbrida (Excel + reglas)")

cats = load_catalogs()

# ---------- Sidebar ----------
with st.sidebar:
    st.header("Filtros")
    f_temas = st.multiselect("Tema", cats["temas"])
    f_estados = st.multiselect("Estado", cats["estados"])
    f_partidos = st.multiselect("Partido / Bancada", cats["partidos"])
    f_proponentes = st.multiselect("Proponente", cats["proponentes"])
    f_comision = st.selectbox(
        "Comisión",
        options=[None] + cats["comisiones"],
        format_func=lambda x: "(todas)" if x is None else x["nombre"],
    )
    f_comision_id = f_comision["id"] if f_comision else None
    f_texto = st.text_input("Buscar en título / sumilla")
    limit = st.slider("Máximo de resultados", 50, 2000, 200, step=50)

    st.markdown("---")
    st.subheader("Sync")
    last = last_sync()
    if last:
        st.caption(f"Último run: {last['started_at']}\n\nNuevos: {last['proyectos_nuevos']}  ·  Actualizados: {last['proyectos_actualizados']}  ·  Errores: {last['errores']}")
    if st.button("🔄 Actualizar ahora"):
        with st.spinner("Corriendo `scraper update`..."):
            code, out = run_update_now()
        if code == 0:
            st.success("Sync OK")
            st.cache_data.clear()
        else:
            st.error("Falló el sync — revisa el log")
        with st.expander("Output"):
            st.code(out)

# ---------- KPIs ----------
totals = kpi_totals()
cols = st.columns(len(totals))
for col, (label, val) in zip(cols, totals.items()):
    col.metric(label, f"{val:,}")

# ---------- Tabla ----------
df = query_proyectos(
    tuple(f_temas),
    tuple(f_estados),
    tuple(f_proponentes),
    tuple(f_partidos),
    f_comision_id,
    f_texto.strip(),
    limit,
)

st.markdown(f"### Resultados: **{len(df):,}** proyecto(s)")

if df.empty:
    st.info("No hay proyectos que cumplan los filtros.")
else:
    df_display = df.copy()
    df_display["Presentado"] = pd.to_datetime(df_display["fec_presentacion"]).dt.strftime("%Y-%m-%d")
    df_display["Último cambio"] = pd.to_datetime(df_display["last_changed_at"], errors="coerce").dt.strftime("%Y-%m-%d")
    df_display = df_display.rename(columns={
        "proyecto_ley": "PL",
        "titulo": "Título",
        "estado": "Estado",
        "tema": "Tema",
        "partido": "Partido",
        "proponente": "Proponente",
        "comisiones": "Comisión",
        "url_portal": "Portal",
        "url_pdf": "PDF",
    })
    st.dataframe(
        df_display[["PL","Tema","Estado","Presentado","Último cambio","Partido","Proponente","Comisión","Título","Portal","PDF"]],
        hide_index=True,
        use_container_width=True,
        height=520,
        column_config={
            "Portal": st.column_config.LinkColumn("Portal", display_text="abrir"),
            "PDF":    st.column_config.LinkColumn("PDF",    display_text="ver"),
            "Título": st.column_config.TextColumn("Título", width="large"),
            "Comisión": st.column_config.TextColumn("Comisión", width="medium"),
        },
    )

    # Detalle expandible
    st.markdown("### Detalle de un proyecto")
    pleys = df["pley_num"].astype(str).tolist()
    pick = st.selectbox("Selecciona PL", options=pleys)
    if pick:
        row = df[df["pley_num"].astype(str) == pick].iloc[0]
        st.markdown(f"**{row['proyecto_ley']}** — {row['titulo']}")
        meta_cols = st.columns(4)
        meta_cols[0].markdown(f"**Estado:** {row['estado']}")
        meta_cols[1].markdown(f"**Tema:** {row['tema']} {'*' if row['tema_manual'] else ''}")
        meta_cols[2].markdown(f"**Partido:** {row['partido'] or '-'}")
        meta_cols[3].markdown(f"**Proponente:** {row['proponente'] or '-'}")
        if pd.notna(row["sumilla"]) and row["sumilla"]:
            st.markdown("**Sumilla:**")
            st.write(row["sumilla"])
        # seguimientos
        conn = get_conn()
        segs = conn.execute(
            "SELECT fecha, estado, comisiones, observacion FROM seguimientos "
            "WHERE per_par_id=2021 AND pley_num=? ORDER BY fecha DESC",
            (int(row["pley_num"]),),
        ).fetchall()
        if segs:
            st.markdown("**Historial:**")
            seg_df = pd.DataFrame([dict(s) for s in segs])
            seg_df["fecha"] = pd.to_datetime(seg_df["fecha"]).dt.strftime("%Y-%m-%d")
            st.dataframe(seg_df, hide_index=True, use_container_width=True)
        links_cols = st.columns(2)
        if row.get("url_portal"):
            links_cols[0].markdown(f"[Abrir en el portal del Congreso]({row['url_portal']})")
        if row.get("url_pdf"):
            links_cols[1].markdown(f"[Descargar PDF]({row['url_pdf']})")

# Footer
st.markdown("---")
st.caption(
    "Datos: api.congreso.gob.pe/spley-portal-service · "
    "Clasificación temática híbrida (Excel + reglas keyword-based con overrides Tecnología/Farma). "
    "Repositorio: github.com/nicosil02/Base_legislativa"
)
