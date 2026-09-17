"""Puntos de agenda de HOY para una comision detectada EN VIVO - se usan
en el aviso inicial de WhatsApp para que Nicolas sepa de que va la sesion
antes de entrar, sin esperar a la transcripcion (esa llega despues, ver
resumenes_store.py - Nicolas 2026-09-17 pidio explicitamente que la
agenda salga del archivo de agenda que YA tenemos, no de la transcripcion).

LIMITACION real encontrada en vivo 2026-09-17: `pleno_sesiones` no tiene
NINGUNA fila desde 2026-06-23 (sigue en el periodo unicameral viejo) - el
sync de agenda del Pleno bicameral esta roto o sin publicar, no se
investigo a fondo esta sesion. Por eso este modulo solo da preview para
comisiones (tabla `sesiones` + `sesion_agenda_punto`, con datos reales de
hoy verificados en vivo) - para 'Pleno: X' siempre devuelve [] hasta que
ese sync se arregle en otra sesion.
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
            puntos = puntos_agenda_comision(conn, v["tipo"], v["titulo"])
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

    assert formatear_para_whatsapp([]) == ""
    assert formatear_para_whatsapp(["A", "B"]) == "\n\nPuntos de agenda:\n- A\n- B"

    # Puntos reales son parrafos multi-linea largos con oficios/vinetas -
    # se queda solo con la primera linea, recortada.
    assert _una_linea_corta("Primera línea del punto\n\nDetalle largo despues") == "Primera línea del punto"
    assert _una_linea_corta("x" * 200) == "x" * 139 + "…"

    print("OK agenda_preview: matchea por camara+keyword del dia y no adivina si es ambiguo")


if __name__ == "__main__":
    _demo()
