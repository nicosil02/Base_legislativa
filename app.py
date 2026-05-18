"""Vali Intelligence — Punto de entrada (router de navegación + auth gate).

Antes de cualquier dashboard:
  - Si la URL trae ?token=... → verifica magic link y setea sesion.
  - Si no hay sesion activa → renderea login page y STOP.
  - Si hay sesion → registra paginas en st.navigation y corre el router.

Corre con:
    python -m streamlit run app.py
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

# Cargar .env local (Streamlit Cloud usa st.secrets — se mapean a env vars
# automaticamente via [secrets] section).
_REPO_ROOT = Path(__file__).resolve().parent
_env_file = _REPO_ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k = _k.strip()
        _v = _v.strip().strip('"').strip("'")
        if _k and _k not in os.environ:
            os.environ[_k] = _v

# Streamlit Cloud expone los secrets en st.secrets; los proyectamos a env vars
# para que los modulos (alerts, auth) puedan leerlos con os.environ uniforme.
try:
    for _k, _v in dict(st.secrets).items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass


st.set_page_config(
    page_title="Vali Intelligence",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ─── BOOTSTRAP DE DBs (Streamlit Cloud no tiene filesystem persistente) ─────
# Si las DBs no existen en disk, las restauramos desde snapshots commiteados.
# Si existen pero el .gz del repo es más nuevo (ej. tras un deploy con nuevo
# snapshot generado por GH Actions), re-descomprime. Esto resuelve el bug de
# Streamlit Cloud donde el .db quedaba "pegado" en una versión vieja porque
# el bootstrap original solo corría cuando el .db no existía.
# En local respeta tus updates: `scraper update` deja el .db con mtime > gz,
# por lo que no se re-descomprime.
def _bootstrap_dbs():
    import gzip
    import shutil

    def _needs_restore(db_path: Path, gz_path: Path) -> str | None:
        """Devuelve el motivo si hay que re-descomprimir, o None si no."""
        if not gz_path.exists():
            return None
        if not db_path.exists():
            return "missing"
        try:
            if gz_path.stat().st_mtime > db_path.stat().st_mtime:
                return "stale"
        except OSError:
            return "missing"
        return None

    repo_root = Path(__file__).resolve().parent

    # Perú: decomprimir data/proyectos.db.gz (14 MB) → proyectos.db (78 MB)
    pe_db = repo_root / "proyectos.db"
    pe_gz = repo_root / "data" / "proyectos.db.gz"
    reason = _needs_restore(pe_db, pe_gz)
    if reason:
        try:
            with gzip.open(pe_gz, "rb") as f_in, pe_db.open("wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            print(f"[bootstrap] proyectos.db restored from gz ({reason}, {pe_db.stat().st_size} bytes)")
        except Exception as e:
            print(f"[bootstrap] error restoring PE DB: {e}")

    # Ecuador: preferir snapshot gzipped (incluye documentos enriquecidos).
    # Si no existe el .gz, fallback al CSV (solo proyectos, sin documentos).
    ec_db = repo_root / "proyectos_ec.db"
    ec_gz = repo_root / "data" / "proyectos_ec.db.gz"
    ec_csv = repo_root / "data" / "ppless_listado_2025-2029_snapshot.csv"
    reason = _needs_restore(ec_db, ec_gz)
    if reason:
        try:
            with gzip.open(ec_gz, "rb") as f_in, ec_db.open("wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            print(f"[bootstrap] proyectos_ec.db restored from gz ({reason}, {ec_db.stat().st_size} bytes)")
        except Exception as e:
            print(f"[bootstrap] error restoring EC DB from gz: {e}")
    elif not ec_db.exists() and ec_csv.exists():
        try:
            from scraper_ec.db import Database
            from scraper_ec.csv_importer import import_csv
            db = Database(str(ec_db))
            db.init_schema()
            import_csv(ec_csv, db)
            db.close()
            print("[bootstrap] proyectos_ec.db initialized from CSV snapshot (sin documentos)")
        except Exception as e:
            print(f"[bootstrap] error initializing EC DB from CSV: {e}")

_bootstrap_dbs()


# ─── AUTH GATE (DESHABILITADO temporalmente por bugs de cookies en Streamlit Cloud) ──
# El modulo auth/ queda en el repo y se puede reactivar agregando:
#   from auth.login import gate_or_render
#   if not gate_or_render(): st.stop()
# Por ahora la app es publica — los dashboards muestran data publica del
# Congreso/Asamblea, sin info sensitiva.


# Logo Vali grande en el tope del sidebar.
# (se hace ANTES de la nav para que aparezca arriba de los links.)
# Busca vali_logo.png > .jpg > .jpeg > .webp > .svg en assets/ (primero que
# encuentre, ese usa). Permite dropear el logo oficial en cualquier formato.
_assets_dir = Path(__file__).resolve().parent / "assets"
_logo_path = None
for _ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
    _candidate = _assets_dir / f"vali_logo{_ext}"
    if _candidate.exists():
        _logo_path = _candidate
        break
if _logo_path is not None:
    try:
        st.logo(str(_logo_path), size="large", link=None)
    except Exception:
        # Fallback en versiones viejas de Streamlit
        pass


# ─── CSS adicional: logo más grande + ocultar texto de íconos Material ─────
# Aplica en todas las páginas (app.py se ejecuta antes de cada st.Page).
# Mínimo, defensivo, sin @import ni :has() ni JS — para no romper nada.
st.markdown(
    """<style>
/* Logo grande: forzar el <img> generado por st.logo() a ~140px de alto.
   Streamlit le aplica un max-height chico por default; lo sobreescribimos. */
[data-testid="stSidebarHeader"] {
    min-height: 180px !important;
    padding: 20px 16px !important;
    background-color: #0A294D !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
}
[data-testid="stSidebarHeader"] [data-testid="stLogo"],
[data-testid="stSidebarHeader"] a[data-testid="stLogo"] {
    margin: 0 auto !important;
    display: block !important;
    max-width: 100% !important;
}
[data-testid="stSidebarHeader"] [data-testid="stLogo"] img,
[data-testid="stSidebarHeader"] img {
    max-height: 140px !important;
    height: 140px !important;
    width: auto !important;
    max-width: 100% !important;
    object-fit: contain !important;
}

/* Ocultar el texto crudo "expand_more" / "keyboard_double_arrow_left" / etc.
   que aparece cuando la fuente Material Symbols Rounded de Streamlit no
   carga. Selectores múltiples para cubrir todas las versiones de DOM. */
[data-testid="stSidebar"] [class*="material-symbols"],
[data-testid="stSidebar"] [class*="material-icons"],
[data-testid="stSidebar"] [class*="MaterialSymbols"],
[data-testid="stSidebar"] [class*="MaterialIcons"],
[data-testid="stSidebar"] span.material-symbols-rounded,
[data-testid="stSidebar"] span.material-symbols-outlined,
[data-testid="stSidebar"] span.material-icons-round,
[data-testid="stSidebar"] [aria-hidden="true"]:not([class*="emoji"]):not([class*="flag"]),
/* Por inline style: a veces Streamlit setea font-family directamente */
[data-testid="stSidebar"] [style*="Material Symbols"],
[data-testid="stSidebar"] [style*="material-symbols"],
[data-testid="stSidebar"] [style*="Material Icons"],
/* Por posición DOM: el ícono toggle suele ser el último hijo de un expander */
[data-testid="stSidebarNav"] [aria-expanded] > span:last-child,
[data-testid="stSidebarNav"] [aria-expanded] > div:last-child,
[data-testid="stSidebarNav"] button[aria-expanded] > span:last-child,
[data-testid="stSidebarNav"] [role="button"] > span:last-child,
/* Específicamente nav section headers (Streamlit moderno) */
[data-testid="stSidebarNav"] li > div > span:last-child,
[data-testid="stSidebarNav"] [data-testid*="stSidebarNavSection"] span:last-child {
    font-size: 0 !important;
    line-height: 0 !important;
    color: transparent !important;
    visibility: hidden !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    opacity: 0 !important;
}

/* ─── Transición suave entre páginas ─────────────────────────────────────
   Fade-in del contenedor principal cuando se navega entre páginas.
   Streamlit re-renderiza todo el main al cambiar de página, así que
   esta animación dispara en cada navegación. Sutil, 220ms, sin distraer. */
[data-testid="stMain"] .block-container,
section[data-testid="stMain"] > div {
    animation: pageFadeIn 220ms ease-out;
}
@keyframes pageFadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
}

/* Hover sutil sobre los links del sidebar nav (feedback antes del click) */
[data-testid="stSidebarNav"] a {
    transition: background-color 150ms ease-out, padding-left 150ms ease-out !important;
}
[data-testid="stSidebarNav"] a:hover {
    padding-left: 18px !important;
}

/* ─── Reemplazo de íconos Material Symbols por caracteres unicode ─────────
   DOM real en Streamlit 1.57 (inspeccionado en el browser):
   <header data-testid="stNavSectionHeader">
     <span>Portafolio de herramientas</span>
     <div class="...e1lpckdq7">  <- rota con transform al colapsar
       <span><span data-testid="stIconMaterial">expand_more</span></span>
     </div>
   </header>
   La rotación está en el div padre del ::before, así que se hereda. */
[data-testid="stNavSectionHeader"] [data-testid="stIconMaterial"],
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"] {
    font-size: 0 !important;
    line-height: 0 !important;
    color: transparent !important;
    position: relative !important;
    display: inline-block !important;
    width: 16px !important;
    height: 16px !important;
}
[data-testid="stNavSectionHeader"] [data-testid="stIconMaterial"]::before {
    content: "▼";
    font-size: 11px;
    font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    color: rgba(255,255,255,0.75);
    line-height: 1;
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
}
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"]::before {
    content: "‹";
    font-size: 18px;
    font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    color: #FFFFFF;
    line-height: 1;
    font-weight: 700;
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
}

/* Anular ::before viejo de home.py / pages/1_Peru.py sobre el button del
   sidebar header (causaba doble "‹ ‹" cuando colapsabas el sidebar). */
[data-testid="stSidebarHeader"] button::before,
button[data-testid="stExpandSidebarButton"]::before,
button[data-testid="stSidebarCollapsedControl"]::before,
button[kind="header"]::before {
    content: none !important;
    display: none !important;
}
</style>""",
    unsafe_allow_html=True,
)


# Definir páginas explícitamente.
home = st.Page(
    "home.py",
    title="Inicio",
    icon="🧠",
    default=True,
    url_path="",
)
peru = st.Page(
    "pages/1_Peru.py",
    title="Perú",
    icon="🇵🇪",
    url_path="peru",
)
ecuador = st.Page(
    "pages/2_Ecuador.py",
    title="Ecuador",
    icon="🇪🇨",
    url_path="ecuador",
)
agenda_pe = st.Page(
    "pages/3_Agenda_PE.py",
    title="Perú · Agenda",
    icon="📅",
    url_path="peru-agenda",
)


# Sidebar logout deshabilitado mientras el auth gate este off.


nav = st.navigation(
    {
        "Vali Intelligence": [home],
        "Radar Legislativo": [peru, ecuador],
        "Agenda parlamentaria": [agenda_pe],
    },
    position="sidebar",
)
nav.run()
