"""proyectos.db publicada en partes, una por dueño (rama `datos`).

Antes cada workflow subia la base entera y merge_db rescataba de la version
publicada solo las tablas de una lista fija: una tabla nueva fuera de la
lista se perdia sin aviso. Ahora cada workflow publica solo las partes que
escribe y quien necesita la base la arma de nuevo, igual que siempre:

  transcripciones  sesiones_transcripciones y sesiones_turnos (vigilante, backfills, oradores, refrescar-pe)
  tv               tv_* y videos_autoridades (workflows de TV)
  votaciones       votaciones nominales del Pleno (refrescar-pe: PDF de texto;
                   votaciones-ocr-bicameral: los escaneados)
  base             todo lo demas (solo refrescar-pe); una tabla nueva cae aca

Las partes con varios escritores se unen fila por fila al publicar (union):
nunca se pisa una fila ajena, y en transcripciones gana el texto mas largo.

    python -m core.partes armar DESTINO.db PARTES_DIR      # parte.db.gz -> base completa
    python -m core.partes extraer ORIGEN.db PARTE SALIDA.db
    python -m core.partes unir LOCAL_PARTE.db REMOTO_PARTE.db PARTE
    python -m core.partes web PARTE_TV.db SALIDA.db         # tv solo con lo que lee la web
"""
from __future__ import annotations

import gc
import gzip
import shutil
import sqlite3
import sys
import time
from pathlib import Path

PARTES = {
    "transcripciones": ["sesiones_transcripciones", "sesiones_turnos"],
    "tv": ["tv_vistos", "tv_menciones", "tv_avisos", "videos_autoridades"],
    "votaciones": ["votacion_pleno", "voto_pleno_nominal", "pleno_votacion_pdf", "pleno_votacion_ocr"],
}
NOMBRES = ["base", *PARTES]


def archivo(parte: str) -> str:
    """Nombre del .gz de la parte en data/ de la rama `datos`."""
    return f"proyectos.{parte}.db.gz"


def _tablas(conn: sqlite3.Connection, esquema: str = "main") -> list[str]:
    return [r[0] for r in conn.execute(
        f"SELECT name FROM {esquema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def _copiar_tabla(conn: sqlite3.Connection, desde: str, tabla: str, donde: str = "") -> None:
    """Crea `tabla` (con indices) en main a partir del esquema `desde` y copia
    las filas (solo las que cumplen `donde`, si se da)."""
    for (sql,) in conn.execute(
            f"SELECT sql FROM {desde}.sqlite_master WHERE tbl_name=? AND sql IS NOT NULL "
            f"ORDER BY type='index'", (tabla,)):
        conn.execute(sql)
    conn.execute(f'INSERT INTO main."{tabla}" SELECT * FROM {desde}."{tabla}"' + (f" WHERE {donde}" if donde else ""))


def extraer(origen: Path, parte: str, salida: Path) -> None:
    """Deja en `salida` solo las tablas de `parte` de la base `origen`."""
    salida.unlink(missing_ok=True)
    if parte == "base":
        src = sqlite3.connect(origen)
        src.execute("VACUUM INTO ?", (str(salida),))
        src.close()
        conn = sqlite3.connect(salida)
        for partes in PARTES.values():
            for t in partes:
                conn.execute(f'DROP TABLE IF EXISTS "{t}"')
        conn.commit()
        conn.execute("VACUUM")
        conn.close()
        return
    conn = sqlite3.connect(salida)
    conn.execute("ATTACH DATABASE ? AS o", (str(origen),))
    hay = set(_tablas(conn, "o"))
    for t in PARTES[parte]:
        if t in hay:
            _copiar_tabla(conn, "o", t)
    conn.commit()
    conn.close()


# La web solo lee el texto de TV de las menciones de los ultimos 14 dias
# (front/vistas.py) y tv_vistos.texto ya pasa los 200 MB: la app arma sin el
# resto, que en Streamlit Cloud la llevaba a "over resource limits" (2026-11-07).
SOLO_WEB = {"tv_vistos": "video_id IN (SELECT video_id FROM p.tv_menciones "
                         "WHERE first_seen_at >= datetime('now', '-14 days'))"}


def recortar_web(origen: Path, salida: Path) -> None:
    """Deja en `salida` la parte `origen` solo con las filas que lee la web
    (SOLO_WEB). Los workflows de TV la publican como parte `tvweb` y la app
    baja esa: la parte tv entera suelta (244 MB) era el pico de disco en cada
    rearmado (2026-11-11)."""
    salida.unlink(missing_ok=True)
    conn = sqlite3.connect(salida)
    conn.execute("ATTACH DATABASE ? AS p", (str(origen),))
    for t in _tablas(conn, "p"):
        _copiar_tabla(conn, "p", t, SOLO_WEB.get(t, ""))
    conn.commit()
    conn.close()


def _descomprimir(gz: Path, destino: Path) -> Path:
    with gzip.open(gz, "rb") as f_in, open(destino, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    return destino


def armar(destino: Path, partes: dict[str, Path], para_web: bool = False) -> None:
    """Base completa en `destino` = base + las otras partes. Atomico: se
    escribe al lado y se reemplaza (la app puede estar leyendo).
    Las partes pueden venir en .gz: se descomprimen de a una al lado de
    `destino` y se borra esa copia al usarla (el .gz queda).
    para_web: copia solo las filas de SOLO_WEB y consume las partes sueltas
    (mueve la base y borra cada parte al usarla) para no tener todo dos veces
    en disco (en Streamlit Cloud el disco cuenta como memoria)."""
    donde = SOLO_WEB if para_web else {}
    tmp = destino.with_name(destino.name + ".armando")
    if partes["base"].suffix == ".gz":
        _descomprimir(partes["base"], tmp)
    else:
        (shutil.move if para_web else shutil.copyfile)(partes["base"], tmp)
    conn = sqlite3.connect(tmp)
    for parte, path in partes.items():
        if parte == "base" or not path.exists():
            continue
        gz = path.suffix == ".gz"
        if gz:
            path = _descomprimir(path, destino.with_name(f"{destino.name}.{parte}.suelta"))
        conn.execute("ATTACH DATABASE ? AS p", (str(path),))
        for t in _tablas(conn, "p"):
            conn.execute(f'DROP TABLE IF EXISTS main."{t}"')
            _copiar_tabla(conn, "p", t, donde.get(t, ""))
        conn.commit()
        conn.execute("DETACH DATABASE p")
        if gz or para_web:
            path.unlink()
    conn.close()
    # Windows no deja reemplazar un archivo abierto y la app lee la base en
    # conexiones cortas: se reintenta hasta un minuto (el 11/11/2026 fallaba
    # con WinError 5 y la PC se quedaba con los datos del arranque).
    for intento in range(30):
        try:
            tmp.replace(destino)
            return
        except PermissionError:
            if intento == 29:
                raise
            gc.collect()  # cierra las conexiones que nadie usa ya
            time.sleep(2)


def unir(local: Path, remoto: Path, parte: str) -> int:
    """Suma a `local` las filas de `remoto` (lo que publicaron otros
    workflows) sin pisar las propias. Devuelve cuantas filas cambiaron."""
    conn = sqlite3.connect(local)
    conn.execute("ATTACH DATABASE ? AS r", (str(remoto),))
    propias = set(_tablas(conn))
    for t in _tablas(conn, "r"):
        info = list(conn.execute(f'PRAGMA table_info("{t}")'))
        if t not in propias:
            _copiar_tabla(conn, "r", t)
        elif "texto" in {c[1] for c in info}:
            # transcripciones y TV en vivo crecen mientras dura la sesion:
            # la version con mas texto es la mas nueva.
            cols = ", ".join(f'"{c[1]}"' for c in info)
            misma = " AND ".join(f'b."{c[1]}" = d."{c[1]}"' for c in info if c[5])
            conn.execute(f"""
                INSERT OR REPLACE INTO "{t}" ({cols}) SELECT {cols} FROM r."{t}" AS d
                WHERE NOT EXISTS (SELECT 1 FROM "{t}" b
                                  WHERE {misma} AND length(coalesce(b.texto, '')) >= length(coalesce(d.texto, '')))""")
        else:
            conn.execute(f'INSERT OR IGNORE INTO "{t}" SELECT * FROM r."{t}"')
    conn.commit()
    n = conn.total_changes
    conn.close()
    return n


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "armar":
        destino, carpeta = Path(args[0]), Path(args[1])
        armar(destino, {p: carpeta / archivo(p).removesuffix(".gz") for p in NOMBRES})
    elif cmd == "extraer":
        extraer(Path(args[0]), args[1], Path(args[2]))
    elif cmd == "web":
        recortar_web(Path(args[0]), Path(args[1]))
    elif cmd == "unir":
        print(f"[partes] {unir(Path(args[0]), Path(args[1]), args[2])} fila(s) de otros workflows")
    else:
        raise SystemExit(__doc__)
