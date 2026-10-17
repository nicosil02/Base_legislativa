"""Radar Legislativo - Ecuador - Agenda parlamentaria.

Vista de sesiones convocadas/realizadas de las comisiones de la Asamblea
Nacional, con cruce automatico contra la base de proyectos de ley EC.

Fuente: feed ICS de Zimbra (correo.asambleanacional.gob.ec) sincronizado
1+ veces al dia por GitHub Actions.
DB: tablas sesiones_ec / sesion_ec_pl_referenciado en proyectos_ec.db.

Diseno espejo de pages/3_Agenda_PE.py para mantener consistencia visual.
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from scraper.categorias import CATEGORIA_CLIENTES_PL
from alerts import armar, historial
from ui_kit import AGENDA_CSS, inject_theme
from consultas.agenda_ec import (
    fetch_live_agenda_ec,
    has_sesiones_table,
    kpi_totals,
    load_catalogs,
    load_sesiones,
    load_pls_agenda_ec,
    load_pls_de_sesion,
    load_descripcion,
    load_sesiones_ec_transcritas,
)
from consultas import matriz_pls



# ====================== CSS (mismo del Agenda PE para consistencia) ======================
inject_theme()
st.markdown(AGENDA_CSS, unsafe_allow_html=True)


# ---------- Pleno y comisiones de la Asamblea: transcripcion + resumen ----------
# Mismo pipeline que Peru (congreso_live: live-watch en vigilar-congreso.yml,
# captions/backfill, rutina horaria de resumenes) - las filas viven en
# `sesiones_transcripciones` de proyectos.db (la DB de Peru), con tipo
# terminado en "(EC)". Pleno por YouTube (en vivo + terminado); comisiones
# por Facebook, solo ya terminadas (congreso_live/facebook_ec.py).
from congreso_live.facebook_ec import url_video


@st.cache_data(ttl=90)
def _plenos_ec_en_vivo() -> list[dict]:
    try:
        from congreso_live.detector import vivos_de_interes
        return [v for v in vivos_de_interes() if v.get("pais") == "EC"]
    except Exception as e:
        print(f"[agenda-ec] no se pudo chequear en vivo: {e}")
        return []


def _clave_organo(nombre: str | None) -> str:
    """'Comision: Seguridad Integral (EC)' / 'Seguridad Integral' / 'Pleno'
    -> clave comparable entre la agenda (sesiones_ec.nombre_comision) y las
    transcripciones (tipo). Los nombres cortos de congreso_live/facebook_ec.py
    son justamente los de la agenda, asi que alcanza con normalizar."""
    import unicodedata
    t = (nombre or "").split(":", 1)[-1].replace("(EC)", "").strip().lower()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return "pleno" if t.startswith("asamblea nacional") else t


@st.cache_data(ttl=300)
def transcripciones_por_sesion() -> dict[tuple[str, str], list[dict]]:
    """{(organo, fecha): [transcripciones]} para cruzar con la agenda."""
    df_t = load_sesiones_ec_transcritas()
    out: dict[tuple[str, str], list[dict]] = {}
    for _, r in df_t.iterrows():
        out.setdefault((_clave_organo(r["tipo"]), r["fecha"] or ""), []).append(r.to_dict())
    return out


def _render_transcripcion_ec(t: dict, resumenes: dict, key: str) -> None:
    """Resumen + ideas + enlace + texto completo de 1 transcripcion EC."""
    _dur = t.get("duracion_seg")
    _dur_txt = f"{int(_dur) // 3600}h {(int(_dur) % 3600) // 60}min" if _dur else "—"
    _fuente = "Facebook" if str(t["video_id"]).startswith("fb_") else "YouTube"
    st.caption(f"{t['titulo'][:120]} · Duración: {_dur_txt} · "
               f"[Ver en {_fuente} ↗]({url_video(t['video_id'])})")
    _res = resumenes.get(t["video_id"])
    if _res:
        st.markdown(_res["resumen"])
        for _idea in _res.get("ideas_clave", []):
            st.markdown(f"- {_idea}")
    else:
        st.caption("Resumen pendiente — se genera en la próxima corrida horaria.")
    if st.toggle("Ver transcripción completa", key=f"ec_tr_{key}_{t['video_id']}"):
        st.code(t["texto"], language=None, wrap_lines=True, height=300)

# ====================== UI ======================

st.markdown('<div class="country-eyebrow">Radar Legislativo · Agenda parlamentaria</div>', unsafe_allow_html=True)
st.markdown(
    '<h1 class="country-title"><span class="accent">Ecuador</span> · Agenda parlamentaria '
    '<span class="period">(2025–2029)</span></h1>',
    unsafe_allow_html=True,
)
st.markdown(
    '<p class="country-subtitle">Sesiones convocadas y realizadas de las comisiones '
    'especializadas y el Pleno de la Asamblea Nacional. Cada sesión cruza '
    'con la base de proyectos de ley para identificar automáticamente qué PLs se '
    'debaten (matching por título contra la descripción del orden del día).</p>',
    unsafe_allow_html=True,
)

if not has_sesiones_table():
    st.warning(
        "Las tablas de agenda EC todavía no existen en la DB. "
        "Inicializa corriendo:\n\n"
        "```\npython -m agenda_ec.cli --db proyectos_ec.db init\n"
        "python -m agenda_ec.cli --db proyectos_ec.db update\n```"
    )
    st.stop()

# ---------- Live sync (tiempo real automatico) ----------
# Lee feed Zimbra, auto-upsert sesiones nuevas a la DB → aparecen en la
# tabla principal sin clic.
with st.spinner("Sincronizando agenda en vivo con la Asamblea Nacional..."):
    try:
        _live = fetch_live_agenda_ec()
    except Exception as _e:
        _live = {"error": str(_e), "inserted": 0, "total_api": 0, "total_db": 0}

if _live.get("inserted", 0) > 0:
    st.cache_data.clear()
    st.toast(
        f"⚡ {_live['inserted']} sesión{'es' if _live['inserted'] != 1 else ''} "
        f"nueva{'s' if _live['inserted'] != 1 else ''} sincronizada{'s' if _live['inserted'] != 1 else ''} "
        f"en vivo desde la Asamblea",
        icon="✅",
    )

# ---------- En vivo ahora (mismo banner que Agenda PE) ----------
_vivos = _plenos_ec_en_vivo()
if _vivos:
    _items_html = "".join(
        f'<div class="live-item"><span class="live-dot"></span>'
        f'<a href="{v["url"]}" target="_blank">{v["tipo"]}</a>'
        f'<span class="live-titulo"> — {v["titulo"][:90]}</span></div>'
        for v in _vivos
    )
    st.markdown(
        f'<div class="live-banner"><div class="live-banner-title">🔴 En vivo ahora en YouTube</div>'
        f'{_items_html}</div>',
        unsafe_allow_html=True,
    )

# ---------- KPIs ----------
totals = kpi_totals()
cols = st.columns(len(totals))
for col, (label, val) in zip(cols, totals.items()):
    col.metric(label, f"{val:,}")

st.markdown("")

cats = load_catalogs()

# ---------- Sidebar: rango fechas ----------
with st.sidebar:
    st.markdown("### Rango de fechas")
    today = dt.date.today()
    default_fin = today + dt.timedelta(days=30)
    fec_min_iso = cats["fec_min"] or "2025-05-01"
    fec_max_iso = cats["fec_max"] or default_fin.isoformat()
    fec_min = dt.date.fromisoformat(fec_min_iso)
    fec_max = max(dt.date.fromisoformat(fec_max_iso), default_fin)
    rango = st.date_input(
        "Sesión",
        value=(today - dt.timedelta(days=14), today + dt.timedelta(days=30)),
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

TODOS = "Todas"

def _opciones(col: str) -> list[str]:
    if col not in df_full.columns:
        return [TODOS]
    return [TODOS] + sorted({str(v) for v in df_full[col].dropna().unique() if str(v).strip()})

# ---------- Pestañas: una vista a la vez, igual que Agenda PE ----------
# Pedido de Nicolas 2026-09-27: "que tenga el mismo estilo que Peru... que no
# este todo en una sola vista". Mesas técnicas y Seguimiento de Peru no
# tienen equivalente en Ecuador (no hay esos datos), por eso son 3.
tab_agenda, tab_comision, tab_transcripciones = st.tabs(
    ["Agenda", "Por comisión", "Transcripciones"]
)

with tab_agenda:
    fc = st.columns([1.6, 1])
    sel_comision = fc[0].selectbox("Comisión", _opciones("Comisión"))
    con_pls = fc[1].selectbox("Con PLs en agenda", ["Todas", "Solo con PLs", "Sin PLs"])

    df = df_full
    if sel_comision != TODOS:
        df = df[df["Comisión"] == sel_comision]
    if con_pls == "Solo con PLs":
        df = df[df["_n_pls"] > 0]
    elif con_pls == "Sin PLs":
        df = df[df["_n_pls"] == 0]

    st.markdown(f"##### {len(df):,} sesión(es) de {len(df_full):,} en el rango")

    # Columnas: Fecha, Hora, Comision, PLs en agenda, Nombre de sesion.
    # (Sin Estado — solo confunde, todas las sesiones del feed son CONFIRMED)
    # Cruce con las transcripciones (Pleno por YouTube, comisiones por Facebook):
    # misma comision + misma fecha. Pedido de Nicolas 2026-09-27: que las
    # transcripciones de Ecuador esten DENTRO de la agenda, como en Peru.
    _tr_idx = transcripciones_por_sesion()
    from congreso_live.resumenes_store import list_resumenes as _list_res
    _resumenes_ec = _list_res()


    def _estado_tr(row) -> str:
        ts = _tr_idx.get((_clave_organo(row.get("Comisión")), row.get("Fecha") or ""), [])
        if not ts:
            return ""
        return "✅ Resumen" if any(t["video_id"] in _resumenes_ec for t in ts) else "📝 Transcrita"


    df = df.assign(**{"Transcripción": df.apply(_estado_tr, axis=1) if not df.empty else []})
    COLS_VISIBLES = ["Fecha", "Hora", "Comisión", "Transcripción", "PLs en agenda", "Nombre de sesión"]
    df_view = df[[c for c in COLS_VISIBLES if c in df.columns]].copy()

    # Reset index para que el index numerico (0..N) sea el row id que devuelve
    # selection.rows — sin esto la seleccion mapea a el index original del df_full
    df_view = df_view.reset_index(drop=True)
    df_with_uid = df.reset_index(drop=True)  # paralelo, contiene UID para lookup

    tabla = st.dataframe(
        df_view,
        hide_index=True,
        use_container_width=True,
        height=620,
        on_select="rerun",
        selection_mode="single-row",
    )

    # ---------- Detalle de la sesion seleccionada ----------
    sel_rows = (tabla.selection or {}).get("rows", [])
    if sel_rows:
        idx = sel_rows[0]
        if 0 <= idx < len(df_with_uid):
            uid = df_with_uid.iloc[idx]["UID"]
            descripcion, location, fecha_sel, hora_sel = load_descripcion(uid)
            comision_sel = df_with_uid.iloc[idx].get("Comisión") or "—"
            titulo_sel = df_with_uid.iloc[idx].get("Nombre de sesión") or "—"

            st.markdown(
                f"""
                <div class="session-card">
                  <div class="eyebrow">Detalle de la sesión</div>
                  <div class="title">{titulo_sel}</div>
                  <div class="meta">📅 {fecha_sel} · ⏰ {hora_sel or "—"} · 📍 {location or "—"}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if descripcion.strip():
                with st.expander("Orden del día / descripción completa", expanded=True):
                    st.write(descripcion)

            _ts = _tr_idx.get((_clave_organo(comision_sel), fecha_sel or ""), [])
            if _ts:
                st.markdown(f"##### 🎙️ Qué pasó en la sesión ({len(_ts)} transmisión(es))")
                for _t in _ts:
                    with st.container(border=True):
                        _render_transcripcion_ec(_t, _resumenes_ec, key=f"det_{uid}")
            else:
                st.caption("🎙️ Todavía no hay transcripción de esta sesión (las comisiones se "
                           "transcriben cuando termina la transmisión en Facebook).")

            df_pls = load_pls_de_sesion(uid)
            if not df_pls.empty:
                st.markdown(f"##### PLs identificados ({len(df_pls)})")
                st.dataframe(
                    df_pls.drop(columns=["_score"], errors="ignore"),
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Nº trámite": st.column_config.LinkColumn(
                            "Nº trámite",
                            # Extrae el n_tramite del fragment '#XXX' al final
                            # de la URL. Soporta numeros (480824) y alfanumericos
                            # (AN-GBJL-2024-0092-M).
                            display_text=r"#([A-Z0-9\-]+)$",
                            help="Abre el PDF del proyecto directamente (o el portal si "
                                 "aun no enriquecimos sus documentos)",
                        ),
                    },
                )
                st.caption(
                    "💡 Click en el Nº trámite abre el PDF del proyecto directamente. "
                    "Si todavía no tenemos sus documentos enriquecidos, abre el "
                    "portal Ppless v2 (pega el número en el filtro)."
                )
            else:
                st.info("No se identificaron PLs específicos en esta sesión "
                        "(la descripción puede referir a temas sin proyecto de ley registrado).")

with tab_comision:
    st.markdown(
        '<p style="font-size:13px;color:var(--ink-mute);margin-bottom:14px;">'
        'PLs únicos referenciados en agendas, filtrados por relevancia para un cliente '
        '(categoría automática + matriz puntual de seguimiento).</p>',
        unsafe_allow_html=True,
    )

    df_agenda_cli = load_pls_agenda_ec(f_ini, f_fin)
    if df_agenda_cli.empty:
        st.info("No hay PLs en agenda en el rango seleccionado.")
    else:
        clientes = historial.clientes("EC")
        TODOS_CLIENTES = "Todos"
        sel_cliente_agenda = st.selectbox("Cliente", [TODOS_CLIENTES] + clientes, key="agenda_ec_cliente")
        df_agenda_show = df_agenda_cli
        matriz_cliente_agenda: set[str] = set()
        if sel_cliente_agenda != TODOS_CLIENTES:
            temas_cliente = CATEGORIA_CLIENTES_PL.get(sel_cliente_agenda, [])
            matriz_cliente_agenda = matriz_pls("EC").get(sel_cliente_agenda, set())
            df_agenda_show = df_agenda_show[
                df_agenda_show["Tema"].isin(temas_cliente)
                | df_agenda_show["PL"].astype(str).isin(matriz_cliente_agenda)
            ]

        st.markdown(f"##### {len(df_agenda_show):,} PL(s) en agenda · {df_agenda_show['PL'].nunique():,} únicos")
        if matriz_cliente_agenda:
            _n_matriz = df_agenda_show["PL"].astype(str).isin(matriz_cliente_agenda).sum()
            if _n_matriz:
                st.caption(f"📋 {_n_matriz} de estos PLs están en tu matriz puntual de seguimiento.")
        tabla_agenda_ec = st.dataframe(
            df_agenda_show.drop(columns=["PL"]),
            hide_index=True,
            use_container_width=True,
            height=520,
            row_height=70,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "Comisión":      st.column_config.TextColumn("Comisión", width="medium"),
                "Nº trámite":    st.column_config.LinkColumn("Nº trámite",
                    display_text=r"#([A-Z0-9\-]+)$",
                    width="small",
                    help="Click abre el PDF del proyecto directamente (o el portal Ppless v2)."),
                "Tema":          st.column_config.TextColumn("Tema", width="small"),
                "Estado del PL": st.column_config.TextColumn("Estado del PL", width="small"),
                "Título":        st.column_config.TextColumn("Título", width="large"),
                "Sesiones":      st.column_config.NumberColumn("Sesiones", width="small",
                    help="Cantidad de sesiones donde el PL apareció en agenda."),
                "Primera":       st.column_config.TextColumn("1ra vez", width="small"),
                "Última":        st.column_config.TextColumn("Última", width="small"),
            },
        )
        _fila_seleccionada = None
        try:
            _sel_rows = tabla_agenda_ec.selection.rows
            if _sel_rows and _sel_rows[0] < len(df_agenda_show):
                _fila_seleccionada = df_agenda_show.iloc[_sel_rows[0]]
        except AttributeError:
            pass

        # ---------- Marcar PL de agenda para alerta ----------
        if clientes and not df_agenda_show.empty:
            st.markdown("##### ✍️ Armar alerta de un PL")
            opciones_pl = {
                f"{row['PL']} · {row['Título'][:70]}": idx
                for idx, row in df_agenda_show.iterrows()
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
                    st.session_state.get("_ultimo_pl_click_agenda_ec") != _fila_seleccionada["PL"]
                    and _label_preseleccionado in _opciones_labels
                ):
                    st.session_state["marcar_agenda_ec_pl_sel"] = _label_preseleccionado
                    st.session_state["_ultimo_pl_click_agenda_ec"] = _fila_seleccionada["PL"]
            else:
                st.caption("Click en una fila de la tabla para elegirla acá, o buscala manualmente:")
            mca = st.columns([3, 2, 1])
            sel_pl_label = mca[0].selectbox("¿Qué PL?", _opciones_labels, key="marcar_agenda_ec_pl_sel")
            sel_pl_cliente = mca[1].selectbox("¿Para qué cliente?", clientes, index=None,
                                              placeholder="Elige el cliente", key="marcar_agenda_ec_pl_cli")
            if mca[2].button("✍️ Armar alerta", key="marcar_agenda_ec_pl_btn", disabled=not sel_pl_cliente,
                             type="primary"):
                row = df_agenda_show.loc[opciones_pl[sel_pl_label]]
                armar.ir_al_chat([armar.item(
                    f"PL {row['PL']}: {row['Título']}", str(row["Nº trámite"]).split("#")[0],
                    f"En agenda de {row['Comisión']} - {row['Estado del PL']}", "EC", tipo="pl")],
                    sel_pl_cliente)


with tab_transcripciones:
    st.caption("Pleno (YouTube, también en vivo) y comisiones (Facebook, cuando la sesión termina).")
    for _v in _vivos:
        st.markdown(f"🔴 **En vivo ahora:** [{_v['titulo']}]({_v['url']}) — se está "
                    "transcribiendo sola; el resumen se actualiza cada hora.")
    df_plenos_ec = load_sesiones_ec_transcritas()
    if df_plenos_ec.empty:
        st.caption("Todavía no hay sesiones transcritas.")
    else:
        for _, _row in df_plenos_ec.head(40).iterrows():
            _organo = _row["tipo"].split(":", 1)[-1].replace("(EC)", "").strip()
            with st.expander(f"{_row['fecha'] or 'Sin fecha'} · {_organo} · {_row['titulo'][:90]}"):
                _render_transcripcion_ec(_row.to_dict(), _resumenes_ec, key="lista")

# ---------- Footer ----------
st.markdown('<div class="footer-rule"></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="footer-text">Radar Legislativo · Vali Consultores · '
    'Fuente: Asamblea Nacional del Ecuador (feed Zimbra)</div>',
    unsafe_allow_html=True,
)
