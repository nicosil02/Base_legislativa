"""Vali Intelligence — Punto de entrada (router de navegación + auth gate).

Antes de cualquier dashboard:
  - Si [auth] esta en Secrets → exige login con Google (st.user.is_logged_in),
    restringido a @valiconsultores.com. Sin [auth] la app no abre (salvo
    VALI_SIN_LOGIN=1 en el .env de la PC).
  - Monta pages/0_Hoy.py, la unica pagina.

Corre con:
    python -m streamlit run app.py
"""
from __future__ import annotations

import importlib
import os
import threading
from pathlib import Path

import streamlit as st


def _importar(nombre: str):
    """Tras cada push de codigo, Streamlit borra los modulos de la app de
    sys.modules al empezar el siguiente rerun de CADA sesion. Si otra sesion
    estaba importando en ese momento, el import revienta con KeyError
    ('clientes' en los logs de 2026-10-21); reintentar lo arregla."""
    for intento in range(3):
        try:
            return importlib.import_module(nombre)
        except KeyError:
            if intento == 2:
                raise


_abrir_clientes = _importar("clientes.privado").abrir

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


# Las bases ya NO estan en main (sus versiones llevaron el repo a 15 GB,
# 2026-09-27): los workflows las publican en la rama `datos` (ver
# scripts/publicar_db.sh). Antes la app se enteraba de datos nuevos porque
# cada commit de la base la redesplegaba; ahora baja el .gz de `datos` cada
# DATOS_CADA_SEG como mucho, y solo si cambio (ETag -> 304 si no).
DATOS_URL = "https://raw.githubusercontent.com/nicosil02/Base_legislativa/datos/data/{}"
DATOS_CADA_SEG = 1800  # cada rearmado escribe ~400 MB; con 600 era uno cada 10 min todo el dia


def _soltar_cache(path: Path) -> None:
    """Saca de la cache de disco del sistema un archivo recien escrito. En
    Streamlit Cloud esa cache se cuenta como memoria de la app y cada
    rearmado de la base la llenaba ("over resource limits", 2026-11-11)."""
    import os
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)
    except (OSError, AttributeError):  # Windows no tiene posix_fadvise
        pass


def _log_memoria(donde: str) -> None:
    """Deja en los logs la memoria que cuenta el contenedor y de que tipo:
    anon = Python, file = cache de disco. Cinco caidas por "over resource
    limits" sin saber cual de las dos crecia (2026-11-11)."""
    import os
    try:
        cg = Path("/sys/fs/cgroup")
        if (cg / "memory.current").exists():  # cgroup v2
            total, stat, claves = cg / "memory.current", cg / "memory.stat", ("anon", "file", "shmem")
        else:  # cgroup v1
            cg = cg / "memory"
            total, stat, claves = cg / "memory.usage_in_bytes", cg / "memory.stat", ("rss", "cache", "shmem")
        s = dict(linea.split()[:2] for linea in stat.read_text().splitlines())
        mb = lambda v: int(v) // 2**20
        disco = sum(f.stat().st_size for f in _REPO_ROOT.rglob("*.db*") if f.is_file())
        print(f"[memoria] {donde}: total={mb(total.read_text())} MB "
              + " ".join(f"{k}={mb(s.get(k, 0))}" for k in claves)
              + f" | bases en disco={mb(disco)} MB pid={os.getpid()}", flush=True)
    except Exception as e:
        print(f"[memoria] {donde}: no pude leer ({e})", flush=True)


@st.cache_resource
def _estado_descarga_datos() -> dict:
    return {}  # {nombre_gz: (ultimo_chequeo, etag)} - uno por proceso


def _bajar_de_datos(gz_path: Path) -> None:
    """Deja en gz_path la version publicada en `datos` si cambio desde la
    ultima vez. Cualquier fallo (sin red, rama todavia no creada) deja lo
    que haya - el bootstrap sigue igual que antes con el .gz local."""
    import os
    import shutil
    import tempfile
    import time
    import urllib.error
    import urllib.request

    estado = _estado_descarga_datos()
    ultimo, etag = estado.get(gz_path.name, (0.0, None))
    if time.time() - ultimo < DATOS_CADA_SEG:
        return
    estado[gz_path.name] = (time.time(), etag)
    req = urllib.request.Request(DATOS_URL.format(gz_path.name))
    if etag and gz_path.exists():
        req.add_header("If-None-Match", etag)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            gz_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=gz_path.parent, prefix=gz_path.name + ".", suffix=".tmp")
            with os.fdopen(fd, "wb") as f:
                shutil.copyfileobj(r, f)  # r.read() subia el .gz entero a memoria
            os.replace(tmp, gz_path)  # mtime nuevo -> _needs_restore lo ve "stale"
            _soltar_cache(gz_path)
            estado[gz_path.name] = (time.time(), r.headers.get("ETag"))
            print(f"[datos] {gz_path.name} actualizado desde la rama datos")
    except urllib.error.HTTPError as e:
        if e.code != 304:
            print(f"[datos] no pude bajar {gz_path.name}: HTTP {e.code}")
    except Exception as e:
        print(f"[datos] no pude bajar {gz_path.name}: {e}")


def _bootstrap_dbs():
    lock = _get_bootstrap_lock()
    # Con una base ya en disco nadie espera la nueva: se baja y se arma por
    # detras y reemplaza a la anterior de un golpe (os.replace). Hacerlo en la
    # ejecucion dejaba la pantalla en blanco a quien entraba tras cada dato nuevo.
    if (_REPO_ROOT / "proyectos.db").exists():
        if lock.acquire(blocking=False):
            threading.Thread(target=_bootstrap_y_soltar, args=(lock,), daemon=True).start()
        return
    if not lock.acquire(blocking=True, timeout=60):
        return
    try:
        _bootstrap_dbs_impl()
    finally:
        lock.release()


def _bootstrap_y_soltar(lock: threading.Lock) -> None:
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

    import time
    estado = _estado_descarga_datos()
    if time.time() - estado.get("_memoria", 0) >= 600:
        estado["_memoria"] = time.time()
        _log_memoria("control")

    # Perú: decomprimir data/proyectos.db.gz (14 MB) → proyectos.db (78 MB)
    pe_db = repo_root / "proyectos.db"
    pe_gz = repo_root / "data" / "proyectos.db.gz"
    # Publicada en partes, una por dueño (core/partes.py): se bajan y se
    # arma la base completa. Sin partes en `datos`, la base entera de antes.
    partes = _importar("core.partes")
    partes_gz = {p: repo_root / "data" / partes.archivo(p) for p in partes.NOMBRES}
    # TV recortada a lo que muestra la web, si los workflows ya la publican:
    # la parte entera suelta pesa 244 MB y la web solo usa un tercio.
    tvweb = repo_root / "data" / partes.archivo("tvweb")
    _bajar_de_datos(tvweb)
    if tvweb.exists():
        partes_gz["tv"].unlink(missing_ok=True)
        partes_gz["tv"] = tvweb
    for gz in partes_gz.values():
        _bajar_de_datos(gz)
    motivos = [m for gz in partes_gz.values() if (m := _needs_restore(pe_db, gz))]
    if partes_gz["base"].exists():
        if motivos:
            # Una parte descomprimida a la vez y borrada al usarla (core/partes.armar):
            # en Streamlit Cloud el disco cuenta como memoria y tener todas las
            # partes sueltas a la vez (~450 MB) llevo la app a "over resource
            # limits" (2026-10-21, 2026-11-07, 2026-11-08).
            for gz in partes_gz.values():  # las que dejaban versiones anteriores
                gz.with_suffix("").unlink(missing_ok=True)
            try:
                partes.armar(pe_db, {p: gz for p, gz in partes_gz.items() if gz.exists()}, para_web=True)
                _log_memoria("recien armada")
                _soltar_cache(pe_db)
                _log_memoria("cache soltada")
                print(f"[bootstrap] proyectos.db armada ({motivos[0]})")
            except Exception as e:
                print(f"[bootstrap] error armando PE DB: {e}")
        reason = None
    else:
        _bajar_de_datos(pe_gz)
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
    _bajar_de_datos(ec_gz)
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
# Credenciales en [auth] de los Secrets (Streamlit Cloud: Manage app >
# Settings > Secrets). Sin ellas la app no abre (ver mas abajo).
ALLOWED_DOMAIN = "@valiconsultores.com"


def _google_auth_configured() -> bool:
    try:
        return bool(st.secrets.get("auth", {}).get("google", {}).get("client_id"))
    except Exception:
        return False


if not _google_auth_configured() and os.environ.get("VALI_SIN_LOGIN") != "1":
    # Sin login la app escribe al repo y abre datos de clientes a cualquiera
    # con la URL: cerrada salvo en la PC (VALI_SIN_LOGIN=1 en el .env local).
    st.error("Falta configurar el inicio de sesión con Google ([auth] en los "
             "Secrets de Streamlit). La app queda cerrada hasta entonces.")
    st.stop()

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


# Datos de clientes cifrados en el repo (clientes/privado.py): en cada
# ejecucion, por si un deploy nuevo borro el texto sin reiniciar el proceso.
try:
    _abrir_clientes()
except Exception as _e:
    print(f"[clientes] no pude abrir los datos cifrados: {_e}")

st.markdown(
    """<style>
/* Sin el aviso de "Running" ni el gris mientras se recalcula la pagina. */
[data-testid="stStatusWidget"] { display: none !important; }
[data-stale="true"], [data-stale="true"] * { opacity: 1 !important; transition: none !important; }
</style>""",
    unsafe_allow_html=True,
)


# Una sola pagina: toda la interfaz vive en front/ (pages/0_Hoy.py la monta y
# trae su propio menu y su boton de cerrar sesion). Las paginas viejas se
# borraron el 2026-11-03.
nav = st.navigation(
    [st.Page("pages/0_Hoy.py", title="Panel", icon="📊", default=True, url_path="")],
    position="hidden",
)
nav.run()
