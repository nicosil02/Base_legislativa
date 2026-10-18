import sqlite3

from core import partes as P


def _base(path, filas_tv, filas_tx, extra=None):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE proyectos (id INTEGER PRIMARY KEY, titulo TEXT)")
    c.execute("CREATE INDEX ix_tit ON proyectos(titulo)")
    c.execute("INSERT INTO proyectos VALUES (1, 'pl')")
    c.execute("CREATE TABLE tv_vistos (video_id TEXT PRIMARY KEY, texto TEXT)")
    c.executemany("INSERT INTO tv_vistos VALUES (?, ?)", filas_tv)
    c.execute("CREATE TABLE tv_avisos (ts TEXT, video_id TEXT, PRIMARY KEY (ts, video_id))")
    c.execute("CREATE TABLE sesiones_transcripciones (video_id TEXT PRIMARY KEY, texto TEXT NOT NULL)")
    c.executemany("INSERT INTO sesiones_transcripciones VALUES (?, ?)", filas_tx)
    if extra:
        c.execute(extra)
    c.commit()
    c.close()


def test_ida_y_vuelta(tmp_path):
    orig = tmp_path / "orig.db"
    _base(orig, [("v1", "hola")], [("s1", "texto")], "CREATE TABLE tabla_nueva (x)")
    partes = {p: tmp_path / f"{p}.db" for p in P.NOMBRES}
    for p, path in partes.items():
        P.extraer(orig, p, path)
    # la tabla nueva cae en base, las de tv/transcripciones solo en su parte
    tablas = lambda p: {r[0] for r in sqlite3.connect(p).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tablas(partes["base"]) == {"proyectos", "tabla_nueva"}
    assert tablas(partes["tv"]) == {"tv_vistos", "tv_avisos"}
    P.armar(tmp_path / "armada.db", partes)
    c = sqlite3.connect(tmp_path / "armada.db")
    assert c.execute("SELECT texto FROM tv_vistos").fetchone() == ("hola",)
    assert c.execute("SELECT name FROM sqlite_master WHERE name='ix_tit'").fetchone()


def test_unir_no_pisa_y_gana_el_texto_mas_largo(tmp_path):
    local, remoto = tmp_path / "l.db", tmp_path / "r.db"
    _base(local, [("v1", "hola mundo"), ("v2", "x")], [("s1", "corto")])
    _base(remoto, [("v1", "hola"), ("v2", "xyz"), ("v3", "nuevo")], [("s1", "mucho mas largo"), ("s2", "otra")])
    for p in ("tv", "transcripciones"):
        P.extraer(local, p, tmp_path / f"l_{p}.db")
        P.extraer(remoto, p, tmp_path / f"r_{p}.db")
        P.unir(tmp_path / f"l_{p}.db", tmp_path / f"r_{p}.db", p)
    tv = dict(sqlite3.connect(tmp_path / "l_tv.db").execute("SELECT * FROM tv_vistos"))
    tx = dict(sqlite3.connect(tmp_path / "l_transcripciones.db").execute("SELECT * FROM sesiones_transcripciones"))
    assert tv == {"v1": "hola mundo", "v2": "xyz", "v3": "nuevo"}
    assert tx == {"s1": "mucho mas largo", "s2": "otra"}


def test_unir_texto_nulo_no_cuenta_como_cambio(tmp_path):
    local, remoto = tmp_path / "l.db", tmp_path / "r.db"
    _base(local, [("v1", None)], [])
    _base(remoto, [("v1", None)], [])
    P.extraer(local, "tv", tmp_path / "l_tv.db")
    P.extraer(remoto, "tv", tmp_path / "r_tv.db")
    assert P.unir(tmp_path / "l_tv.db", tmp_path / "r_tv.db", "tv") == 0


def test_votaciones_va_en_su_parte_y_se_une_por_fila(tmp_path):
    from votaciones.pleno_bicameral import init_schema
    local, remoto = tmp_path / "l.db", tmp_path / "r.db"
    for path, vid in ((local, "senado:2026-10-07:13:06:v1"), (remoto, "senado:2026-09-30:12:50:v1")):
        _base(path, [], [])
        c = sqlite3.connect(path)
        init_schema(c)
        c.execute("INSERT INTO voto_pleno_nominal VALUES (?, 'X', 'FP', 'SI')", (vid,))
        c.commit()
        c.close()
    P.extraer(local, "base", tmp_path / "base.db")
    P.extraer(local, "votaciones", tmp_path / "l_v.db")
    P.extraer(remoto, "votaciones", tmp_path / "r_v.db")
    tablas = {r[0] for r in sqlite3.connect(tmp_path / "base.db").execute("SELECT name FROM sqlite_master")}
    assert "voto_pleno_nominal" not in tablas and "proyectos" in tablas
    # refrescar-pe (texto) y el OCR escriben votaciones distintas: la union junta las dos
    P.unir(tmp_path / "l_v.db", tmp_path / "r_v.db", "votaciones")
    c = sqlite3.connect(tmp_path / "l_v.db")
    assert c.execute("SELECT COUNT(*) FROM voto_pleno_nominal").fetchone()[0] == 2
