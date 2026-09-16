"""Vali Intelligence — Punto de entrada (router de navegación + auth gate).

Antes de cualquier dashboard:
  - Si [auth] esta en Secrets → exige login con Google (st.user.is_logged_in),
    restringido a @valiconsultores.com. Sin [auth] configurado, la app queda
    publica (sin gate) - ver el bloque AUTH GATE mas abajo.
  - Registra paginas en st.navigation y corre el router.

Corre con:
    python -m streamlit run app.py
"""
from __future__ import annotations

import os
import threading
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


# Favicon: usamos el logo oficial de Vali (assets/vali_favicon.png, 192x192).
# Streamlit acepta path string en page_icon y lo sirve como favicon en todas
# las pestanas. Fallback al emoji si el archivo no esta.
_favicon = Path(__file__).resolve().parent / "assets" / "vali_favicon.png"
st.set_page_config(
    page_title="Vali Intelligence",
    page_icon=str(_favicon) if _favicon.exists() else "🧠",
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
#
# Bug real en vivo 2026-09-14 (logs de Streamlit Cloud): decenas de
# "restored from gz (stale...)" disparandose en rafaga, una por cada
# sesion/rerun concurrente (Streamlit Cloud corre las sesiones como
# threads en UN proceso) - cada thread decide "hay que restaurar" y
# reescribe el MISMO proyectos.db al mismo tiempo. El os.replace()
# atomico protege a un lector de ver un archivo a medio escribir, pero
# no evita que dos threads pisen el destino en simultaneo - en el
# filesystem no persistente de Streamlit Cloud eso termino en
# "database disk image is malformed" de forma reproducible. Un lock a
# nivel de proceso serializa todos los intentos: el primer thread
# restaura, los demas ven el resultado ya bueno y no hacen nada.
#
# OJO: un `threading.Lock()` a nivel de modulo NO alcanza. Streamlit
# reejecuta app.py entero en cada rerun de cada sesion (es como corre
# el script), asi que una asignacion a nivel de modulo crea un Lock
# NUEVO en cada rerun - nunca se comparte entre threads, el "fix" no
# serializaba nada (confirmado en vivo: seguia re-restaurando "corrupto"
# en rafaga incluso con el lock puesto). st.cache_resource si garantiza
# un unico objeto por proceso, compartido entre reruns y sesiones -
# es la herramienta hecha justo para esto (recursos no serializables
# tipo locks/conexiones).
@st.cache_resource
def _get_bootstrap_lock() -> threading.Lock:
    return threading.Lock()


def _bootstrap_dbs():
    lock = _get_bootstrap_lock()
    if not lock.acquire(blocking=True, timeout=60):
        return
    try:
        _bootstrap_dbs_impl()
    finally:
        lock.release()


def _bootstrap_dbs_impl():
    import gzip
    import os
    import shutil

    def _esta_corrupto(db_path: Path) -> bool:
        """Chequeo barato: si el archivo no abre ni una query trivial,
        esta corrupto (ej. 'database disk image is malformed', visto en
        vivo 2026-09-14 en Streamlit Cloud) y hay que re-descomprimir sin
        importar el mtime."""
        import sqlite3
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
            conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            conn.close()
            return False
        except sqlite3.DatabaseError:
            return True

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
        if _esta_corrupto(db_path):
            return "corrupto"
        return None

    def _descomprimir_atomico(gz_path: Path, db_path: Path) -> None:
        """Descomprime a un .tmp en el mismo directorio y hace os.replace()
        al final (atomico en el mismo filesystem, POSIX y Windows) - nunca
        deja el archivo destino en un estado truncado/a medio escribir.
        Bug real encontrado en vivo 2026-09-14: db_path.open("wb") trunca
        el archivo al instante y `shutil.copyfileobj` tarda varios segundos
        en terminar (el PE .db descomprimido pesa ~78 MB) - si otra sesion
        de Streamlit (multiples usuarios/pestañas comparten el mismo
        contenedor, y Streamlit Cloud corre las sesiones como threads
        dentro de UN solo proceso - mismo PID) corre una query SELECT
        mientras tanto, ve un sqlite truncado y tira sqlite3.DatabaseError.
        Mas probable justo despues de un redeploy (contenedor fresco,
        todas las sesiones bootstrapean a la vez). tempfile.mkstemp da un
        nombre unico incluso entre threads del mismo PID, asi que dos
        bootstraps concurrentes nunca pisan el mismo .tmp."""
        import tempfile
        fd, tmp_name = tempfile.mkstemp(
            dir=db_path.parent, prefix=db_path.name + ".", suffix=".tmp",
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as f_out, gzip.open(gz_path, "rb") as f_in:
                shutil.copyfileobj(f_in, f_out)
                f_out.flush()
                os.fsync(f_out.fileno())
            os.replace(tmp_path, db_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    repo_root = Path(__file__).resolve().parent

    # Perú: decomprimir data/proyectos.db.gz (14 MB) → proyectos.db (78 MB)
    pe_db = repo_root / "proyectos.db"
    pe_gz = repo_root / "data" / "proyectos.db.gz"
    reason = _needs_restore(pe_db, pe_gz)
    if reason:
        try:
            _descomprimir_atomico(pe_gz, pe_db)
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
            _descomprimir_atomico(ec_gz, ec_db)
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

    # Garantizar que el schema completo (incluyendo tablas nuevas como
    # unificacion_*) existe en la DB EC. Necesario porque los snapshots
    # commiteados por workflows viejos pueden no tenerlas. init_schema usa
    # CREATE TABLE IF NOT EXISTS, asi que es idempotente y seguro.
    if ec_db.exists():
        try:
            from scraper_ec.db import Database
            db = Database(str(ec_db))
            db.init_schema()
            db.close()
        except Exception as e:
            print(f"[bootstrap] no se pudo asegurar schema EC: {e}")


_bootstrap_dbs()


# ─── AUTH GATE (Google, via st.login nativo de Streamlit) ──────────────────
# Reemplaza el viejo sistema de magic-link (auth/login.py, borrado
# 2026-09-16) que tenia un bug real de cookies en Streamlit Cloud: la
# cookie vi_session SI se seteaba (confirmado con DevTools) pero el
# servidor no la leia al navegar a /peru o /ecuador (paginas = URLs
# distintas = requests nuevos) - problema de timing/scope del hack de
# "cookie via JS en un iframe". st.login() usa la cookie de sesion propia
# de Streamlit (firmada server-side via Authlib), asi que no depende de
# ese hack y no deberia repetir esa clase de bug.
#
# Se activa SOLO si [auth] esta configurado en Secrets (Streamlit Cloud:
# Manage app > Settings > Secrets) - mientras no este configurado, la app
# sigue publica como hasta ahora. Deploy seguro: este commit no le rompe
# el acceso a nadie hasta que se agreguen las credenciales de Google.
ALLOWED_DOMAIN = "@valiconsultores.com"


def _google_auth_configured() -> bool:
    try:
        return bool(st.secrets.get("auth", {}).get("google", {}).get("client_id"))
    except Exception:
        return False


if _google_auth_configured():
    if not st.user.is_logged_in:
        st.markdown(
            "<div style='max-width:440px;margin:14vh auto 0 auto;text-align:center;"
            "font-family:Inter,-apple-system,sans-serif;'>"
            "<div style='font-size:11px;font-weight:800;letter-spacing:0.28em;"
            "text-transform:uppercase;color:#0A294D;margin-bottom:10px;'>"
            "Asuntos Públicos · Vali Consultores</div>"
            "<h1 style=\"font-family:Georgia,'Times New Roman',serif;"
            "font-size:2.6rem;font-weight:400;letter-spacing:-0.01em;"
            "color:#0A294D;margin:0 0 12px 0;\">Vali Intelligence</h1>"
            "<p style='font-size:14px;color:#435D74;margin-bottom:28px;'>"
            "Inicia sesión con tu cuenta de Google "
            "<strong>@valiconsultores.com</strong> para continuar.</p></div>",
            unsafe_allow_html=True,
        )
        _cols = st.columns([1, 1.2, 1])
        with _cols[1]:
            if st.button("Iniciar sesión con Google", use_container_width=True,
                         type="primary"):
                st.login("google")
        st.stop()

    if not st.user.email.endswith(ALLOWED_DOMAIN):
        st.error(
            f"Solo cuentas {ALLOWED_DOMAIN} pueden acceder a Vali Intelligence. "
            f"Conectado como {st.user.email}."
        )
        if st.button("Cerrar sesión"):
            st.logout()
        st.stop()

    # Registra al usuario en data/users.json si es su primer login (idempotente)
    # - alerts/cli.py lo usa como lista de destinatarios de las alertas diarias.
    try:
        from auth.store import register
        register(st.user.email)
    except Exception as e:
        print(f"[auth] no se pudo registrar {st.user.email}: {e}")


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

/* ─── Transición de página ──────────────────────────────────────────────
   Streamlit re-renderiza el main al navegar — no podemos hacer exit
   animations (la pagina vieja desaparece instantaneamente). Pero sí
   podemos hacer un entry suave y elegante.

   Curva: cubic-bezier(.16,1,.3,1) — "expo-out", la mas elegante para
   UI moderna (Apple/Linear/Vercel la usan). Acelera al inicio y se
   asienta despacio al final, no se siente forzado.

   Duracion: 360ms, suficiente para que el ojo lo registre como
   transicion (no flicker) pero rapido para no sentir lag. */
[data-testid="stMain"] .block-container {
    animation: pageEnter 360ms cubic-bezier(.16,1,.3,1) both;
}
@keyframes pageEnter {
    from {
        opacity: 0;
        transform: translateY(8px) scale(.995);
        filter: blur(2px);
    }
    to {
        opacity: 1;
        transform: translateY(0) scale(1);
        filter: blur(0);
    }
}

/* Hover sutil sobre los links del sidebar nav (feedback antes del click) */
[data-testid="stSidebarNav"] a {
    transition: background-color 180ms cubic-bezier(.16,1,.3,1),
                padding-left 180ms cubic-bezier(.16,1,.3,1) !important;
}
[data-testid="stSidebarNav"] a:hover {
    padding-left: 18px !important;
}
[data-testid="stSidebarNav"] a:active {
    transform: scale(.98);
}

/* ─── Country-card press feedback ────────────────────────────────────────
   Cuando clickeas la card del home, antes de navegar mostramos una
   contraccion sutil + sombra interna. Eso le da "peso" al click y
   suaviza la sensacion de cambio de pagina (porque el browser tarda
   ~200-400ms en empezar a renderear la pagina nueva). */
a.country-card {
    transition: border-color 220ms cubic-bezier(.16,1,.3,1),
                transform 220ms cubic-bezier(.16,1,.3,1),
                box-shadow 220ms cubic-bezier(.16,1,.3,1) !important;
    will-change: transform;
}
a.country-card:active {
    transform: translateY(-1px) scale(.985) !important;
    box-shadow: 0 2px 8px rgba(10,41,77,.12) !important;
    transition-duration: 80ms !important;
}

/* ─── Stagger de cards al entrar a la pagina ─────────────────────────────
   Cuando carga el home, las cards aparecen con un pequeño delay entre
   ellas (50-100ms cada una) creando una cascada visual. Sutil pero
   marca diferencia vs aparecer todas a la vez. */
.country-card {
    animation: cardEnter 420ms cubic-bezier(.16,1,.3,1) both;
}
[data-testid="stColumn"]:nth-child(1) .country-card { animation-delay: 60ms; }
[data-testid="stColumn"]:nth-child(2) .country-card { animation-delay: 140ms; }
[data-testid="stColumn"]:nth-child(3) .country-card { animation-delay: 220ms; }
@keyframes cardEnter {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
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
    title="Perú",
    icon="🇵🇪",
    url_path="peru-agenda",
)
agenda_ec = st.Page(
    "pages/4_Agenda_EC.py",
    title="Ecuador",
    icon="🇪🇨",
    url_path="ecuador-agenda",
)
noticias_pe = st.Page(
    "pages/5_Noticias_PE.py",
    title="Perú",
    icon="🇵🇪",
    url_path="peru-noticias",
)
noticias_ec = st.Page(
    "pages/6_Noticias_EC.py",
    title="Ecuador",
    icon="🇪🇨",
    url_path="ecuador-noticias",
)
alertas = st.Page(
    "pages/7_Alertas.py",
    title="Borradores",
    icon="📝",
    url_path="alertas",
)


if _google_auth_configured() and st.user.is_logged_in:
    with st.sidebar:
        st.caption(f"👤 {st.user.email}")
        # Bug real 2026-09-16: las paginas fuerzan "color:#FFFFFF !important"
        # en TODO el sidebar (section[data-testid="stSidebar"] *), asi que el
        # boton secundario por defecto (fondo blanco) terminaba con texto
        # blanco sobre fondo blanco - invisible. Selector mas especifico
        # (div[data-testid="stButton"] ademas de section[...]) le gana a esa
        # regla sin importar el orden en que se inyecten.
        st.markdown(
            """<style>
            section[data-testid="stSidebar"] div[data-testid="stButton"] button {
                background-color: #FFFFFF !important;
                border: 1px solid #FFFFFF !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stButton"] button p,
            section[data-testid="stSidebar"] div[data-testid="stButton"] button span {
                color: #0A294D !important;
            }
            section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
                background-color: #F4F6F8 !important;
                border-color: #F4F6F8 !important;
            }
            </style>""",
            unsafe_allow_html=True,
        )
        if st.button("Cerrar sesión", use_container_width=True):
            st.logout()


nav = st.navigation(
    {
        "Vali Intelligence": [home],
        "Radar Legislativo": [peru, ecuador],
        "Agenda parlamentaria": [agenda_pe, agenda_ec],
        "Noticias y coyuntura": [noticias_pe, noticias_ec],
        "Alertas": [alertas],
    },
    position="sidebar",
)
nav.run()
