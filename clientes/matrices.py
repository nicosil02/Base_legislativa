"""Matrices de PLs que Nicolas mantiene a mano en Excel (Bayer Crop/Syngenta,
Incode). Complementan CATEGORIA_CLIENTES_PL: un PL tributario que afecta al
agro no cae en "Agricultura". Se lee el Excel en cada carga para que Nicolas
lo siga editando como siempre.

La hoja "Peru Legislativo" de Incode está desactualizada y no se lee; en la de
Ecuador se cruza por número de PL, no por el estado de la matriz.
"""
from __future__ import annotations

import re
from pathlib import Path

from core.text import sin_tildes

CLIENTES_DIR = Path(__file__).resolve().parent

# Del texto libre de la columna "Proyecto" se saca el código, igual que
# proyecto_ley en la DB ("00011-2026-2031-CD").
_RE_PL_PE = re.compile(r"\d+-\d{4}-\d{4}-[A-Za-z]{1,3}")


def _normalizar_pl_pe(texto: str) -> str | None:
    m = _RE_PL_PE.search(str(texto))
    return m.group(0).upper() if m else None

BAYER_CROP_XLSX = CLIENTES_DIR / "MatrizPLAndinos_Bayer CROP.xlsx"
INCODE_XLSX = CLIENTES_DIR / "140125 - Matriz - Matriz Legislativa y Regulatoria INCODE.xlsx"


_RE_DIGITS = re.compile(r"\d{5,}")


def _split_numeros(valor, extraer_digitos: bool = False) -> list[str]:
    """Una celda puede traer varios números separados por salto, coma o
    barra. `extraer_digitos` (solo Ecuador): de un token como "AN-2024-2928"
    se queda con la corrida de 5+ dígitos; en Perú el código real es
    alfanumérico y esto lo rompería."""
    if valor is None:
        return []
    if isinstance(valor, (int, float)):
        return [str(int(valor))]
    texto = str(valor).replace(",", "\n").replace("/", "\n")
    tokens = [p.strip() for p in texto.split("\n") if p.strip()]
    if not extraer_digitos:
        return tokens
    out = []
    for t in tokens:
        m = _RE_DIGITS.search(t)
        out.append(m.group(0) if m else t)
    return out


def _leer_hoja(path: Path, hoja: str, header_row: int,
                cols: dict[str, str | list[str]]) -> list[dict]:
    """Filas de una hoja como dicts {alias: valor}; `cols` mapea cada alias a
    uno o varios headers aceptados (la hoja ECUADOR tiene el typo "Titúlo").
    Archivo u hoja que no existe -> lista vacía."""
    import openpyxl

    if not path.exists():
        return []
    wb = openpyxl.load_workbook(path, data_only=True)
    if hoja not in wb.sheetnames:
        return []
    ws = wb[hoja]
    # Headers con espacios de más: se comparan con strip + lower.
    headers_norm = [
        (str(c.value).strip().lower() if c.value is not None else None)
        for c in next(ws.iter_rows(min_row=header_row, max_row=header_row))
    ]
    idx = {}
    for alias, candidatos in cols.items():
        if isinstance(candidatos, str):
            candidatos = [candidatos]
        for real in candidatos:
            real_norm = real.strip().lower()
            if real_norm in headers_norm:
                idx[alias] = headers_norm.index(real_norm)
                break
    out = []
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if not any(c is not None for c in row):
            continue
        out.append({alias: row[i] for alias, i in idx.items()})
    return out


def matriz_bayer_crop(pais: str) -> list[dict]:
    """PLs puntuales de la matriz Bayer Crop/Syngenta para `pais` ("PE"/"EC").
    Cada dict: pl_numero, titulo_matriz, tema_matriz, estado_matriz."""
    hoja = "PERÚ" if pais == "PE" else "ECUADOR"
    filas = _leer_hoja(
        BAYER_CROP_XLSX, hoja, header_row=(3 if pais == "PE" else 2),
        cols={"titulo": ["Título", "Titúlo"], "proyecto": "Proyecto", "tema": "Tema", "estado": "Estado"},
    )
    out = []
    for f in filas:
        for num in _split_numeros(f.get("proyecto"), extraer_digitos=(pais == "EC")):
            if pais == "PE":
                num = _normalizar_pl_pe(num)
                if not num:
                    continue
            out.append({
                "pl_numero": num, "titulo_matriz": f.get("titulo"),
                "tema_matriz": f.get("tema"), "estado_matriz": f.get("estado"),
            })
    return out


def matriz_incode_ec() -> list[dict]:
    """PLs puntuales de la matriz Incode para Ecuador."""
    filas = _leer_hoja(
        INCODE_XLSX, "Ecuador Legislativo", header_row=2,
        cols={"titulo": ["Título", "Titúlo"], "proyecto": "Proyecto", "tema": "Tema", "estado": "Estado"},
    )
    out = []
    for f in filas:
        for num in _split_numeros(f.get("proyecto"), extraer_digitos=True):
            out.append({
                "pl_numero": num, "titulo_matriz": f.get("titulo"),
                "tema_matriz": f.get("tema"), "estado_matriz": f.get("estado"),
            })
    return out


# Matching noticia <-> PL trackeado por parte del nombre: el equipo nombra
# los PLs ("Ley del INIAP"), las noticias casi nunca citan el número.

# Boilerplate legislativo que no identifica a ningún PL.
_STOPWORDS_PL = {
    "proyecto", "proyectos", "ley", "leyes", "organica", "organico",
    "reformatoria", "reformatorio", "reforma", "codigo", "para", "que",
    "sobre", "con", "del", "las", "los", "una", "uno", "por", "sus", "en",
    "de", "la", "el", "y", "a", "al", "se", "su", "e", "u", "o", "no", "es",
    "un", "lo", "como", "mas", "integral", "nacional", "ecuador", "asamblea",
    "diversos", "varios", "articulos", "articulo", "cuerpos", "legales",
    "vigente", "vigentes", "cumplimiento", "fin", "efectos", "materia",
}


# Palabras de muchos títulos que no identifican nada ("desarrollo" sola
# emparejaba un PL agropecuario con 1444 noticias).
_PALABRAS_GENERICAS_PL = {
    "desarrollo", "unificado", "productivo", "productiva", "general",
    "publico", "publica", "sistema", "gestion", "fortalecimiento",
    "proteccion", "regimen", "responsabilidad", "seguridad", "servicio",
    "servicios", "derecho", "derechos", "modelo", "plan", "politica",
    "sancionar", "sanciones", "control", "registro", "personas",
}

# Siglas del título original (INIAP, COIP, OVM) identifican un PL por sí
# solas; se ignoran las que salen como dateline ("ECUADOR: ...").
_RE_ACRONIMO = re.compile(r"\b[A-Z]{3,}\b")
_ACRONIMOS_IGNORAR = {"ECUADOR", "PERU", "LEY", "ASAMBLEA", "COMISION", "PROYECTO"}


# Nombre usado en "matriz_pl" de clientes/<slug>/cliente.json -> filas del pais.
MATRICES = {
    "bayer_crop": matriz_bayer_crop,
    "incode_ec": lambda pais: matriz_incode_ec() if pais == "EC" else [],
}


def _normalizar_texto(s: str | None) -> str:
    return sin_tildes((s or "").lower())


def _acronimos(texto: str | None) -> set[str]:
    return {a for a in _RE_ACRONIMO.findall(texto or "") if a not in _ACRONIMOS_IGNORAR}


def palabras_clave_titulo(titulo: str | None, min_len: int = 5) -> set[str]:
    """Palabras que identifican a ESE PL (sin boilerplate, genéricas ni siglas)."""
    texto = _normalizar_texto(titulo)
    palabras = re.findall(r"[a-z]+", texto)
    return {
        p for p in palabras
        if len(p) >= min_len and p not in _STOPWORDS_PL and p not in _PALABRAS_GENERICAS_PL
    }


# Los PLs trackeados son de Ecuador: una noticia que nombra otro país y no a
# Ecuador comparte vocabulario por casualidad ("Congreso de Perú y Meta ...
# inteligencia artificial"). Solo aplica a la vía de palabras, no a siglas.
_OTRO_PAIS_MARCADORES = {
    "peru", "mexico", "colombia", "chile", "argentina", "espana",
    "bolivia", "venezuela", "brasil", "uruguay", "paraguay", "norteamerica",
    "euros",  # Ecuador usa USD - "euros" es senal fuerte de nota europea
}
_ECUADOR_MARCADORES = {
    "ecuador", "ecuatoriano", "ecuatoriana", "ecuatorianos", "ecuatorianas",
    "quito", "guayaquil",
}


def _parece_de_otro_pais(texto_normalizado: str) -> bool:
    palabras = set(re.findall(r"[a-z]+", texto_normalizado))
    if palabras & _ECUADOR_MARCADORES:
        return False
    return bool(palabras & _OTRO_PAIS_MARCADORES)


# El Registro Oficial mezcla actos administrativos (personería jurídica de
# una ONG "de Biocomercio") que comparten vocabulario con un PL sin ser una ley.
_ACTOS_NO_LEGISLATIVOS = {
    "personeria juridica", "personalidad juridica", "se aprueba el estatuto",
    "planificacion operativa", "ordenanza municipal",
    "gobiernos autonomos descentralizados",
}


def _parece_acto_administrativo(texto_normalizado: str) -> bool:
    return any(frase in texto_normalizado for frase in _ACTOS_NO_LEGISLATIVOS)


def coincide_con_noticia(pl_titulo: str | None, noticia_texto: str | None, minimo_palabras: int = 3,
                          noticia_titulo: str | None = None) -> bool:
    """True si la noticia (título+resumen) parece hablar del mismo PL: o
    comparten una sigla, o comparten `minimo_palabras` palabras distintivas
    (con 2 salían 248 matches sobre 2145 noticias EC, con 3 bajó a 18 sin
    perder los reales) y la noticia no es de otro país ni un acto
    administrativo. Es una señal para revisar, no una alerta automática."""
    if _parece_acto_administrativo(_normalizar_texto(noticia_texto)):
        return False
    acr_pl = _acronimos(pl_titulo)
    if acr_pl and (acr_pl & _acronimos(noticia_texto)):
        return True
    kw_pl = palabras_clave_titulo(pl_titulo)
    if len(kw_pl) < minimo_palabras:
        return False
    kw_noticia = palabras_clave_titulo(noticia_texto, min_len=4)
    if len(kw_pl & kw_noticia) < minimo_palabras:
        return False
    # "Otro país" se mira en el titular: un país nombrado de paso en el cuerpo
    # no descarta un match real. Sin titular, el texto completo.
    texto_pais = noticia_titulo if noticia_titulo is not None else noticia_texto
    return not _parece_de_otro_pais(_normalizar_texto(texto_pais))


def pls_trackeados_ec() -> list[dict]:
    """Todos los PLs EC que siguen los clientes (matriz_pl de su cliente.json),
    con sus `clientes`; un PL en varias matrices aparece una vez por matriz."""
    from clientes import config
    out = []
    for clave, slugs in config.por_matriz("EC").items():
        out += [{**f, "clientes": slugs} for f in MATRICES[clave]("EC")]
    return out
