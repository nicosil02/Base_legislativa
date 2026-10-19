"""Radar Legislativo - Peru - Agenda de Comisiones.

Vista de sesiones convocadas y realizadas de las comisiones del Congreso del Peru
con cruce automatico contra la base de proyectos de ley.

Fuente: API service-portal-publico-ext (visor-sesiones del Congreso).
DB: tablas sesion_* / sesiones en proyectos.db (compartida con el scraper PE).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from scraper.sync import FECHA_INICIO_BICAMERAL
from scraper.categorias import CATEGORIA_CLIENTES_PL
from alerts import armar, historial
from ui_kit import AGENDA_CSS, inject_theme
from consultas.agenda_pe import (
    has_mesas_table,
    load_mesas,
    load_transcripciones,
    _estado_transcripcion_vivo,
    fetch_live_agenda_pe,
    has_sesiones_table,
    load_catalogs,
    kpi_totals,
    load_sesiones,
    buscar_pl_en_agendas,
    load_pls_de_sesion,
    load_pls_por_comision,
    load_puntos_agenda,
)
from consultas import hora_a_minutos, matriz_pls



# ====================== CSS (estetica Vali, identica a Peru) ======================
inject_theme()
st.markdown(AGENDA_CSS, unsafe_allow_html=True)


# La columna "Nº PL" funciona como LinkColumn donde la celda contiene la URL
# completa al portal. Para que el TEXTO clickeable muestre el formato del PL
# (ej "14093/2025-CR") en vez del numero crudo, codificamos el label como
# query param ?pl=... antes del hash (el Angular del portal ignora el query
# string y lee el path real en el fragment #/expediente/...).
# display_text regex extrae el contenido del param ?pl=.
URL_TEMPLATE = (
    "https://wb2server.congreso.gob.pe/spley-portal/?pl={label}"
    "#/expediente/{per_par_id}/{pley_num}"
)


# ====================== UI ======================

st.markdown('<div class="country-eyebrow">Radar Legislativo · Agenda parlamentaria</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="country-title"><span class="accent">Perú</span> · Agenda parlamentaria '
    '<span class="period">(2026–2031, bicameral)</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Sesiones convocadas y realizadas de las comisiones del '
    '<strong>Senado</strong> y la <strong>Cámara de Diputados</strong> (período vigente '
    '2026–2031) y del <strong>Pleno</strong> del Congreso del Perú. Cada sesión y agenda del '
    'Pleno cruza con la base de proyectos de ley para identificar automáticamente qué PLs '
    'están en discusión y enriquecerlos con tema, estado y bancada. Usa el filtro "Cámara" '
    'para distinguir entre Senado, Diputados y Congreso/Pleno.</p>',
    unsafe_allow_html=True,
)

from consultas.camara_pe import (  # noqa: E402
    _DIPUTADOS_COMISIONES_ORDEN, _SENADO_COMISIONES_ORDEN, _clasificar_camara,
    _tipo_de_comision_oficial, load_sesiones_youtube,
)


# ---------- En vivo ahora (YouTube: Pleno + comisiones ordinarias) ----------
@st.cache_data(ttl=90)
def _vivos_ahora() -> list[dict]:
    """Sesiones EN VIVO ahora mismo en el canal de YouTube del Congreso -
    reusa congreso_live.detector (misma deteccion que ya corre cada rato
    via GH Actions para el aviso de WhatsApp personal existente), cacheado
    90s para no pegarle a YouTube en cada rerun de Streamlit."""
    try:
        from congreso_live.detector import vivos_de_interes
        # El Pleno de Ecuador sale por el mismo detector - va en Agenda EC.
        return [v for v in vivos_de_interes() if v.get("pais") != "EC"]
    except Exception as e:
        print(f"[agenda-pe] no se pudo chequear en vivo: {e}")
        return []

_vivos = _vivos_ahora()
if _vivos:
    _items_html = "".join(
        f'<div class="live-item"><span class="live-dot"></span>'
        f'<a href="{v["url"]}" target="_blank">{v["tipo"]}</a>'
        f'<span class="live-titulo"> — {v["titulo"][:90]}</span></div>'
        for v in _vivos
    )
    st.markdown(
        f'<div class="live-banner">'
        f'<div class="live-banner-title">🔴 En vivo ahora en YouTube</div>'
        f'{_items_html}'
        f'</div>',
        unsafe_allow_html=True,
    )

if not has_sesiones_table():
    st.warning(
        "Las tablas de sesiones todavía no existen en la DB. "
        "Inicializá corriendo:\n\n"
        "```\npython -m sesiones.cli init\npython -m sesiones.cli update\n```"
    )
    st.stop()

# ---------- Live sync (tiempo real automatico) ----------
# Al cargar, consulta API visor-sesiones y auto-upsert los nuevos a la
# DB → aparecen en la tabla principal sin clic.
import datetime as _dt
_anio_actual = _dt.date.today().year
with st.spinner("Sincronizando agenda en vivo con el Congreso..."):
    try:
        _live = fetch_live_agenda_pe(periodo_leg=_anio_actual)
    except Exception as _e:
        _live = {"error": str(_e), "inserted": 0, "total_api": 0, "total_db": 0}

if _live.get("inserted", 0) > 0:
    st.cache_data.clear()
    st.toast(
        f"⚡ {_live['inserted']} sesión{'es' if _live['inserted'] != 1 else ''} "
        f"nueva{'s' if _live['inserted'] != 1 else ''} sincronizada{'s' if _live['inserted'] != 1 else ''} "
        f"en vivo desde la API",
        icon="✅",
    )

# ---------- KPIs ----------
# Recortado de 5 a 4: "Referencias totales" duplicaba conceptualmente a
# "PLs únicos referenciados" (una cuenta cruda de menciones vs. la cuenta
# de PLs distintos) sin agregar una decisión nueva - puro ruido en la
# franja mas visible de la pagina. Los 4 que quedan responden preguntas
# reales: cuanto hay, que viene, que ya paso, cuantos PLs distintos.
totals = kpi_totals()
totals.pop("Referencias totales", None)
cols = st.columns(len(totals))
for col, (label, val) in zip(cols, totals.items()):
    col.metric(label, f"{val:,}")

st.markdown("")

# ---------- Buscador rapido por numero de PL ----------
# Escribe un numero (ej. "1000") y muestra todas las sesiones donde ese PL
# aparecio en agenda: comision, fecha, contexto. Atajo para la pregunta
# "¿en que comision se vio el PL X y cuando?".
st.markdown("##### Buscar Proyecto de Ley en agendas")
sb = st.columns([1.5, 5])
pl_query = sb[0].text_input(
    "Nº de PL", value="", placeholder="ej. 1000",
    label_visibility="collapsed",
    help="Ingresa el número del proyecto de ley (solo el número, sin /año-grupo). "
         "Muestra en qué comisión y cuándo apareció en agenda.",
)
if pl_query.strip():
    try:
        pl_num = int(pl_query.strip().split("/")[0])
    except ValueError:
        sb[1].warning(f"'{pl_query}' no es un número válido. Ingresa solo dígitos (ej. 1000).")
    else:
        df_pl = buscar_pl_en_agendas(pl_num)
        if df_pl.empty:
            sb[1].info(f"PL {pl_num} no aparece en ninguna sesión registrada.")
        else:
            n_com = df_pl["Comisión"].nunique()
            titulo = df_pl["Título del PL"].iloc[0]
            sb[1].markdown(
                f"**PL {pl_num}** · {len(df_pl)} aparición(es) en {n_com} comisión(es)  \n"
                f"<span style='color:#435D74;font-size:13px'>{titulo}</span>",
                unsafe_allow_html=True,
            )
            st.dataframe(
                df_pl.drop(columns=["_id_sesion", "_raw"]),
                hide_index=True,
                use_container_width=True,
                height=min(420, 90 + 55 * len(df_pl)),
                row_height=60,
                column_config={
                    "Fecha":          st.column_config.TextColumn("Fecha", width="small"),
                    "Hora":           st.column_config.TextColumn("Hora", width="small"),
                    "Comisión":       st.column_config.TextColumn("Comisión", width="medium"),
                    "Tipo":           st.column_config.TextColumn("Tipo", width="small"),
                    "Estado sesión":  st.column_config.TextColumn("Estado sesión", width="small"),
                    "Sesión":         st.column_config.TextColumn("Sesión", width="medium"),
                    "Contexto en agenda": st.column_config.TextColumn("Contexto", width="large"),
                    "Título del PL":  st.column_config.TextColumn("Título", width="large"),
                    "Tema":           st.column_config.TextColumn("Tema", width="small"),
                    "Estado del PL":  st.column_config.TextColumn("Estado PL", width="small"),
                },
            )
    st.markdown("---")

cats = load_catalogs()

# ---------- Sidebar: rango fechas ----------
with st.sidebar:
    st.markdown("### Rango de fechas")
    today = dt.date.today()
    default_fin = today + dt.timedelta(days=30)
    fec_min_iso = cats["fec_min"] or "2023-08-15"
    fec_max_iso = cats["fec_max"] or default_fin.isoformat()
    fec_min = dt.date.fromisoformat(fec_min_iso)
    fec_max = max(dt.date.fromisoformat(fec_max_iso), default_fin)
    # Default cubre todo el historico (desde 15-ago-2023) hasta proximos 30 dias.
    # La DB tiene ~2.100 sesiones; pandas + Streamlit lo aguantan sin problema.
    # El usuario puede arrastrar el rango si solo le interesa lo reciente.
    rango = st.date_input(
        "Sesión",
        value=(fec_min, today + dt.timedelta(days=30)),
        min_value=fec_min,
        max_value=fec_max,
        format="YYYY-MM-DD",
    )
    if isinstance(rango, tuple) and len(rango) == 2:
        f_ini, f_fin = rango
    else:
        f_ini, f_fin = fec_min, fec_max

# ---------- Tabla principal ----------
df_full = load_sesiones(f_ini, f_fin)
# Sesiones que el Congreso transmitio pero no cargo en su visor (ver
# load_sesiones_youtube). Se cruzan por (fecha, camara, tipo de comision).
_ya_en_agenda = frozenset(
    (r["Fecha"], r["Cámara"], _tipo_de_comision_oficial(r["Comisión"]), hora_a_minutos(r["Hora"]))
    for _, r in df_full[(df_full["_fuente"] == "comision")
                        & (df_full["Fecha"] >= FECHA_INICIO_BICAMERAL)].iterrows()
)
_df_yt = load_sesiones_youtube(f_ini, f_fin, _ya_en_agenda)
if not _df_yt.empty:
    df_full = pd.concat([df_full, _df_yt], ignore_index=True)
    df_full["_hora_min"] = df_full["Hora"].apply(hora_a_minutos)
    df_full = df_full.sort_values(["Fecha", "_hora_min"], ascending=[False, False],
                                  kind="mergesort").drop(columns=["_hora_min"]).reset_index(drop=True)

TODOS = "Todas"

def _opciones(col: str, base: pd.DataFrame | None = None) -> list[str]:
    base = df_full if base is None else base
    if col not in base.columns:
        return [TODOS]
    return [TODOS] + sorted({str(v) for v in base[col].dropna().unique() if str(v).strip()})


# ---------- Pestañas: 4 herramientas distintas, una vista a la vez ----------
# Antes vivian las 4 apiladas en un solo scroll (filtros de agenda +
# tabla + detalle + vista por comision + mesas tecnicas + transcripciones).
# Cada una es una tarea distinta; mostrarlas todas a la vez es lo que
# hacia la pagina sentirse sobrecargada. Ahora se ve una a la vez.
tab_agenda, tab_comision, tab_mesas, tab_transcripciones, tab_seguimiento = st.tabs(
    ["Agenda", "Por comisión", "Mesas técnicas", "Transcripciones", "Seguimiento"]
)

with tab_agenda:
    fc = st.columns([0.9, 1.3, 1, 1])
    sel_camara = fc[0].selectbox("Cámara", _opciones("Cámara"))
    # La opciones de Comisión se acotan a la cámara elegida — Senado y Diputados
    # tienen comisiones con el mismo nombre (ver sesiones/sync.py), así que sin
    # esto quedaban indistinguibles en el dropdown.
    _base_comision = df_full if sel_camara == TODOS else df_full[df_full["Cámara"] == sel_camara]
    sel_comision = fc[1].selectbox("Comisión", _opciones("Comisión", _base_comision))
    sel_tipo = fc[2].selectbox("Tipo", _opciones("Tipo"))
    con_pls = fc[3].selectbox("Con PLs en agenda", ["Todas", "Solo con PLs", "Sin PLs"])

    df = df_full
    if sel_camara != TODOS:
        df = df[df["Cámara"] == sel_camara]
    if sel_comision != TODOS:
        df = df[df["Comisión"] == sel_comision]
    if sel_tipo != TODOS:
        df = df[df["Tipo"] == sel_tipo]
    if con_pls == "Solo con PLs":
        df = df[df["_n_pls"] > 0]
    elif con_pls == "Sin PLs":
        df = df[df["_n_pls"] == 0]

    st.markdown(f"##### {len(df):,} sesión(es) de {len(df_full):,} en el rango")

    # Sin "Estado" — info redundante (las sesiones se filtran por fecha
    # naturalmente y el estado raro vale como filtro). Columnas espejan EC.
    COLS_VISIBLES = ["ID", "Fecha", "Hora", "Cámara", "Comisión", "PLs en agenda", "Nombre"]
    df_view = df[[c for c in COLS_VISIBLES if c in df.columns]].copy()

    tabla = st.dataframe(
        df_view,
        hide_index=True,
        use_container_width=True,
        height=620,
        row_height=140,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "ID":       st.column_config.NumberColumn("ID", width="small", pinned=True,
                help="ID interno de la sesión. Click la fila para ver detalle con links a portal."),
            "Fecha":    st.column_config.TextColumn("Fecha", width="small"),
            "Hora":     st.column_config.TextColumn("Hora", width="small"),
            "Comisión": st.column_config.TextColumn("Comisión", width="medium"),
            "PLs en agenda": st.column_config.TextColumn(
                "PLs en agenda", width="large",
                help="Proyectos de ley detectados en el orden del día. Click la fila para ver títulos y links."),
            "Nombre":   st.column_config.TextColumn("Nombre de sesión", width="medium"),
        },
    )

    # ---------- Panel de detalle ----------
    selected = []
    try:
        selected = tabla.selection.rows or []
    except AttributeError:
        pass

    if selected and selected[0] < len(df_view):
        # Recuperamos la fila completa de df (filtrado) para sacar el ID y _fuente,
        # ya que df_full tiene los IDs originales y df ya respeta los filtros del UI.
        sel_idx = selected[0]
        id_sesion = int(df.iloc[sel_idx]["ID"])
        fuente = df.iloc[sel_idx].get("_fuente", "comision") if "_fuente" in df.columns else "comision"
        # Lookup de la fila completa para metadata extra (teams/video) y orden
        mask = (df_full["ID"] == id_sesion)
        if "_fuente" in df_full.columns:
            mask &= (df_full["_fuente"] == fuente)
        sesion_row = df_full[mask].iloc[0]

        teams = sesion_row.get("_link_teams") or ""
        video = sesion_row.get("_link_video") or ""

        extras = []
        if teams:
            extras.append(f'<a href="{teams}" target="_blank" style="color:#0A294D;font-weight:700;text-decoration:underline">Teams</a>')
        if video:
            extras.append(f'<a href="{video}" target="_blank" style="color:#0A294D;font-weight:700;text-decoration:underline">Video</a>')
        extras_html = " · ".join(extras) if extras else ""

        eyebrow_label = {"pleno": "Agenda del Pleno",
                         "youtube": "Solo en YouTube"}.get(fuente, f"Sesión {id_sesion}")
        meta_extra = f" · {extras_html}" if extras_html else ""
        # HTML en una sola linea (sin \n embebidos): un f-string multilinea
        # con una linea que evalua a vacio (ej. sin teams/video) deja una
        # linea "en blanco" para el parser de Markdown, que ahi da por
        # terminado el bloque HTML y renderiza el resto (los </div> de
        # cierre) como texto literal en vez de cerrar los tags. Bug real
        # visto en vivo 2026-09-15 al testear el rediseño.
        st.markdown(
            f'<div class="session-card">'
            f'<div class="eyebrow">{eyebrow_label}</div>'
            f'<div class="title">{sesion_row["Nombre"]}</div>'
            f'<div class="meta">{sesion_row["Comisión"]} ({sesion_row["Tipo"]}) · '
            f'{sesion_row["Fecha"]} {sesion_row["Hora"] or ""} · '
            f'<strong>{sesion_row["Estado"]}</strong>{meta_extra}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        if fuente == "youtube":
            st.caption("El Congreso transmitió esta sesión pero no la cargó en su "
                       "visor de sesiones, así que no hay orden del día oficial. "
                       "La transcripción está en la pestaña Transcripciones.")

        # PLs referenciados (priorizar — esto es lo más valioso)
        df_pls = load_pls_de_sesion(id_sesion, fuente=fuente)
        if not df_pls.empty:
            st.markdown(f"##### Proyectos de Ley en agenda ({len(df_pls)})")
            df_pls_show = df_pls.drop(columns=["pley_num", "_Contexto", "_Raw"])
            st.dataframe(
                df_pls_show,
                hide_index=True,
                use_container_width=True,
                row_height=80,
                column_config={
                    # Nº PL: el valor de la celda es la URL al portal; display_text
                    # con regex extrae el formato "NNNNN/YYYY-XX" del query param
                    # ?pl=... para mostrarlo como label clickeable.
                    "Nº PL":   st.column_config.LinkColumn("Nº PL",
                        display_text=r"\?pl=([^#]+)",
                        width="small", pinned=True,
                        help="Click para abrir el expediente en el portal del Congreso."),
                    "Tema":    st.column_config.TextColumn("Tema", width="small"),
                    "Estado":  st.column_config.TextColumn("Estado", width="small"),
                    "Bancada": st.column_config.TextColumn("Bancada", width="small"),
                    "Título":  st.column_config.TextColumn("Título", width="large"),
                },
            )

        # Puntos de agenda (texto plano)
        puntos = load_puntos_agenda(id_sesion, fuente=fuente)
        if puntos:
            with st.expander(f"Orden del día completo ({len(puntos)} punto/s)", expanded=False):
                for p in puntos:
                    txt = p["descripcion_texto"] or "(sin texto)"
                    st.markdown(f"**Punto {p['orden']+1}** (id {p['id_orden_dia']})")
                    st.text(txt[:3000] + ("..." if len(txt) > 3000 else ""))
                    st.markdown("---")
    else:
        st.markdown(
            '<div style="margin-top: 18px; font-size: 13px; color: var(--ink-mute);">'
            '↑ Click sobre una fila para ver agenda + PLs cruzados de la sesión.'
            '</div>',
            unsafe_allow_html=True,
        )

with tab_comision:
    st.markdown(
        '<p style="font-size:13px;color:var(--ink-mute);margin-bottom:14px;">'
        'PLs únicos referenciados en agendas, agrupados por comisión. '
        'Cuenta cuántas sesiones discutieron cada PL en el rango seleccionado.</p>',
        unsafe_allow_html=True,
    )

    df_por_com = load_pls_por_comision(f_ini, f_fin)
    if df_por_com.empty:
        st.info("No hay PLs en agenda en el rango seleccionado.")
    else:
        # Comisiones únicas con count de PLs
        resumen = (df_por_com.groupby("Comisión")
                   .agg(pls_unicos=("pley_num", "nunique"),
                        sesiones=("Sesiones", "sum"))
                   .sort_values("pls_unicos", ascending=False)
                   .reset_index())
        # Comisiones donde elegir
        todas_comisiones = ["(todas)"] + resumen["Comisión"].tolist()
        fcv = st.columns([2, 1])
        sel_com_v = fcv[0].selectbox(
            "Comisión a inspeccionar",
            todas_comisiones,
            format_func=lambda x: (
                x if x == "(todas)"
                else f"{x} — {resumen.loc[resumen['Comisión']==x,'pls_unicos'].iloc[0]} PLs únicos"
            ),
        )
        clientes = historial.clientes("PE")
        TODOS_CLIENTES = "Todos"
        sel_cliente = fcv[1].selectbox("Cliente", [TODOS_CLIENTES] + clientes)
        if sel_com_v == "(todas)":
            df_show = df_por_com
        else:
            df_show = df_por_com[df_por_com["Comisión"] == sel_com_v]
        matriz_cliente: set[str] = set()
        if sel_cliente != TODOS_CLIENTES:
            temas_cliente = CATEGORIA_CLIENTES_PL.get(sel_cliente, [])
            matriz_cliente = matriz_pls("PE").get(sel_cliente, set())
            df_show = df_show[df_show["Tema"].isin(temas_cliente) | df_show["PL"].isin(matriz_cliente)]

        st.markdown(f"##### {len(df_show):,} PL(s) en agenda · {df_show['pley_num'].nunique():,} únicos")
        if matriz_cliente:
            _n_matriz = df_show["PL"].isin(matriz_cliente).sum()
            if _n_matriz:
                st.caption(f"📋 {_n_matriz} de estos PLs están en tu matriz puntual de seguimiento.")
        tabla_agenda = st.dataframe(
            df_show.drop(columns=["pley_num"]),
            hide_index=True,
            use_container_width=True,
            height=520,
            row_height=70,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "Comisión":     st.column_config.TextColumn("Comisión", width="medium"),
                # Nº PL clickeable al portal (formato extraido del query param ?pl=)
                "Nº PL":        st.column_config.LinkColumn("Nº PL",
                    display_text=r"\?pl=([^#]+)",
                    width="small",
                    help="Click para abrir el expediente en el portal del Congreso."),
                "PL": None,  # solo para cruzar contra la matriz/marcar - no se muestra
                "Tema":         st.column_config.TextColumn("Tema", width="small"),
                "Estado del PL":st.column_config.TextColumn("Estado del PL", width="small"),
                "Título":       st.column_config.TextColumn("Título", width="large"),
                "Sesiones":     st.column_config.NumberColumn("Sesiones", width="small",
                    help="Cantidad de sesiones de esta comisión donde el PL apareció en agenda."),
                "Primera":      st.column_config.TextColumn("1ra vez", width="small"),
                "Última":       st.column_config.TextColumn("Última", width="small"),
            },
        )
        _fila_seleccionada = None
        try:
            _sel_rows = tabla_agenda.selection.rows
            if _sel_rows and _sel_rows[0] < len(df_show):
                _fila_seleccionada = df_show.iloc[_sel_rows[0]]
        except AttributeError:
            pass

        # ---------- Marcar PL de agenda para alerta ----------
        if clientes and not df_show.empty:
            st.markdown("##### ✍️ Armar alerta de un PL")
            opciones_pl = {
                f"{row['PL']} · {row['Título'][:70]}": idx
                for idx, row in df_show.iterrows()
            }
            _opciones_labels = list(opciones_pl.keys())
            if _fila_seleccionada is not None:
                st.caption(
                    f"PL seleccionado en la tabla: **{_fila_seleccionada['PL']}** · "
                    f"{_fila_seleccionada['Título'][:80]}"
                )
                _label_preseleccionado = f"{_fila_seleccionada['PL']} · {_fila_seleccionada['Título'][:70]}"
                # Pasar index= a un selectbox con key ya inicializado en session_state
                # no tiene efecto en los reruns siguientes - hay que setear el valor
                # a mano, y solo cuando el click en la tabla cambio.
                if (
                    st.session_state.get("_ultimo_pl_click_agenda_pe") != _fila_seleccionada["PL"]
                    and _label_preseleccionado in _opciones_labels
                ):
                    st.session_state["marcar_agenda_pl_sel"] = _label_preseleccionado
                    st.session_state["_ultimo_pl_click_agenda_pe"] = _fila_seleccionada["PL"]
            else:
                st.caption("Click en una fila de la tabla para elegirla acá, o buscala manualmente:")
            mca = st.columns([3, 2, 1])
            sel_pl_label = mca[0].selectbox("¿Qué PL?", _opciones_labels, key="marcar_agenda_pl_sel")
            sel_pl_cliente = mca[1].selectbox("¿Para qué cliente?", clientes, index=None,
                                              placeholder="Elige el cliente", key="marcar_agenda_pl_cli")
            if mca[2].button("✍️ Armar alerta", key="marcar_agenda_pl_btn", disabled=not sel_pl_cliente,
                             type="primary"):
                row = df_show.loc[opciones_pl[sel_pl_label]]
                armar.ir_al_chat([armar.item(
                    f"PL {row['PL']}: {row['Título']}", row["Nº PL"],
                    f"En agenda de {row['Comisión']} - {row['Estado del PL']}", "PE", tipo="pl")],
                    sel_pl_cliente)




with tab_mesas:
    st.markdown(
        '<p style="font-size:13px;color:var(--ink-soft);">'
        'Convocatorias publicadas por congresistas y comisiones en '
        '<code>comunicaciones.congreso.gob.pe/agenda/</code>. Incluye mesas '
        'técnicas, ceremonias, sesiones descentralizadas y otros eventos que '
        '<strong>no aparecen en el visor de sesiones formales</strong>. '
        'Sincronizado automáticamente cada hora.</p>',
        unsafe_allow_html=True,
    )
    if not has_mesas_table():
        st.info("Sin mesas/eventos registrados todavía.")
    else:
        df_mesas = load_mesas(limit=120)
        if df_mesas.empty:
            st.info("Sin mesas/eventos registrados todavía.")
        else:
            st.markdown(f'<p style="font-size:13px;color:var(--ink-soft);">'
                        f'{len(df_mesas):,} eventos recientes</p>',
                        unsafe_allow_html=True)
            st.dataframe(
                df_mesas,
                hide_index=True,
                use_container_width=True,
                height=420,
                column_config={
                    "Fecha":    st.column_config.TextColumn("Fecha", width="medium"),
                    "Hora":     st.column_config.TextColumn("Hora", width="small"),
                    "Tipo":     st.column_config.TextColumn("Tipo", width="small"),
                    "Tema":     st.column_config.TextColumn("Tema", width="large"),
                    "Organiza": st.column_config.TextColumn("Organiza", width="medium"),
                    "Bancada":  st.column_config.TextColumn("Bancada", width="small"),
                    "Comisión": st.column_config.TextColumn("Comisión", width="medium"),
                    "Enlace":   st.column_config.LinkColumn(
                        "Enlace",
                        width="small",
                        display_text="Ver noticia ↗",
                        help="Abre la convocatoria publicada en comunicaciones.congreso.gob.pe",
                    ),
                },
            )





def _render_resumen_card(res: dict, titulo_caja: str = "Resumen",
                          max_ideas: int = 3) -> None:
    """Tarjeta de resumen + ideas clave + cruce de agenda (si hay) para 1
    transcripcion. Un solo lugar para esto - antes estaba duplicado entre
    la seccion "en vivo" y "Sesiones previas".

    Ideas clave acotadas a `max_ideas` con un toggle para ver el resto -
    feedback real de Nicolas 2026-09-15: con 5-7 ideas por sesion y varias
    sesiones en pantalla, la vista quedaba demasiado larga."""
    ideas = res.get("ideas_clave", [])
    agenda_html = (
        f'<div style="font-size:12px;color:var(--ink-mute);margin-top:8px;'
        f'padding-top:8px;border-top:1px solid var(--line-soft);">'
        f'<strong>Agenda:</strong> {res["agenda_cumplida"]}</div>'
        if res.get("agenda_cumplida") else ""
    )
    with st.container(border=True):
        st.markdown(
            f'<div style="font-size:11px;font-weight:800;letter-spacing:0.1em;'
            f'text-transform:uppercase;color:var(--ink-mute);margin-bottom:6px;">'
            f'{titulo_caja}</div>'
            f'<div style="font-size:14px;margin-bottom:4px;">{res["resumen"]}</div>',
            unsafe_allow_html=True,
        )
        ver_todas = True
        if len(ideas) > max_ideas:
            # key incluye titulo_caja ademas de video_id - bug real
            # 2026-09-16 (StreamlitDuplicateElementKey en vivo, reportado por
            # Nicolas): una sesion que ya tiene captions sincronizados
            # ("Sesiones previas") pero YouTube todavia la marca como en
            # curso ("En vivo") se renderiza en las DOS secciones con el
            # mismo video_id en la misma corrida de la pagina.
            ver_todas = st.toggle(
                f"Ideas clave ({len(ideas)})", value=False,
                key=f"ideas_toggle_{titulo_caja}_{res.get('video_id', titulo_caja)}",
            )
        ideas_mostradas = ideas if ver_todas else ideas[:max_ideas]
        ideas_html = "".join(f"<li>{i}</li>" for i in ideas_mostradas)
        st.markdown(
            f'<ul style="font-size:13px;color:var(--ink-soft);margin:0;'
            f'padding-left:18px;">{ideas_html}</ul>{agenda_html}',
            unsafe_allow_html=True,
        )


with tab_transcripciones:
    # ---------- En vivo: transcribir los ultimos N segundos, bajo demanda ----------
    # Bajo demanda (no automatico) porque capturar audio real de un stream
    # en vivo tarda literalmente lo que dura el clip (no hay forma de ir
    # mas rapido que tiempo real) y ademas solo funciona desde una IP
    # local/residencial - las IPs de datacenter (GitHub Actions, muy
    # probablemente Streamlit Cloud tambien) estan marcadas por el
    # anti-bot de YouTube, mismo bloqueo ya documentado para el sync
    # automatico de transcripciones pasadas. Verificado en vivo
    # 2026-09-14: funciona perfecto desde una IP local.
    if _vivos:
        st.markdown("##### 🔴 En vivo ahora")
        st.caption(
            "GitHub detecta cada sesión en vivo y la transcribe sola. Lo último "
            "que se sabe de cada una aparece acá abajo."
        )
        from congreso_live.resumenes_store import list_resumenes as _list_resumenes_vivo
        _resumenes_vivo = _list_resumenes_vivo()
        for _v in _vivos:
            with st.container(border=True):
                cols_v = st.columns([1])
                cols_v[0].markdown(f"**{_v['tipo']}** — {_v['titulo'][:90]}")

                _estado = _estado_transcripcion_vivo(_v["id"])
                _res_vivo = _resumenes_vivo.get(_v["id"])
                if _estado:
                    _dur = _estado["duracion_seg"] or 0
                    cols_v[0].caption(
                        f"📡 Transcribiéndose automáticamente — "
                        f"~{int(_dur) // 60} min cubiertos hasta ahora "
                        f"(última actualización: {_estado['fetched_at']})."
                    )
                    if _res_vivo:
                        with st.expander("Ver resumen (última corrida horaria)"):
                            _render_resumen_card(_res_vivo, "Resumen (última corrida horaria)")
                    else:
                        cols_v[0].caption(
                            "Resumen pendiente — se genera en la próxima corrida "
                            "horaria de la rutina de resúmenes."
                        )
                else:
                    cols_v[0].caption(
                        "Todavía no aparece transcripción. GitHub revisa cada 10 minutos, "
                        "publica el avance cada 5 y la web lo baja cada 10, así que una "
                        "sesión recién empezada puede tardar unos 20 a 25 minutos en verse acá."
                    )
        st.markdown("")

    st.markdown(
        '<p style="font-size:13px;color:var(--ink-soft);max-width:760px;">'
        'Texto de lo discutido en sesiones ya transmitidas, a partir de los '
        'captions automáticos de YouTube — no es tiempo real: YouTube tarda '
        'unos días en procesarlos, así que esto muestra sesiones recientes, '
        'no la que está en vivo ahora mismo.</p>',
        unsafe_allow_html=True,
    )
    df_transcripciones = load_transcripciones()
    if df_transcripciones.empty:
        st.caption(
            "Ninguna todavía. Se sincronizan con "
            "`python -m congreso_live.cli sync-transcripciones`."
        )
    else:
        from congreso_live.resumenes_store import list_resumenes
        _resumenes = list_resumenes()

        # ---------- Por semana: checklist fijo por comision, como el informe ----------
        # Pedido real de Nicolas 2026-09-18: "las sesiones... podrian aparecer
        # siempre en el orden que tengo en mi doc... y si no sesionaron
        # colocar que no sesionaron" - reemplaza el filtro de 3 botones (que
        # solo mostraba lo que SI paso) por un checklist fijo de las
        # comisiones ordinarias de cada camara, en el orden del catalogo
        # oficial (el mismo que usa su informe semanal real), con "No
        # sesionó" explicito para las que no tuvieron actividad. Las
        # no-legislativas/bicamerales que SI sesionaron van al final, fuera
        # del catalogo fijo.
        st.markdown("##### 📅 Por semana")
        if "semana_offset" not in st.session_state:
            st.session_state["semana_offset"] = 0
        _col_prev, _col_label, _col_next = st.columns([1, 2, 1])
        if _col_prev.button("◀ Anterior", key="semana_prev", use_container_width=True):
            st.session_state["semana_offset"] -= 1
        if _col_next.button("Siguiente ▶", key="semana_next", use_container_width=True):
            st.session_state["semana_offset"] += 1
        _hoy = dt.datetime.now(dt.timezone.utc).date()
        _lunes_hoy = _hoy - dt.timedelta(days=_hoy.weekday())
        _lunes = _lunes_hoy + dt.timedelta(weeks=st.session_state["semana_offset"])
        _domingo = _lunes + dt.timedelta(days=6)
        _col_label.markdown(f"**{_lunes:%d/%m} al {_domingo:%d/%m}**")
        if st.session_state["semana_offset"] != 0 and _col_label.button("Volver a esta semana", key="semana_hoy"):
            st.session_state["semana_offset"] = 0
            st.rerun()

        _df_semana = df_transcripciones[
            (df_transcripciones["fecha"] >= _lunes.isoformat())
            & (df_transcripciones["fecha"] <= _domingo.isoformat())
        ].copy()
        _df_semana["_camara"] = [
            _clasificar_camara(r["tipo"], r["titulo"], r["fecha"], r["video_id"], r["texto"])
            for _, r in _df_semana.iterrows()
        ]

        def _que_paso(row) -> str:
            _res = _resumenes.get(row["video_id"])
            if _res:
                return _res["resumen"]
            return (row["texto"][:180] + "…") if row["texto"] else "Resumen pendiente de generar."

        def _tabla_camara(camara: str, catalogo: tuple[str, ...]) -> pd.DataFrame:
            _df_cam = _df_semana[_df_semana["_camara"] == camara]
            _tipos_catalogo: set[str] = set()
            _filas = []
            for _nombre in catalogo:
                _tipo = _tipo_de_comision_oficial(_nombre)
                _tipos_catalogo.add(_tipo)
                _match = _df_cam[_df_cam["tipo"] == _tipo] if _tipo else _df_cam.iloc[0:0]
                if _match.empty:
                    _filas.append({"Comisión": _nombre, "Qué pasó": "No sesionó esta semana."})
                else:
                    for _, _r in _match.iterrows():
                        _filas.append({"Comisión": _nombre, "Qué pasó": _que_paso(_r)})
            # Lo que sesiono esa semana pero no esta en el catalogo fijo
            # (no-legislativas: Etica, Procedimientos Especiales, Control
            # Politico, etc.) - al final, con su propio nombre real.
            _extra = _df_cam[~_df_cam["tipo"].isin(_tipos_catalogo)]
            for _, _r in _extra.iterrows():
                _nombre_extra = _r["tipo"].split(":", 1)[-1].strip()
                _filas.append({"Comisión": _nombre_extra, "Qué pasó": _que_paso(_r)})
            return pd.DataFrame(_filas)

        # Botones para ver una tabla a la vez (pedido de Nicolas: le
        # gustaba poder pasar de Senado a Diputados y al otro con un
        # boton, en vez de las 3 tablas juntas) - el checklist fijo con
        # "No sesionó" se mantiene, solo cambia como se navega entre camaras.
        _vista = st.radio(
            "Vista", ["Senado", "Diputados", "Plenos y conjuntas"],
            horizontal=True, key="vista_camara", label_visibility="collapsed",
        )
        if _vista == "Senado":
            st.dataframe(_tabla_camara("Senado", _SENADO_COMISIONES_ORDEN),
                         hide_index=True, use_container_width=True)
        elif _vista == "Diputados":
            st.dataframe(_tabla_camara("Diputados", _DIPUTADOS_COMISIONES_ORDEN),
                         hide_index=True, use_container_width=True)
        else:
            _df_conjuntas = _df_semana[_df_semana["_camara"].isin(["Congreso", "Conjunta"])]
            if _df_conjuntas.empty:
                st.caption("Nada de Plenos conjuntos o comisiones bicamerales esta semana.")
            else:
                # El nombre corto ya viene de `tipo` (ej. "Comision: Presupuesto"
                # -> "Presupuesto") - antes caia al titulo crudo del video para
                # las bicamerales, que trae emoji/fecha/"EN VIVO" pegado y
                # queda feo (bug real reportado por Nicolas 2026-09-18).
                _filas_conj = [
                    {"Comisión": (f"Pleno {_r['tipo'].split(':', 1)[-1].strip()}"
                                  if _r["tipo"].startswith("Pleno:")
                                  else _r["tipo"].split(":", 1)[-1].strip()),
                     "Qué pasó": _que_paso(_r)}
                    for _, _r in _df_conjuntas.iterrows()
                ]
                st.dataframe(pd.DataFrame(_filas_conj), hide_index=True, use_container_width=True)

        # st.expander no admite expanders anidados (cada sesion ya usa uno
        # para su propio detalle) - un toggle es el equivalente "boton que
        # muestra/oculta" sin ese problema.
        ver_previas = st.toggle(f"Sesiones previas, por fecha ({len(df_transcripciones)})")
        if ver_previas:
            for _fecha, _grupo in df_transcripciones.groupby("fecha", sort=False):
                st.markdown(f"###### {_fecha or 'Sin fecha'} ({len(_grupo)})")
                for _, row in _grupo.iterrows():
                    _dur = row["duracion_seg"]
                    _dur_txt = f"{int(_dur) // 3600}h {(int(_dur) % 3600) // 60}min" if _dur else "—"
                    _temas_html = "".join(
                        f'<span class="pl-chip">{t}</span>'
                        for t in (row["temas"] or "").split(",") if t
                    )
                    _res = _resumenes.get(row["video_id"])
                    _camara = _clasificar_camara(
                        row["tipo"], row["titulo"], row["fecha"], row["video_id"], row["texto"])
                    with st.expander(f"[{_camara}] {row['tipo']} · {row['titulo'][:90]}"):
                        st.markdown(
                            f'<div style="margin-bottom:10px;">{_temas_html}</div>'
                            f'<div style="font-size:12px;color:var(--ink-mute);margin-bottom:10px;">'
                            f'Duración: {_dur_txt} · '
                            f'<a href="https://www.youtube.com/watch?v={row["video_id"]}" '
                            f'target="_blank">Ver en YouTube ↗</a></div>',
                            unsafe_allow_html=True,
                        )
                        if _res:
                            _render_resumen_card(_res)
                        else:
                            st.caption("Resumen pendiente de generar.")
                        # Colapsada por defecto (no ocupar la pantalla con el
                        # texto crudo) - st.code() en vez de st.text_area()
                        # porque trae boton de copiar nativo (util para pegar
                        # en otra IA), pedido real de Nicolas 2026-09-16.
                        if st.toggle("Ver transcripción completa",
                                     key=f"ver_transcripcion_{row['video_id']}"):
                            st.code(row["texto"], language=None, wrap_lines=True, height=300)

                        # Chat simple de preguntas sobre esta transcripcion, via
                        # Gemini (tier gratuito - decision de Nicolas 2026-09-15
                        # para que esto no genere costo por uso). Sin memoria
                        # entre sesiones de usuario ni busqueda cruzada entre
                        # transcripciones - una pregunta, un contexto: el texto
                        # de ESTA sesion.
                        st.markdown("**Preguntale a la transcripción**")
                        _qa_key = f"qa_history_{row['video_id']}"
                        if _qa_key not in st.session_state:
                            st.session_state[_qa_key] = []
                        for _pregunta_prev, _respuesta_prev in st.session_state[_qa_key]:
                            st.chat_message("user").write(_pregunta_prev)
                            st.chat_message("assistant").write(_respuesta_prev)
                        with st.form(key=f"qa_form_{row['video_id']}", clear_on_submit=True):
                            _pregunta_nueva = st.text_input(
                                "Pregunta", placeholder="¿Qué se discutió sobre...?",
                                label_visibility="collapsed",
                                key=f"qa_input_{row['video_id']}",
                            )
                            _enviar = st.form_submit_button("Preguntar")
                        if _enviar and _pregunta_nueva.strip():
                            with st.spinner("Pensando..."):
                                try:
                                    from congreso_live.qa_chat import preguntar
                                    _respuesta_nueva = preguntar(
                                        _pregunta_nueva, row["texto"], titulo=row["titulo"],
                                    )
                                except Exception as e:
                                    st.error(f"No se pudo responder: {e}")
                                else:
                                    st.session_state[_qa_key].append(
                                        (_pregunta_nueva, _respuesta_nueva))
                                    st.rerun()

with tab_seguimiento:
    st.markdown(
        '<p style="font-size:13px;color:var(--ink-soft);max-width:760px;">'
        'Marca las comisiones que te interesa seguir como prioritarias. '
        'Se guarda para ti (no por cliente) y se usa para resaltar sus '
        'sesiones en la Agenda y para las alertas de WhatsApp cuando haya '
        'novedades.</p>',
        unsafe_allow_html=True,
    )
    from alerts.seguimiento_store import list_seguidas, set_seguidas

    try:
        _seguidas_actuales = list_seguidas()
        _seguimiento_error = None
    except Exception as e:
        _seguidas_actuales = set()
        _seguimiento_error = str(e)

    if _seguimiento_error:
        st.error(f"No se pudo cargar el estado guardado: {_seguimiento_error}")

    _comisiones_por_camara: dict[str, list[str]] = {}
    for _c in cats["comisiones"]:
        _comisiones_por_camara.setdefault(_c["camara"] or "—", []).append(_c["nombre"])

    with st.form("form_seguimiento"):
        _marcadas: set[str] = set()
        for _camara, _nombres in sorted(_comisiones_por_camara.items()):
            st.markdown(f"**{_camara}**")
            for _nombre in sorted(set(_nombres)):
                if st.checkbox(_nombre, value=_nombre in _seguidas_actuales,
                                key=f"seg_{_camara}_{_nombre}"):
                    _marcadas.add(_nombre)
        _guardar = st.form_submit_button("Guardar")

    if _guardar:
        try:
            set_seguidas(_marcadas)
            st.success(f"Guardado: {len(_marcadas)} comisión(es) marcadas como prioritarias.")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo guardar: {e}")

# ---------- Footer ----------
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
with st.expander("Cobertura y limitaciones de esta vista"):
    st.markdown(
        '<p style="font-size:12px;color:var(--ink-soft);line-height:1.55;'
        'max-width:760px;margin-bottom:14px;">'
        '<strong style="color:var(--ink);">Cobertura temporal:</strong> '
        'esta vista muestra solo el Congreso bicameral vigente (desde el '
        '<strong>27 de julio de 2026</strong>) — la data histórica del período unicameral '
        '2021–2026 queda guardada en la base pero desconectada de esta página. '
        'Las <strong>agendas del Pleno</strong> bicameral aún no se publican por la API '
        '<em>adp-portal</em> (verificado 2026-09-11) — esa sección quedará vacía hasta que '
        'el Congreso empiece a publicarlas.<br><br>'
        '<strong style="color:var(--ink);">Cobertura de órganos:</strong> esta vista '
        'incluye las comisiones propias del <strong>Senado</strong> (11) y la '
        '<strong>Cámara de Diputados</strong> (19), y el <strong>Pleno</strong> del Congreso. '
        'La <strong>Comisión Permanente</strong>, la <strong>Subcomisión de '
        'Acusaciones Constitucionales</strong> y las comisiones investigadoras/especiales '
        'no se publican por las APIs disponibles y no figuran aquí. Algunas comisiones '
        'comparten nombre exacto entre Senado y Diputados (ej. "Justicia y Derechos '
        'Humanos") — esas sesiones no se pueden filtrar por cámara con certeza y quedan '
        'sin clasificar en el filtro "Cámara".</p>',
        unsafe_allow_html=True,
    )
st.markdown(
    '<div class="footer-text">Fuente · wb2server.congreso.gob.pe/service-portal-publico-ext · '
    'Radar Legislativo</div>',
    unsafe_allow_html=True,
)
