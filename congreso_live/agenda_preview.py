"""Puntos de agenda de HOY para una sesion (comision o Pleno) detectada EN
VIVO - se usan en el aviso inicial de WhatsApp para que Nicolas sepa de
que va la sesion antes de entrar, sin esperar a la transcripcion (esa
llega despues, ver resumenes_store.py - Nicolas 2026-09-17 pidio
explicitamente que la agenda salga del archivo de agenda que YA tenemos,
no de la transcripcion).

Dos fuentes distintas segun el tipo de sesion:
  - Comisiones: tabla `sesiones` + `sesion_agenda_punto` (API vieja, sigue
    viva y al dia para el periodo bicameral).
  - Pleno: tabla `pleno_agenda_pdf` (texto completo del PDF de agenda que
    publica cada camara - `pleno.agenda_pdf` en pleno/, NO `pleno_sesiones`/
    `pleno_tema`, que son de la API vieja y dejaron de recibir filas
    nuevas desde 2026-06-23 porque son del periodo unicameral que ya
    termino - confundir esa tabla con la real hizo pensar en un primer
    pase que el sync de Pleno bicameral estaba roto; no lo esta, solo
    vive en otra tabla). El texto del PDF no trae una lista estructurada
    de puntos como sesion_agenda_punto - se parsea la seccion "ÍNDICE"
    del propio documento (ver _extraer_indice), que es la tabla de
    contenidos corta que cada agenda ya trae.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone

LIMA = timezone(timedelta(hours=-5))
MAX_PUNTOS = 4
MAX_CHARS_PUNTO = 140


def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _camara_de_titulo(titulo: str | None) -> str | None:
    t = _norm(titulo)
    if "diputados" in t:
        return "Diputados"
    if "senado" in t:
        return "Senado"
    return None


_RE_FECHA_TITULO = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")


def _fecha_del_titulo(titulo: str | None) -> str | None:
    """El titulo real de YouTube casi siempre trae la fecha de la sesion
    (ej. "...| 09/09/2026") - a veces mas confiable que `fecha`
    (sesiones_transcripciones.fecha, la fecha UTC de CAPTURA, que puede
    correr 1+ dia por detras si la sesion arranco tarde o se resumio
    despues). None si no hay match o la fecha no es valida."""
    m = _RE_FECHA_TITULO.search(titulo or "")
    if not m:
        return None
    dia, mes, anio = m.groups()
    anio = anio if len(anio) == 4 else f"20{anio}"
    try:
        return datetime(int(anio), int(mes), int(dia)).date().isoformat()
    except ValueError:
        return None


def camara_de_agenda(db: sqlite3.Connection, tipo: str, titulo: str | None,
                     fecha: str | None) -> str | None:
    """Cruza contra la agenda real (tabla `sesiones`, misma fuente que
    puntos_agenda_comision) para resolver la camara de una Comision cuyo
    titulo de YouTube NO la dice - pedido real de Nicolas 2026-09-18: los
    5 comites que se llaman igual en ambas camaras (Constitucion, Defensa
    Nacional, Justicia, Etica, Procedimientos Especiales) solo se pueden
    distinguir por texto cuando el titulo trae el marcador explicito;
    cuando no lo trae, la agenda real (quien tenia sesion agendada ESE
    dia con ese nombre de comision) sí lo sabe.

    Prueba la fecha que trae el propio TITULO (si la trae - ver
    _fecha_del_titulo) y la de `fecha` (fecha UTC de captura,
    sesiones_transcripciones.fecha) +- 1 dia, por el desfase UTC/Lima de
    una sesion que arranca de madrugada. None si ningun dia candidato
    tiene una sesion agendada con ese keyword, o si hay mas de una camara
    candidata - mismo criterio que puntos_agenda_comision: no adivina."""
    if not tipo.startswith("Comision:"):
        return None
    kw = _norm(tipo.split(":", 1)[-1].strip())
    candidatas: set[str] = set()
    del_titulo = _fecha_del_titulo(titulo)
    if del_titulo:
        candidatas.add(del_titulo)
    if fecha:
        try:
            d = datetime.fromisoformat(fecha).date()
            candidatas.add(d.isoformat())
            candidatas.add((d - timedelta(days=1)).isoformat())
        except ValueError:
            pass
    if not candidatas:
        return None
    fechas = tuple(candidatas)
    rows = db.execute(
        f"SELECT nombre_comision, camara FROM sesiones WHERE fecha IN "
        f"({','.join('?' * len(fechas))})", fechas,
    ).fetchall()
    camaras = {_norm(camara) for nombre, camara in rows if camara and kw in _norm(nombre)}
    if camaras == {"senado"}:
        return "Senado"
    if camaras == {"diputados"}:
        return "Diputados"
    return None


def puntos_agenda_comision(db: sqlite3.Connection, tipo: str, titulo: str,
                           max_puntos: int = MAX_PUNTOS) -> list[str]:
    """tipo: 'Comision: <kw>' (ver detector.clasificar_titulo). Busca,
    entre las sesiones de comision agendadas para HOY (hora Lima, no UTC -
    a la noche UTC ya cayo en el dia siguiente), la que matchea por camara
    (inferida del titulo real de YouTube, si se puede) y por el keyword
    como substring de nombre_comision. Si hay 0 o mas de 1 match no
    arriesga a adivinar cual es - devuelve [] antes que mostrar la agenda
    de la comision equivocada."""
    if not tipo.startswith("Comision:"):
        return []
    kw = _norm(tipo.split(":", 1)[-1].strip())
    camara = _camara_de_titulo(titulo)
    hoy_lima = datetime.now(LIMA).date().isoformat()

    rows = db.execute(
        "SELECT id_sesion, nombre_comision, camara FROM sesiones WHERE fecha = ?",
        (hoy_lima,),
    ).fetchall()
    candidatas = [
        r for r in rows
        if kw in _norm(r[1])
        and (camara is None or not r[2] or _norm(r[2]) == _norm(camara))
    ]
    if len(candidatas) != 1:
        return []

    puntos = db.execute(
        """SELECT descripcion_texto FROM sesion_agenda_punto
           WHERE id_sesion=? ORDER BY orden LIMIT ?""",
        (candidatas[0][0], max_puntos),
    ).fetchall()
    return [_una_linea_corta(p[0]) for p in puntos if p[0] and p[0].strip()]


_RE_ROMANO = re.compile(r"[IVXLC]+\.?$")
_RE_HEADER_PAGINA = re.compile(
    r"(agenda del pleno|agenda de la sesi[oó]n del pleno|"
    r"c[aá]mara de diputados|senado de la rep[uú]blica)",
    re.IGNORECASE,
)


def _extraer_indice(texto: str, max_items: int = MAX_PUNTOS) -> list[str]:
    """Los PDFs de agenda (senado.congreso.gob.pe / diputados.congreso.gob.pe)
    traen una seccion "ÍNDICE" (tabla de contenidos corta) antes del
    cuerpo completo (paginas de mociones/oficios enteros, inutilizables
    para un WhatsApp). Se extrae el texto entre "ÍNDICE" y la proxima
    aparicion del encabezado de pagina repetido (que marca donde termina
    el indice y empieza el cuerpo real), se descartan numeros de pagina
    sueltos, y se pega cada numeral romano suelto (bug real de extraccion
    de PDF: a veces "I." queda en su propia linea, separado del titulo)
    con el titulo que le sigue."""
    m = re.search(r"índice", texto, re.IGNORECASE)
    if not m:
        return []
    resto = texto[m.end():]
    m2 = _RE_HEADER_PAGINA.search(resto)
    bloque = resto[:m2.start()] if m2 else resto[:800]

    crudas = [l.strip() for l in bloque.splitlines() if l.strip()]
    crudas = [
        l for l in crudas
        if not re.fullmatch(r"\d+", l)
        and not re.fullmatch(r"p[aá]g\.?", l, re.IGNORECASE)
        and not re.fullmatch(r"índice", l, re.IGNORECASE)
    ]

    out: list[str] = []
    pendiente = ""
    for l in crudas:
        if _RE_ROMANO.fullmatch(l):
            pendiente = l.rstrip(".")
            continue
        out.append(f"{pendiente}. {l}" if pendiente else l)
        pendiente = ""
        if len(out) >= max_items:
            break
    return out


def puntos_agenda_pleno(db: sqlite3.Connection, tipo: str,
                        max_puntos: int = MAX_PUNTOS) -> list[str]:
    """tipo: 'Pleno: Senado'/'Pleno: Diputados' (ver detector.clasificar_titulo).
    'Pleno: Congreso' (sesion conjunta, caso raro/fallback) no tiene una
    camara clara para elegir el PDF correcto - devuelve [] antes que
    adivinar. [] tambien si el PDF de HOY todavia no fue publicado o
    scrapeado (el Congreso a veces lo sube el mismo dia de la sesion, no
    antes - limitacion real de la fuente, no del parser)."""
    camara = {"Pleno: Senado": "senado", "Pleno: Diputados": "diputados"}.get(tipo)
    if not camara:
        return []
    hoy_lima = datetime.now(LIMA).date().isoformat()
    row = db.execute(
        "SELECT texto FROM pleno_agenda_pdf WHERE camara=? AND fecha=? "
        "ORDER BY length(texto) DESC LIMIT 1",
        (camara, hoy_lima),
    ).fetchone()
    if not row:
        return []
    return _extraer_indice(row[0], max_puntos)


def puntos_agenda(db: sqlite3.Connection, tipo: str, titulo: str) -> list[str]:
    """Despacha a comision o Pleno segun el prefijo de `tipo`."""
    if tipo.startswith("Pleno:"):
        return puntos_agenda_pleno(db, tipo)
    return puntos_agenda_comision(db, tipo, titulo)


def _una_linea_corta(texto: str, max_chars: int = MAX_CHARS_PUNTO) -> str:
    """Los puntos de agenda reales son parrafos completos (invitaciones
    con oficio, temas en vinetas, etc.) - inutilizable en un WhatsApp de
    'te interesa entrar o no'. Se queda con la primera linea no vacia y
    la recorta a max_chars."""
    primera = next((l.strip() for l in texto.splitlines() if l.strip()), "")
    if len(primera) > max_chars:
        primera = primera[:max_chars - 1].rstrip() + "…"
    return primera


def agenda_extra_para(v: dict) -> str:
    """Best-effort: abre proyectos.db (mismo _find_db_path que ya usa
    transcripciones.py) y devuelve el bloque de agenda ya formateado para
    pegar al mensaje de WhatsApp de esta sesion - '' si no hay DB, no hay
    match, o cualquier error. Es un nice-to-have: nunca debe romper el
    aviso principal (cmd_check/notify siguen andando igual sin esto)."""
    from congreso_live.transcripciones import _find_db_path

    try:
        db_path = _find_db_path()
        if not db_path.exists():
            return ""
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            puntos = puntos_agenda(conn, v["tipo"], v["titulo"])
        finally:
            conn.close()
        return formatear_para_whatsapp(puntos)
    except Exception:
        return ""


def formatear_para_whatsapp(puntos: list[str]) -> str:
    """'' si no hay puntos, o un bloque tipo:
    \\n\\nPuntos de agenda:\\n- Punto 1\\n- Punto 2"""
    if not puntos:
        return ""
    lineas = "\n".join(f"- {p}" for p in puntos)
    return f"\n\nPuntos de agenda:\n{lineas}"


# ============================================================
# self-check (Ponytail: 1 chequeo ejecutable de la logica no trivial)
# ============================================================

def _demo():
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE TABLE sesiones (id_sesion INTEGER PRIMARY KEY,
        nombre_comision TEXT, camara TEXT, fecha TEXT)""")
    conn.execute("""CREATE TABLE sesion_agenda_punto (id_sesion INTEGER,
        orden INTEGER, descripcion_texto TEXT)""")
    hoy = datetime.now(LIMA).date().isoformat()
    conn.execute("INSERT INTO sesiones VALUES (1, 'Justicia y Derechos Humanos', 'Senado', ?)", (hoy,))
    conn.execute("INSERT INTO sesiones VALUES (2, 'Energia y Minas', 'Diputados', ?)", (hoy,))
    conn.executemany(
        "INSERT INTO sesion_agenda_punto VALUES (1, ?, ?)",
        [(1, "Dictamen sobre reforma penal"), (2, "Informe de la subcomision")],
    )

    # Match unico por keyword + camara -> devuelve los puntos reales.
    puntos = puntos_agenda_comision(
        conn, "Comision: Justicia", "Comisión de Justicia y DDHH del Senado")
    assert puntos == ["Dictamen sobre reforma penal", "Informe de la subcomision"], puntos

    # Camara equivocada (Diputados vs sesion real de Senado) -> sin match, no adivina.
    assert puntos_agenda_comision(
        conn, "Comision: Justicia", "Comisión de Justicia y DDHH de la Cámara de Diputados") == []

    # Comision sin sesion hoy -> sin match.
    assert puntos_agenda_comision(conn, "Comision: Salud", "Comisión de Salud") == []

    # Pleno nunca busca en sesiones de comision.
    assert puntos_agenda_comision(conn, "Pleno: Senado", "Sesión del Pleno del Senado") == []

    # camara_de_agenda: mismo fixture (Justicia = Senado, Energia y Minas =
    # Diputados ese dia) - resuelve por agenda real, sin depender del titulo.
    assert camara_de_agenda(conn, "Comision: Justicia", "sin fecha en el titulo", hoy) == "Senado"
    assert camara_de_agenda(conn, "Comision: Energia Y Minas", "sin fecha", hoy) == "Diputados"
    # Sin sesion agendada ese dia con ese keyword -> no adivina.
    assert camara_de_agenda(conn, "Comision: Salud", "sin fecha", hoy) is None
    # Un dia antes de `hoy` (UTC de madrugada = Lima del dia anterior) tambien
    # se prueba - la sesion del fixture sigue estando en `hoy`, cae dentro
    # de la ventana de 2 fechas al pedir "manana" (fecha UTC = hoy+1).
    _manana = (datetime.now(LIMA).date() + timedelta(days=1)).isoformat()
    assert camara_de_agenda(conn, "Comision: Justicia", "sin fecha", _manana) == "Senado"
    # Pleno no tiene camara ambigua que resolver via `sesiones` (comisiones).
    assert camara_de_agenda(conn, "Pleno: Senado", "sin fecha", hoy) is None
    # La fecha del TITULO (mas confiable que `fecha` de captura, ver
    # _fecha_del_titulo) alcanza sola, incluso si `fecha` no tiene nada que
    # ver - bug real 2026-09-18: un titulo con "09/09/2026" pero fetched_at
    # del 10/09 quedaba "Sin confirmar" porque solo se probaba `fecha` +-1.
    assert camara_de_agenda(
        conn, "Comision: Justicia", f"Sesión de la Comisión | {hoy[8:10]}/{hoy[5:7]}/{hoy[:4]}",
        "2099-01-01") == "Senado"

    assert formatear_para_whatsapp([]) == ""
    assert formatear_para_whatsapp(["A", "B"]) == "\n\nPuntos de agenda:\n- A\n- B"

    # Puntos reales son parrafos multi-linea largos con oficios/vinetas -
    # se queda solo con la primera linea, recortada.
    assert _una_linea_corta("Primera línea del punto\n\nDetalle largo despues") == "Primera línea del punto"
    assert _una_linea_corta("x" * 200) == "x" * 139 + "…"

    # --- Pleno: pleno_agenda_pdf, formato real del PDF (verificado en
    # vivo 2026-09-17 contra las agendas reales de Senado/Diputados) -
    # numerales romanos en su propia linea, encabezado de pagina repetido
    # que marca donde termina el indice, numeros de pagina sueltos.
    conn.execute("""CREATE TABLE pleno_agenda_pdf (camara TEXT, fecha TEXT, texto TEXT)""")
    texto_pdf = (
        "Agenda del Pleno del Senado\n"
        "Sesión del jueves\n\n"
        "SENADO DE LA REPÚBLICA | Área de Relatoría y Agenda\n2\n"
        "ÍNDICE\nPág.\n\nÍndice\n2\n"
        "I.\nConcurrencia de ministro de Estado\n3\n"
        "II.\nOficios del Poder Ejecutivo\n4\n\n"
        "Agenda del Pleno del Senado\n"
        "SENADO DE LA REPÚBLICA | Área de Relatoría y Agenda\n3\n"
        "I. CONCURRENCIA DE MINISTRO DE ESTADO\n(cuerpo completo, paginas y paginas)..."
    )
    conn.execute("INSERT INTO pleno_agenda_pdf VALUES ('senado', ?, ?)", (hoy, texto_pdf))
    assert puntos_agenda_pleno(conn, "Pleno: Senado") == [
        "I. Concurrencia de ministro de Estado", "II. Oficios del Poder Ejecutivo",
    ]
    assert puntos_agenda_pleno(conn, "Pleno: Diputados") == [], "diputados no tiene PDF hoy en este fixture"
    assert puntos_agenda_pleno(conn, "Pleno: Congreso") == [], "sesion conjunta - no hay camara clara, no adivina"

    # El dispatcher puntos_agenda() elige la fuente correcta por prefijo.
    assert puntos_agenda(conn, "Pleno: Senado", "cualquier titulo") == [
        "I. Concurrencia de ministro de Estado", "II. Oficios del Poder Ejecutivo",
    ]
    assert puntos_agenda(conn, "Comision: Justicia", "Comisión de Justicia y DDHH del Senado") == \
        ["Dictamen sobre reforma penal", "Informe de la subcomision"]

    print("OK agenda_preview: matchea por camara+keyword/PDF del dia y no adivina si es ambiguo")


if __name__ == "__main__":
    _demo()
