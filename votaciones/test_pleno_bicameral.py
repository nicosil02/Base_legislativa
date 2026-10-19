"""Tests de votaciones/pleno_bicameral.py con lineas reales recortadas (sin red).

Cada linea es "y x:palabra | x:palabra ...", como sale de page.get_text("words")
del PDF del Senado del 7/10/2026 (escaneo con capa OCR: "01 :06", "o" por 0,
"NO ---" partido, fila del presidente sin voto)."""
import sqlite3

from consultas.votaciones import disciplina, votos_de_pl
from votaciones.pleno_bicameral import _RE_LINK, guardar, init_schema, parse_pagina, pley_de_asunto

PAGINA_SENADO = """
41.3 206:SENADO | 250:DE | 267:LA | 282:REPÚBLICA | 341:DEL | 363:PERÚ
93.3 25:VOTACIÓN: | 75:Fecha: | 101:07/10/2026 | 142:Hora: | 163:01 | 172::06 | 185:PM
105.2 25:Asunto:
116.3 26:PROYECTO | 77:DE | 95:RESOLUCIÓN | 154:LEGISLATIVA | 210:12, | 229:QUE | 253:AUTORIZA | 299:A | 311:LA | 328:SEÑORA
125.5 26:TERRITORIO | 79:NACIONAL | 123:DEL | 143:28
140.0 -5:COPIA
156.4 25:FP | 76:AGUINAGA | 114:RECUENCO, | 180:SI | 206:PBG | 257:FIGALLO | 287:RIVADENEYRA, | 361:SI | 387:RP | 437:MUÑANTE | 473:BARRIOS, | 541:SI
188.5 25:JP | 76:ANDRÉS | 106:LUJAN, | 132:SERAFÍN | 180:NO | 186:--- | 206:PBG | 257:FLORES | 286:SUAREZ, | 317:JUVER | 361:SI | 387:JP | 437:QUITO | 461:SARMIENTO, | 541:NO---
231.4 25:FP | 76:ASTUDILLO | 116:SALCEDO, | 152:CÉSAR | 180:LO | 207:RP | 257:JÁUREGUI | 293:MARTÍNEZ | 330:DE | 361:SI | 387:FP | 437:ROSPIGLIOSI | 483:CAPURRO, | 542:SI
252.5 25:PBG | 76:BONIFAZ | 107:CARMONA, | 146:NORA | 180:Abst. | 207:FP | 257:JUÁREZ | 285:GALLEGOS, | 326:CARMEN | 361:SI | 387:FP | 437:TAPIA | 459:BERNAL, | 490:SEGUNDO | 542:SI
274.0 26:RP | 76:CALISTO | 107:GIAMPIETRI, | 180:SI | 207:AN | 257:LUQUE | 282:IBARRA, | 311:RUTH | 361:NO--- | 387:FP | 437:TORRES | 468:MORALES, | 505:MIGUEL
391.0 26:Resultado | 61:de | 207:Grupo | 229:Parlamentario | 443:Si+++ | 473:No-- | 502:Abst. | 530:Sin | 543:Resp.
401.3 26:A | 32:FAVOR | 58:(SI) | 153:9 | 207:AN | 255:AHORA | 281:NACIÓN | 450:1 | 479:3
411.1 25:EN | 37:CONTRA | 68:(NO) | 153:3 | 207:FP | 255:FUERZA | 284:POPULAR | 450:17
417.8 26:ABSTENCIÓN | 508:o | 547:o
421.0 153:1 | 207:JP | 255:JUNTOS | 284:POR | 301:EL | 311:PERÚ | 478:8
427.4 26:SIN | 39:RESPUESTA | 478:o | 547:o
430.8 153:1 | 207:PBG | 255:PARTIDO | 287:DEL | 302:BUEN | 323:GOBIERNO | 449:5 | 508:1
437.1 26:AUSENTE | 478:o | 508:o | 547:o
440.3 207:PCO | 255:PARTIDO | 287:CÍVICO | 313:OBRAS | 449:5
446.8 25:LIC. | 40:OFICIAL | 153:1
450.0 207:RP | 255:RENOVACIÓN | 309:POPULAR | 449:8
"""


def _words(txt):
    out = []
    for linea in txt.strip().splitlines():
        y, resto = linea.split(" ", 1)
        for w in resto.split(" | "):
            x, t = w.split(":", 1)
            out.append((float(x), float(y), t))
    return out


def test_parse_pagina_senado_ocr():
    b = parse_pagina(_words(PAGINA_SENADO))
    assert (b["tipo"], b["fecha"], b["hora"]) == ("votacion", "2026-10-07", "13:06")
    assert b["asunto"].startswith("PROYECTO DE RESOLUCIÓN LEGISLATIVA 12, QUE AUTORIZA")
    assert "COPIA" not in b["asunto"]
    votos = {n: (ban, v) for n, ban, v in b["votos"]}
    assert len(votos) == 15
    assert votos["ANDRÉS LUJAN, SERAFÍN"] == ("JP", "NO")  # "NO" + "---" en dos palabras
    assert votos["QUITO SARMIENTO"] == ("JP", "NO")
    assert votos["BONIFAZ CARMONA, NORA"] == ("PBG", "ABST")
    assert votos["ASTUDILLO SALCEDO, CÉSAR"] == ("FP", "LO")
    assert votos["JÁUREGUI MARTÍNEZ DE"] == ("RP", "SI")  # "DE" no se toma por sigla
    assert votos["TORRES MORALES, MIGUEL"] == ("FP", "SINRESP")  # preside: sin voto
    # totales: "o" del OCR = 0; el numero puede caer unos pt mas abajo
    t = b["totales"]
    assert (t["si"], t["no"], t["abst"], t["sin_resp"], t["lo"]) == (9, 3, 1, 1, 1)
    assert "aus" not in t  # sin numero: no se sabe (no se toma como 0)
    assert b["cuadra"]  # 9 SI, 3 NO, 1 ABST, 1 SINRESP, 1 LO


def test_pley_de_asunto():
    assert pley_de_asunto("PROYECTO DE RESOLUCIÓN LEGISLATIVA 12, QUE AUTORIZA") == 12
    assert pley_de_asunto("TEXTO SUSTITUTORIO DE LA PROPOSICIÓN LEGISLATIVA 98, CONTENIDO") == 98
    assert pley_de_asunto("PROYECTO DE LEY N° 1234 QUE") == 1234
    assert pley_de_asunto("MOCIÓN DE ORDEN DEL DÍA 31") is None


def test_link_votaciones_y_asistencias():
    fila = ('<td data-search="x.pdf"><a class="fsm-pub-doc" href="https://senado.congreso.gob.pe/a/Acta.pdf" '
            'aria-label="Abrir Acta PDF"></a></td><td><a class="fsm-pub-doc" '
            'href="https://senado.congreso.gob.pe/a/Asistencias_y_votaciones_7_10_2026_vbo.pdf" target="_blank" '
            'aria-label="Abrir Votaciones y Asistencias PDF"></a></td>')
    assert _RE_LINK.findall(fila) == ["https://senado.congreso.gob.pe/a/Asistencias_y_votaciones_7_10_2026_vbo.pdf"]


def test_guardar_idempotente_y_gana_la_que_cuadra():
    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    b = parse_pagina(_words(PAGINA_SENADO))
    assert guardar(conn, "senado", "prov.pdf", [b]) == 1
    assert guardar(conn, "senado", "prov.pdf", [b]) == 1  # misma clave: se reescribe, no se duplica
    malo = dict(b, cuadra=False, votos=b["votos"][:3])
    assert guardar(conn, "senado", "final_ocr.pdf", [malo]) == 0  # no pisa una que cuadra
    assert conn.execute("SELECT COUNT(*), pdf_url, pley_num, pl_cod_tipo_parl FROM votacion_pleno").fetchone() \
        == (1, "prov.pdf", 12, "S")
    assert conn.execute("SELECT COUNT(*) FROM voto_pleno_nominal").fetchone()[0] == 15
    assert len(votos_de_pl(conn, 12, "S")) == 15
    d = {a["congresista"]: a for a in disciplina(conn)}
    # JP: 2 NO de 2 -> alineados; PBG: 2 SI + 1 ABST -> Bonifaz no alineada
    assert d["QUITO SARMIENTO"]["pct_alineado"] == 100.0
    assert d["BONIFAZ CARMONA, NORA"]["pct_alineado"] == 0.0
    assert "TORRES MORALES, MIGUEL" not in d  # SINRESP no es postura


def _pagina_ocr(nombre):
    import gzip
    import json
    from pathlib import Path
    with gzip.open(Path(__file__).with_name("ocr_paginas_reales.json.gz"), "rt", encoding="utf-8") as f:
        return [tuple(w) for w in json.load(f)[nombre]]


def test_votos_registrados_despues_cuadran_con_el_cuadro_por_bancada():
    # Diputados 13/08 17:21: "se anunciaron 115 votos a favor, habiendose
    # registrado 120". La lista y el cuadro por bancada traen 120.
    b = parse_pagina(_pagina_ocr("diputados_2026-08-13_1721"), tol=5)
    assert b["cuadra"]
    assert b["totales"]["si"] == 120 and b["totales"]["si_anunciado"] == 115


def test_ocr_que_no_leyo_un_voto_se_repara_con_el_cuadro_y_constancia_del_presidente():
    # Senado 09/09 18:02: el OCR no leyo el SI de Velasquez Garcia (RP); el
    # cuadro dice RP 8 SI y 0 sin respuesta. Torres Morales preside y deja
    # constancia de su voto a favor.
    b = parse_pagina(_pagina_ocr("senado_2026-09-09_1802"), tol=5)
    assert b["cuadra"]
    votos = {n: v for n, _b, v in b["votos"]}
    assert votos["VELÁSQUEZ GARCÍA, MIGUEL"] == "SI"
    assert votos["TORRES MORALES, MIGUEL"] == "SI"


def test_el_que_preside_no_es_candidato_a_reparar():
    # Senado 09/09 15:57: FP tiene 2 sin respuesta (el presidente y una mal leida)
    assert parse_pagina(_pagina_ocr("senado_2026-09-09_1557"), tol=5)["cuadra"]
