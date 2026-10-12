"""Atribucion de oradores en transcripciones de Pleno/Comision, por texto.

Whisper no sabe quien habla. Pero en el Congreso (PE) y la Asamblea (EC)
la Presidencia anuncia a cada orador antes de que hable: "tiene la palabra
el diputado X", "le damos la palabra a la senadora Y", "adelante,
asambleista Z". Este modulo corta el texto en esos anuncios y le asigna
cada tramo a la persona anunciada. Sirve para el reporte semanal ("se
presento X, afirmo Y, ante ello Z cuestiono").

Sin audio ni modelos: regex + difflib contra el padron de legisladores
(autores de PLs 2026-2031 en PE, proponentes en EC). No esta conectado a
ningun pipeline todavia.

Uso: python -m congreso_live.oradores test
     python -m congreso_live.oradores RUTA.db VIDEO_ID [ec.db]
"""
from __future__ import annotations

import difflib
import re
import sqlite3
import sys
import unicodedata

# ponytail: heuristica de texto. Falla cuando Whisper se come el anuncio,
# cuando alguien interrumpe sin que la Presidencia lo anuncie, o cuando el
# nombre sale muy deformado. Si hace falta mas, diarizacion de audio.

_ROL = (r"(?:congresistas?|senador(?:a|es)?|diputad[oa]s?|asamble[ií]stas?|samble[ií]stas?|"
        r"legislador(?:a)?|ministr[oa]|viceministr[oa]|gobernador(?:a)?|alcalde(?:sa)?|"
        r"titular|economista|doctor(?:a)?|ingenier[oa]|abogad[oa]|general|"
        r"vocer[oa]|presidente|presidenta|consejal(?:a)?|colega)")
_ART = r"(?:(?:el|la|al|del|a\s+la|a)\s+)?(?:(?:se[ñn]or(?:a|ita)?)\s+)?"
# Nombre: hasta 7 palabras, corta en signos y en las colas tipicas del
# anuncio ("por dos minutos", "hasta por 20 minutos", "adelante").
_NOMBRE = (r"(?P<nombre>(?:(?!(?:por|hasta|para|adelante|minutos?|y|que|quien|tiene|gracias)\b)"
           r"[\wáéíóúñü'-]+\s*){0,7})")
_CUE = re.compile(
    r"(?i)\b(?:"  # \b: "acceder a la Republica" no es "cedo a ..."
    # "tiene la palabra el diputado X", "tiene el uso de la palabra la senadora Y"
    r"tien(?:e|en|de)\s+(?:usted\s+)?(?:el\s+uso\s+de\s+)?la\s+palabra,?\s+"
    r"|(?:le\s+)?(?:damos\s+la\s+intervenci[oó]n|damos|doy|otorgo|otorgamos|cedo|ceder(?:le)?|concedo|"
    r"vamos\s+a\s+dar(?:le)?|otorg[oó])\s+(?:(?:el\s+)?uso\s+de\s+)?(?:la\s+palabra\s+)?"
    r"|(?:est[aá]|ha)\s+(?:en\s+el\s+)?uso\s+de\s+la\s+palabra,?\s+"
    # Pleno EC: "escuchamos la intervencion de la asambleista X", "interviene el legislador Y"
    r"|intervenci[oó]n\s+de(?:l)?\s+|interviene\s+"
    r"|adelante,?\s+"
    r")" + _ART + r"(?P<rol>" + _ROL + r")?\b,?\s*" + _NOMBRE)
# "Senor gobernador, tiene usted la palabra" (rol antes del verbo).
_CUE_INV = re.compile(
    r"(?i)(?:se[ñn]or(?:a|ita)?\s+)?\b(?P<rol>" + _ROL + r")\b,?\s*" + _NOMBRE +
    r"(?:,?\s*por\s+favor)?,?\s*tiene\s+(?:usted\s+)?(?:(?:el\s+)?uso\s+de\s+)?la\s+palabra")
# Comisiones: la mesa solo llama "Diputado Garcia." y el orador arranca con
# el saludo. Sin verbo, asi que se exige nombre en mayuscula + saludo.
_CUE_LLAMADO = re.compile(
    r"(?:^|(?<=[.?!]\s))(?P<rol>[Cc]ongresista|[Ss]enador(?:a)?|[Dd]iputad[oa]|[Aa]samble[ií]sta|"
    r"[Ll]egislador(?:a)?)\s+(?P<nombre>[A-ZÁÉÍÓÚÑ][\wáéíóúñü-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñü-]+){0,2})"
    r"[.,]\s+(?=(?:[Mm]uchas\s+)?[Gg]racias|[Bb]uen[oa]s|[Ss]e[ñn]or|[Pp]resident)")
# Lo que la Presidencia dice al cerrar un turno; se separa como "Presidencia".
_CIERRE = re.compile(
    r"(?i)(?:tiempo(?:\s+cumplido)?|(?:muchas\s+|much[ií]simas\s+)?gracias,?\s+(?:se[ñn]or(?:a|ita)?\s+)?"
    + _ROL.replace("|presidente|presidenta", "") + r"|a\s+usted(?:es)?\s+(?:las?|le)?\s*gracias)\b")
_PARTIDOS = re.compile(
    r"(?i)\b(?:de(?:l)?\s+)?(?:partido\s+)?(?:fuerza\s+popular|renovaci[oó]n\s+popular|juntos?\b.*|"
    r"buen\s+gobierno|ahora\s+naci[oó]n|c[ií]vico\s+obras|obras|podemos|per[uú]\s+libre|"
    r"somos\s+per[uú]|alianza\s+para\s+el\s+progreso|app|avanza\s+pa[ií]s|acci[oó]n\s+popular|"
    r"revoluci[oó]n\s+ciudadana|adn|construye|pachakutik|psc)\b.*$")
_SIN_NOMBRE = {"", "usted", "uso", "palabra", "la", "el", "de", "del"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def padron_pe(conn: sqlite3.Connection) -> list[str]:
    """Diputados y senadores 2026-2031 = autores de PLs del periodo."""
    nombres = set()
    for (raw,) in conn.execute("SELECT autores_raw FROM proyectos WHERE per_par_id>=2026 AND autores_raw!=''"):
        nombres.update(n.strip() for n in raw.split(";") if n.strip())
    return sorted(nombres)


def padron_ec(conn: sqlite3.Connection) -> list[str]:
    """Asambleistas = proponentes de PLs en proyectos_ec.db."""
    return sorted(r[0].title() for r in conn.execute(
        "SELECT DISTINCT nombre FROM proponentes WHERE tipo LIKE 'ASAMBLE%'"))


def _emparejar(dicho: str, padron: list[str]) -> str | None:
    """Nombre del padron que mejor calza con lo que transcribio Whisper.
    Pide al menos un apellido parecido, y ademas otra palabra (nombre u
    otro apellido) o un apellido largo casi identico y unico en el padron.
    Caso real: "senador Arista" calzaba con "Auristela" (un nombre de pila)."""
    palabras = [w for w in _norm(dicho).replace(",", " ").split() if len(w) > 2]
    if not palabras or not padron:
        return None

    def parecido(w, tokens, umbral):
        return any(difflib.SequenceMatcher(None, w, t).ratio() >= umbral for t in tokens)

    mejores = []
    for persona in padron:
        p = _norm(persona)
        # PE: "Apellidos, Nombres"; EC: "APELLIDO APELLIDO NOMBRES"
        apellidos = p.split(",")[0].split() if "," in p else p.split()[:2]
        tokens = [t for t in p.replace(",", " ").split() if len(t) > 2]
        if not any(parecido(w, apellidos, 0.8) for w in palabras):
            continue
        hits = sum(1 for w in palabras if parecido(w, tokens, 0.8))
        fuerte = any(parecido(w, apellidos, 0.88) and len(w) >= 5 for w in palabras)
        mejores.append((hits, fuerte, persona))
    if not mejores:
        return None
    mejores.sort(reverse=True)
    top = mejores[0][:2]
    empatados = [m[2] for m in mejores if m[:2] == top]
    if len(empatados) > 1:
        return None
    if top[0] >= 2 or top[1]:
        return empatados[0]
    return None


def _limpiar_nombre(nombre: str) -> str:
    nombre = _PARTIDOS.sub("", nombre.strip(" ,.¿?"))
    nombre = re.sub(r"(?i)\s+(?:de|del|dos|tres|cuatro|cinco|seis|diez)$", "", nombre.strip())
    return nombre.strip(" ,.¿?")


def _juntar(texto_o_segmentos) -> tuple[str, list[tuple[int, float]]]:
    """Texto plano + [(offset, inicio_seg)] si vinieron segmentos de Whisper."""
    if isinstance(texto_o_segmentos, str):
        return texto_o_segmentos, []
    partes, marcas, pos = [], [], 0
    for s in texto_o_segmentos:
        t = s["text"].strip()
        marcas.append((pos, float(s.get("start", 0))))
        partes.append(t)
        pos += len(t) + 1
    return " ".join(partes), marcas


def atribuir_oradores(texto_o_segmentos, padron: list[str] | None = None) -> list[dict]:
    """Corta la transcripcion en turnos [{orador, rol, texto, inicio?}].

    texto_o_segmentos: el `texto` de sesiones_transcripciones, o la lista
    {start, end, text} de transcribir_audio() (entonces cada turno trae
    `inicio` en segundos). padron: nombres oficiales para normalizar; si
    falta o no calza, `orador` queda como lo dijo Whisper + " (?)".
    Lo anterior al primer anuncio y los cierres de la Presidencia
    ("Gracias, senor diputado. Tiempo.") van como orador "Presidencia"."""
    texto, marcas = _juntar(texto_o_segmentos)
    cues = []
    for rx in (_CUE, _CUE_INV, _CUE_LLAMADO):
        for m in rx.finditer(texto):
            # "Senores senadores, tiene la palabra el senador X": manda el
            # anuncio directo; los otros solo si no pisan a uno directo.
            if rx is not _CUE and any(a < m.end() and m.start() < b for a, b, _, _ in cues):
                continue
            rol = (m.group("rol") or "").lower()
            nombre = _limpiar_nombre(m.group("nombre") or "")
            if _norm(nombre) in _SIN_NOMBRE:
                nombre = ""
            if not rol and not nombre:
                continue
            if rol == "colega" and not nombre:
                continue
            if rol in ("presidente", "presidenta") and "comisi" not in _norm(nombre):
                # "adelante, presidente" lo dice el orador; "presidente de la
                # Republica" es una mencion. Solo vale "el presidente de la Comision X".
                continue
            if not rol and (len(nombre.split()) < 2 or not nombre[0].isupper()):
                continue  # "adelante, por favor": ruido
            cues.append((m.start(), m.end(), rol, nombre))
    cues.sort()
    # Anuncio doble ("le damos la palabra al senador X. Adelante, senador."):
    # el segundo, sin nombre y con el mismo rol, a menos de 200 caracteres
    # no abre otro turno.
    filtrados = []
    for c in cues:
        if filtrados and c[0] < filtrados[-1][1]:
            continue
        if (filtrados and not c[3] and c[2] == filtrados[-1][2]
                and c[0] - filtrados[-1][1] < 200):
            continue
        filtrados.append(c)

    turnos = []

    def agregar(orador, rol, ini, fin):
        t = texto[ini:fin].strip(" .,")
        if not t:
            return
        turno = {"orador": orador, "rol": rol, "texto": t}
        if marcas:
            turno["inicio"] = max((s for o, s in marcas if o <= ini), default=0.0)
        turnos.append(turno)

    if filtrados:
        agregar("Presidencia", "", 0, filtrados[0][0])
    for i, (ini, fin, rol, nombre) in enumerate(filtrados):
        fin_turno = filtrados[i + 1][0] if i + 1 < len(filtrados) else len(texto)
        # El cierre de la Presidencia solo se busca en la cola del turno.
        cola_desde = max(fin, fin_turno - 300)
        corte = fin_turno
        for m in _CIERRE.finditer(texto, cola_desde, fin_turno):
            corte = min(corte, m.start())
        oficial = _emparejar(nombre, padron or []) if nombre else None
        if (not oficial and rol and nombre and nombre[0].islower()
                and nombre.split()[0] not in ("de", "del")):  # "ministro del Interior" si sirve
            nombre = ""  # "adelante asambleista bueno, ...": no es un nombre
        orador = oficial or (f"{rol} {nombre}".strip() + (" (?)" if nombre else ""))
        # Salta la cola del anuncio ("por dos minutos.") hasta el primer punto.
        punto = re.search(r"[.?!]", texto[fin:min(fin + 60, corte)])
        agregar(orador, rol, fin + punto.end() if punto else fin, corte)
        agregar("Presidencia", "", corte, fin_turno)
    if not filtrados:
        agregar("Presidencia", "", 0, len(texto))  # sin anuncios: no se puede atribuir
    return turnos


def cobertura(turnos: list[dict]) -> dict:
    """% del texto con orador identificado / solo rol / Presidencia."""
    tot = sum(len(t["texto"]) for t in turnos) or 1
    def pct(f):
        return round(100 * sum(len(t["texto"]) for t in turnos if f(t)) / tot, 1)
    return {
        "padron": pct(lambda t: t["orador"] != "Presidencia" and not t["orador"].endswith("(?)")
                      and t["orador"] != t["rol"]),
        "nombre_sin_verificar": pct(lambda t: t["orador"].endswith("(?)")),
        "solo_rol": pct(lambda t: t["orador"] == t["rol"] and t["rol"]),
        "presidencia_o_sin_atribuir": pct(lambda t: t["orador"] == "Presidencia"),
    }


def _demo() -> None:
    padron = ["Pérez Quispe, Ana María", "Bravo De Rueda, Aldo", "Ampuero Mesa, Katherine"]
    texto = ("Se abre la sesion. Tiene la palabra la diputada Ana Peres Quispe de Fuerza "
             "Popular por dos minutos. Gracias presidente, este proyecto afecta a los "
             "agricultores. Muchas gracias. Gracias, señora diputada. Tiempo cumplido. "
             "A continuación le damos la palabra al senador Aldo Bravo. Adelante, senador. "
             "Presidente, me opongo al dictamen. Gracias. Señor ministro, tiene usted la "
             "palabra. Respondo a los congresistas. Diputado García. Gracias presidente, "
             "una consulta. Tambien hay que acceder a la Republica de Chile.")
    turnos = atribuir_oradores(texto, padron)
    oradores = [t["orador"] for t in turnos]
    assert oradores == ["Presidencia", "Pérez Quispe, Ana María", "Presidencia",
                        "Bravo De Rueda, Aldo", "ministro", "diputado García (?)"], turnos
    assert "agricultores" in turnos[1]["texto"] and "Tiempo" not in turnos[1]["texto"], turnos[1]
    assert "me opongo" in turnos[3]["texto"], turnos[3]
    # Con segmentos: cada turno trae el segundo en que empieza.
    segs = [{"start": 0, "end": 5, "text": "Tiene la palabra el congresista Juan Zeta."},
            {"start": 5, "end": 9, "text": "Gracias presidente, pido la reconsideracion."}]
    t2 = atribuir_oradores(segs)
    assert t2[-1]["orador"] == "congresista Juan Zeta (?)" and t2[-1]["inicio"] == 0.0, t2
    assert atribuir_oradores("Texto sin anuncios.")[0]["orador"] == "Presidencia"
    print("OK oradores: corta turnos por anuncio de la Presidencia y normaliza contra el padron")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "test":
        _demo()
    elif len(sys.argv) >= 3:
        sys.stdout.reconfigure(encoding="utf-8")
        conn = sqlite3.connect(sys.argv[1])
        fila = conn.execute("SELECT tipo, texto FROM sesiones_transcripciones WHERE video_id=?",
                            (sys.argv[2],)).fetchone()
        padron = (padron_ec(sqlite3.connect(sys.argv[3])) if len(sys.argv) > 3 else padron_pe(conn))
        turnos = atribuir_oradores(fila[1], padron)
        for t in turnos:
            print(f"[{t['orador']}] {t['texto'][:160]}")
        print(fila[0], len(turnos), "turnos", cobertura(turnos))
    else:
        print("Uso: python -m congreso_live.oradores test | RUTA.db VIDEO_ID [ec.db]")
        sys.exit(1)
