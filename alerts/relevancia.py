"""Relevancia natural-language de candidatos (noticias + PLs) por cliente.

Paso 2 del gap vs Dapper/Parlamento.ai identificado esta sesion: ellos rankean
por relevancia semantica en vez de solo categoria/keyword rigida. El paso 1
(cruce fuente x cliente en noticias_fuentes.clientes, ver noticias/fuentes.py)
ya esta commiteado - este modulo lo reusa como filtro grueso para noticias
(sigue siendo valido: es curaduria explicita de fuentes, no keyword matching).

Nicolas 2026-09-17: usar keywords del bluebook (el corte por TF-IDF de mas
abajo, `rankear()`) no alcanza - hace falta "conocimiento de usuario mucho
mayor" para juzgar bien que le importa a cada cliente. Fix: Gemini (tier
gratuito de Google AI Studio, GEMINI_API_KEY - MISMA decision de costo que
`congreso_live/qa_chat.py`, 2026-09-15: nunca la API de Claude para esto) ve
el notas.md COMPLETO del cliente (temas, entidades, actores, no solo las 2
secciones en prosa que usaba el TF-IDF) mas TODOS los candidatos de la
ventana, y juzga relevancia real por item - `rankear()`/TF-IDF quedan solo
como filtro de PRIMERA pasada para no perder candidatos por completo si
Gemini no esta disponible (--sin-llm), no como el criterio final.

Este modulo SIGUE siendo una HERRAMIENTA DE REVISION PARA NICOLAS, no un
mecanismo de envio: junta candidatos, Gemini juzga relevancia Y redacta el
borrador de alerta (ver clientes/_plantillas/whatsapp_alerta.md), y lo
imprime en consola para que EL lo lea/edite/mande a mano. NO envia nada a
ningun cliente, NO toca alerts/build.py ni alerts/send.py (el email
generico diario a Nicolas sigue intacto). Un envio automatico a clientes
reales sigue siendo una decision aparte, no tomada.

Uso (imprime un borrador para que Nicolas lo revise, no manda nada):
    python -m alerts.relevancia --cliente bayer
    python -m alerts.relevancia --cliente google --pais PE --top 3
    python -m alerts.relevancia --cliente bayer --sin-llm   # solo TF-IDF, sin llamar a Gemini
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from alerts.build import (
    _find_db_file, _open_ro,
    _peru_new_pls, _peru_new_dictamenes,
    _ecuador_new_pls, _ecuador_new_dictamenes,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENTES_DIR = REPO_ROOT / "clientes"

# Mapeo tema (proyectos/proyectos_ec - taxonomia de scraper/categorias.py,
# 29 valores reales verificados contra las DBs de produccion 2026-09-12) ->
# clientes. Solo se mapean los temas que algun notas.md real reclama
# explicitamente - el resto (Otros, Educacion, Trabajo, Tributos, Pensiones,
# Construccion, Energia, Pesca, Mineria, Comercio, Saneamiento, Control de la
# actividad privada, Infraestructura, Mype, Inmobiliario, Informalidad,
# Consumo masivo, Seguros, Deporte, Horeca, Justicia) se deja SIN mapear a
# proposito: un PL de un tema no listado igual puede colarse como candidato
# si el score TF-IDF (ver mas abajo) lo encuentra relevante por texto real -
# esa es justo la ventaja "natural language" sobre una tabla fija.
TEMA_CLIENTES: dict[str, list[str]] = {
    "Salud": ["bayer"],
    "Farma": ["bayer"],
    "Agricultura": ["bayer", "syngenta"],
    "Ambiente": ["bayer", "syngenta"],
    "Tecnología": ["google", "incode"],
    "Telecomunicaciones": ["google", "incode"],
    "Transporte y telecomunicaciones": ["google", "incode"],
    "Banca": ["google", "incode"],  # KYC/AML/inclusion financiera, explicito en incode/notas.md
}

# ponytail: umbral fijo elegido a ojo (corpus tipico de 5-30 candidatos por
# corrida, similitud TF-IDF entre perfil-prosa y titulo+resumen corto rara
# vez pasa de 0.3 salvo match fuerte) - si en la practica deja pasar ruido o
# se come candidatos buenos, ajustar mirando corridas reales.
NL_THRESHOLD = 0.08
WINDOW_HORAS = 48


def _leer_seccion(md_text: str, *titulos_posibles: str) -> str:
    """Extrae el contenido de la primera seccion `## <titulo>` cuyo titulo
    contenga (case-insensitive) alguno de `titulos_posibles`, hasta el
    proximo `## ` o el final del archivo."""
    lines = md_text.splitlines()
    out: list[str] = []
    capturando = False
    for line in lines:
        if line.startswith("## "):
            if capturando:
                break
            header = line[3:].lower()
            if any(t.lower() in header for t in titulos_posibles):
                capturando = True
            continue
        if capturando:
            out.append(line)
    return "\n".join(out).strip()


def perfil_cliente(slug: str) -> str:
    """Texto libre que describe los intereses del cliente: junta 'Temas de
    interes' + 'Perfil para prompts' de su notas.md (las 2 secciones en
    prosa real, no listas de entidades/actores)."""
    path = CLIENTES_DIR / slug / "notas.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    partes = [
        _leer_seccion(text, "temas de interes", "temas de interés"),
        _leer_seccion(text, "perfil para prompts"),
    ]
    return "\n".join(p for p in partes if p)


def notas_completas(slug: str) -> str:
    """notas.md ENTERO (temas de interes, contacto, entidades a monitorear,
    actores clave, historial de notas) - a diferencia de `perfil_cliente()`
    (solo 2 secciones en prosa, pensado para el score TF-IDF), esto le da a
    Gemini el mismo contexto que tendria Nicolas leyendo el archivo entero."""
    path = CLIENTES_DIR / slug / "notas.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _leer_plantilla_alerta() -> str:
    path = CLIENTES_DIR / "_plantillas" / "whatsapp_alerta.md"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _gemini(prompt: str, system: str) -> str:
    """Llamada minima a Gemini - mismo patron/modelo que congreso_live.qa_chat
    (tier gratuito, GEMINI_API_KEY). Levanta RuntimeError si falta la key."""
    import os

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY en el entorno")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-3.6-flash", contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system),
    )
    return (resp.text or "").strip()


_RE_VEREDICTO = re.compile(
    r"^\s*\[?(\d+)\]?\s*[:.\-]\s*(S[IÍ]|NO)\b[\s:\-]*(.*)$", re.IGNORECASE)


def _parsear_veredictos(texto: str) -> dict[int, dict]:
    """Parsea la respuesta de Gemini a `juzgar_relevancia_llm`: una linea por
    item, formato "<indice>: SI/NO - <razon>". Lineas que no matchean el
    formato se ignoran (no se asume relevante ni irrelevante por defecto -
    ver juzgar_relevancia_llm, que trata lo no-parseado como "sin veredicto"
    y lo deja afuera antes que arriesgar un falso positivo)."""
    out: dict[int, dict] = {}
    for linea in texto.splitlines():
        m = _RE_VEREDICTO.match(linea)
        if not m:
            continue
        idx, veredicto, razon = m.groups()
        out[int(idx)] = {"relevante": veredicto.upper().startswith("S"),
                         "razon": razon.strip()}
    return out


SYSTEM_JUEZ = (
    "Sos un analista senior de asuntos publicos/regulatorios de una "
    "consultora (Vali Consultores) que decide, con criterio real de "
    "negocio, si una noticia o proyecto de ley le importa a un cliente "
    "puntual - NO por si el texto contiene una palabra clave literal del "
    "perfil del cliente, sino si el CONTENIDO REAL le importaria a alguien "
    "que sigue de cerca los intereses de ese cliente. Se estricto: preferis "
    "dejar afuera algo dudoso a inundar al cliente de ruido que no le sirve."
)


def juzgar_relevancia_llm(slug: str, candidatos: list[dict]) -> list[dict]:
    """Un solo llamado a Gemini con el notas.md COMPLETO del cliente + TODOS
    los candidatos de la ventana, pidiendo un veredicto SI/NO + razon por
    item. Devuelve solo los candidatos marcados relevantes, con `razon_llm`
    agregado. Items sin veredicto parseable (respuesta rara de Gemini) NO
    se incluyen - mas vale perder uno raro que inundar sin filtro real."""
    if not candidatos:
        return []
    notas = notas_completas(slug)
    if not notas.strip():
        return []

    items_txt = []
    for i, c in enumerate(candidatos, 1):
        tipo_label = "proyecto de ley/dictamen" if c["tipo"] == "pl" else "noticia"
        items_txt.append(
            f"[{i}] ({tipo_label}, {c['pais']}) Fuente: {c.get('fuente') or '-'} "
            f"| Fecha: {c.get('fecha') or '-'} | Tema/categoria: {c.get('tema') or '-'}\n"
            f"Titulo: {c.get('titulo')}\n"
            f"Resumen: {c.get('resumen') or '(sin resumen)'}"
        )

    prompt = f"""Perfil completo del cliente "{slug}" (notas de la consultora - temas de interes,
entidades y actores clave a monitorear, historial de notas):

=== PERFIL ===
{notas}

Evalua CADA uno de los siguientes {len(candidatos)} items y decidi si es relevante para este
cliente puntual. Respondé en este formato EXACTO, una linea por item, SIN texto adicional antes
ni despues:

<numero>: SI - <razon en una frase>
<numero>: NO - <razon en una frase>

=== ITEMS ===
{chr(10).join(items_txt)}
"""
    respuesta = _gemini(prompt, SYSTEM_JUEZ)
    veredictos = _parsear_veredictos(respuesta)

    out = []
    for i, c in enumerate(candidatos, 1):
        v = veredictos.get(i)
        if v and v["relevante"]:
            out.append({**c, "razon_llm": v["razon"]})
    return out


def redactar_alerta_llm(slug: str, item: dict, historial: list[dict]) -> str:
    """Llama a Gemini con el prompt de `prompt_para_llm()` (mismas reglas de
    clientes/_plantillas/whatsapp_alerta.md, inlineadas para que el modelo
    las tenga sin acceso a archivos) y devuelve el borrador de alerta ya
    redactado - Nicolas lo revisa/edita antes de mandar cualquier cosa."""
    prompt = prompt_para_llm(slug, item, historial)
    system = ("Redactas alertas de WhatsApp para una consultora de asuntos "
              "publicos, siguiendo EXACTAMENTE las reglas de formato/tono "
              "que se te dan. Devolves SOLO el texto final de la alerta, "
              "sin explicaciones ni comentarios adicionales.")
    return _gemini(prompt, system)


def historial_entradas(slug: str) -> list[dict]:
    """Parsea historial_alertas.md en entradas `## <fecha/titulo>` + cuerpo.
    Devuelve [] si no existe o no tiene entradas reales todavia (ej. Google,
    sin historial al 2026-09-12)."""
    path = CLIENTES_DIR / slug / "historial_alertas.md"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    entradas = []
    for bloque in re.split(r"\n(?=## )", text):
        if not bloque.startswith("## "):
            continue
        lineas = bloque.splitlines()
        entradas.append({"titulo": lineas[0][3:].strip(), "cuerpo": "\n".join(lineas[1:]).strip()})
    return entradas


def _clientes_de_fuente(campo_clientes: str | None, slug: str) -> bool:
    if not campo_clientes:
        return False
    tags = campo_clientes.split("|")
    return slug in tags or "todos" in tags


def _candidatos_noticias(slug: str, pais: str | None) -> list[dict]:
    """Noticias de fuentes tageadas para este cliente (o 'todos'), ultimas
    WINDOW_HORAS. Filtro por clientes ya resuelto en noticias_fuentes
    (paso 1, commiteado antes) - aca solo se lee."""
    out = []
    for p, dbname in (("PE", "proyectos.db"), ("EC", "proyectos_ec.db")):
        if pais and pais != p:
            continue
        db = _find_db_file(dbname, search_root=REPO_ROOT)
        if not db:
            continue
        conn = _open_ro(db)
        try:
            rows = conn.execute(
                """SELECT n.id, n.titulo, n.resumen, n.url, n.fecha_pub,
                          f.nombre AS fuente, f.clientes AS clientes
                   FROM noticias n JOIN noticias_fuentes f ON f.id = n.fuente_id
                   WHERE f.pais=? AND f.activa=1
                     AND date(COALESCE(n.fecha_pub, n.first_seen_at))
                         >= date('now', ?)
                   ORDER BY COALESCE(n.fecha_pub, n.first_seen_at) DESC
                   LIMIT 500""",
                (p, f"-{WINDOW_HORAS // 24 + 1} days"),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            conn.close()
        for r in rows:
            if not _clientes_de_fuente(r["clientes"], slug):
                continue
            out.append({
                "tipo": "noticia", "pais": p, "id": r["id"],
                "titulo": r["titulo"], "resumen": r["resumen"] or "",
                "url": r["url"], "fecha": (r["fecha_pub"] or "")[:10],
                "fuente": r["fuente"], "tema": None,
                "tema_match": True,  # ya vino filtrado por tag de cliente
            })
    return out


def _candidatos_pls(slug: str, pais: str | None) -> list[dict]:
    """Nuevos PLs + dictamenes (PE+EC), TODOS los de la ventana (sin filtrar
    por tema todavia) - el filtro real (tema_match o score NL) se aplica
    despues de vectorizar, en `rankear()`."""
    out = []
    since_iso = None  # build_alert ya sabe convertir None -> ahora-24h; para
    # esta ventana de 48h pasamos since_iso explicito.
    from datetime import datetime, timedelta, timezone
    since_iso = (datetime.now(timezone.utc) - timedelta(hours=WINDOW_HORAS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    if not pais or pais == "PE":
        db_pe = _find_db_file("proyectos.db", search_root=REPO_ROOT)
        if db_pe:
            conn = _open_ro(db_pe)
            try:
                for item in _peru_new_pls(conn, since_iso) + _peru_new_dictamenes(conn, since_iso):
                    out.append({**item, "tipo": "pl", "pais": "PE",
                                "resumen": "", "fuente": "Congreso PE"})
            finally:
                conn.close()
    if not pais or pais == "EC":
        db_ec = _find_db_file("proyectos_ec.db", search_root=REPO_ROOT)
        if db_ec:
            conn = _open_ro(db_ec)
            try:
                for item in _ecuador_new_pls(conn, since_iso) + _ecuador_new_dictamenes(conn, since_iso):
                    out.append({**item, "tipo": "pl", "pais": "EC",
                                "resumen": "", "fuente": "Asamblea Nacional EC"})
            finally:
                conn.close()

    for item in out:
        tema = item.get("tema")
        item["tema_match"] = slug in TEMA_CLIENTES.get(tema, [])
    return out


def _texto_item(item: dict) -> str:
    return f"{item.get('titulo') or ''} {item.get('resumen') or ''}".strip()


def rankear(slug: str, pais: str | None, top: int) -> list[dict]:
    """Candidatos = noticias ya tageadas para el cliente + TODOS los PLs
    nuevos de la ventana. Rankea todo por similitud TF-IDF contra el perfil
    en prosa del cliente. Un PL entra en el resultado final si tema_match
    (tabla fija) O score >= NL_THRESHOLD (natural language) - una noticia
    ya vino filtrada por el tag de fuente, siempre entra si hay perfil."""
    candidatos = _candidatos_noticias(slug, pais) + _candidatos_pls(slug, pais)
    perfil = perfil_cliente(slug)
    if not candidatos:
        return []
    if not perfil.strip():
        # sin perfil en prosa no hay como rankear por NL - devolvemos los
        # que ya matchean por tag/tema, sin score.
        for c in candidatos:
            c["score"] = None
        seleccion = [c for c in candidatos if c.get("tema_match")]
        return seleccion[:top]

    corpus = [perfil] + [_texto_item(c) for c in candidatos]
    vec = TfidfVectorizer(strip_accents="unicode", lowercase=True,
                           ngram_range=(1, 2), min_df=1)
    try:
        matriz = vec.fit_transform(corpus)
    except ValueError:
        # corpus vacio tras tokenizar (ej. todos los campos en blanco)
        for c in candidatos:
            c["score"] = 0.0
        seleccion = [c for c in candidatos if c.get("tema_match")]
        return seleccion[:top]
    scores = cosine_similarity(matriz[0:1], matriz[1:])[0]
    for c, s in zip(candidatos, scores):
        c["score"] = round(float(s), 4)

    seleccion = [c for c in candidatos if c["tema_match"] or c["score"] >= NL_THRESHOLD]
    # Nicolas pidio priorizar noticias sobre PLs (2026-09-12) - noticias
    # primero (por score), PLs despues, en vez de un solo sort por score que
    # dejaba que un PL con texto mas "denso" le gane a noticias reales.
    seleccion.sort(key=lambda c: (c["tipo"] == "pl", -c["score"]))
    return seleccion[:top]


def contexto_historial(slug: str, item: dict, top: int = 2) -> list[dict]:
    """Top matches de este item contra el historial de alertas del cliente
    (la 'regla de oro': tejer continuidad con algo ya reportado antes).
    Devuelve [] honesto si el historial esta vacio, no inventa conexiones."""
    entradas = historial_entradas(slug)
    if not entradas:
        return []
    corpus = [_texto_item(item)] + [e["titulo"] + " " + e["cuerpo"] for e in entradas]
    vec = TfidfVectorizer(strip_accents="unicode", lowercase=True, ngram_range=(1, 2), min_df=1)
    try:
        matriz = vec.fit_transform(corpus)
    except ValueError:
        return []
    scores = cosine_similarity(matriz[0:1], matriz[1:])[0]
    ranked = sorted(zip(entradas, scores), key=lambda t: t[1], reverse=True)
    return [{"titulo": e["titulo"], "score": round(float(s), 4)} for e, s in ranked[:top] if s > 0]


BANDERA = {"PE": "🇵🇪", "EC": "🇪🇨"}
CLIENTES_CON_BANDERA = {"google", "incode"}  # ver whatsapp_alerta.md, regla 2026-09-11


def prompt_para_llm(slug: str, item: dict, historial: list[dict]) -> str:
    """Arma el prompt final para redactar la alerta - incluye el texto REAL
    de whatsapp_alerta.md inlineado (un LLM llamado por API no tiene acceso
    al archivo; esto tambien sirve para que Nicolas lo lea/audite entero
    sin tener que abrir el archivo aparte)."""
    bandera = BANDERA.get(item["pais"], "") if slug in CLIENTES_CON_BANDERA else ""
    hist_txt = "(sin antecedentes relacionados en el historial de este cliente)"
    if historial:
        hist_txt = "\n".join(f"- {h['titulo']} (similitud texto: {h['score']})" for h in historial)

    tipo_label = "proyecto de ley / dictamen" if item["tipo"] == "pl" else "noticia"
    return f"""Redacta una alerta de WhatsApp para el cliente "{slug}" siguiendo EXACTAMENTE el formato
y las reglas de abajo (incluida la "regla de oro": si hay continuidad con un antecedente de abajo,
tejerla en el bullet de analisis, no como dato de relleno).

=== REGLAS (clientes/_plantillas/whatsapp_alerta.md) ===
{_leer_plantilla_alerta()}

Bandera de pais: {"usar " + bandera if bandera else "NO usar bandera (regla: solo Google/Incode)"}.

=== ITEM ({tipo_label}, {item['pais']}) ===
Titulo: {item.get('titulo')}
Fuente: {item.get('fuente')}
Fecha: {item.get('fecha')}
Tema/categoria: {item.get('tema') or '(noticia, sin tema de PL)'}
Resumen/contenido: {item.get('resumen') or '(sin resumen - usar solo el titulo)'}
URL: {item.get('url')}
Relevancia NL para este cliente (TF-IDF vs. su perfil, no es una probabilidad): {item.get('score')}
Matcheo por tema/categoria fija: {item.get('tema_match')}

=== ANTECEDENTES posibles en el historial de {slug} (top {len(historial)}, via similitud de texto) ===
{hist_txt}
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Borrador de digest por cliente PARA QUE NICOLAS LO REVISE "
                     "y mande a mano si le sirve - no manda nada solo.")
    p.add_argument("--cliente", required=True, choices=["google", "incode", "bayer", "syngenta"])
    p.add_argument("--pais", choices=["PE", "EC"], default=None)
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--sin-llm", action="store_true",
                   help="solo TF-IDF (rankear), no llama a Gemini - para cuando falta "
                        "GEMINI_API_KEY o para comparar contra el corte viejo")
    args = p.parse_args(argv)

    print(f"[relevancia] BORRADOR para revision de Nicolas - cliente={args.cliente} "
          f"(nada se envia; ventana {WINDOW_HORAS}h, pais={args.pais or 'PE+EC'})")

    if args.sin_llm:
        seleccion = rankear(args.cliente, args.pais, args.top)
        if not seleccion:
            print("[relevancia] sin candidatos en esta ventana.")
            return 0
        for i, item in enumerate(seleccion, 1):
            hist = contexto_historial(args.cliente, item)
            print(f"\n{'=' * 70}\n[{i}/{len(seleccion)}] score={item['score']} "
                  f"tema_match={item['tema_match']} tipo={item['tipo']} pais={item['pais']}")
            print(f"  {item.get('titulo')}")
            print(f"{'-' * 70}")
            print(prompt_para_llm(args.cliente, item, hist))
        print(f"\n{'=' * 70}\n[relevancia] Fin del borrador (--sin-llm, solo TF-IDF) - Nicolas: "
              f"revisa/edita antes de mandar cualquier cosa a un cliente real.")
        return 0

    candidatos = _candidatos_noticias(args.cliente, args.pais) + _candidatos_pls(args.cliente, args.pais)
    if not candidatos:
        print("[relevancia] sin candidatos en esta ventana.")
        return 0

    print(f"[relevancia] {len(candidatos)} candidato(s) en la ventana - Gemini juzgando relevancia...")
    try:
        relevantes = juzgar_relevancia_llm(args.cliente, candidatos)
    except RuntimeError as e:
        print(f"[relevancia] {e} - corre con --sin-llm para el modo TF-IDF sin Gemini.")
        return 1
    relevantes = relevantes[:args.top]

    if not relevantes:
        print("[relevancia] Gemini no encontro nada relevante en esta ventana.")
        return 0

    for i, item in enumerate(relevantes, 1):
        hist = contexto_historial(args.cliente, item)
        print(f"\n{'=' * 70}\n[{i}/{len(relevantes)}] tipo={item['tipo']} pais={item['pais']}")
        print(f"  {item.get('titulo')}")
        print(f"  Gemini: {item['razon_llm']}")
        print(f"{'-' * 70}")
        try:
            print(redactar_alerta_llm(args.cliente, item, hist))
        except RuntimeError as e:
            print(f"[relevancia] fallo la redaccion ({e}), mostrando el prompt crudo:")
            print(prompt_para_llm(args.cliente, item, hist))
    print(f"\n{'=' * 70}\n[relevancia] Fin del borrador - Nicolas: revisa/edita antes de mandar "
          f"cualquier cosa a un cliente real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
