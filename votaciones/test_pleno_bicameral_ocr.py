"""Tests de votaciones/pleno_bicameral_ocr.py con cajas reales del OCR (sin OCR ni red)."""
import sqlite3

from votaciones.pleno_bicameral import init_schema
from votaciones.pleno_bicameral_ocr import palabras_ocr, parse_nominal, pendientes
from votaciones.test_pleno_bicameral import _words


def test_palabras_ocr_separa_voto_pegado_y_pasa_a_puntos():
    # Senado 30/09/2026 (dpi 200: 1653 px = 595 pt). Caja con el voto pegado;
    # se separa porque termina donde los votos sueltos de la 3ra columna.
    items = [("MUÑANTE BARRIOS, ALEJANDROPRE", [1167, 357, 1534, 372]),
             ("NORIEGA REÁTEGUI，VÍCTOR", [1167, 387, 1442, 402]),
             ("FLORES RUIZ, VÍCTOR SEFERINO", [689, 417, 1000, 432]),  # termina en NO pero no es voto
             ("5I", [494, 357, 530, 372])] + [("PRE", [1489, y, 1534, y + 15]) for y in (387, 417, 447)]
    w = palabras_ocr(items, 1653, 595.0)
    assert [t for _, _, t in w][:9] == ["MUÑANTE", "BARRIOS,", "ALEJANDRO", "PRE", "NORIEGA", "REÁTEGUI,VÍCTOR",
                                        "FLORES", "RUIZ,", "VÍCTOR"]
    assert w[9][2] == "SEFERINO" and w[10][2] == "SI"
    x_pre = w[3][0]
    assert 530 < x_pre < 552 and abs(w[0][1] - 131.2) < 1  # voto medido desde el borde derecho, y = centro


# Diputados 05/08/2026, formato "VOTACION NOMINAL" (marcas √ por columna), en pt.
NOMINAL = """
43.2 235:SESIÓN | 260:DEL | 280:PLENO | 300:DE | 310:LA | 320:CÁMARA | 350:DE | 360:DIPUTADOS
52.9 279:VOTACIÓNNOMINAL
83.1 366:Sesión | 390:del: | 410:05 | 420:de | 430:agosto | 455:de | 470:2026
97.5 90:ASUNTO: | 130:APROBACIÓN | 180:DEL | 200:NÚMERO | 240:DE | 255:INTEGRANTES
123.3 259:SI | 277:NO | 294:ABST. | 341:GRUPO | 481:SI | 498:NO | 515:ABST.
135.3 256:111 | 278:15 | 299:0 | 477:111 | 499:15 | 520:0
146.0 98:1 | 122:PBG | 145:RETO | 165:OTERO | 318:66 | 345:JP | 366:LAVADO | 390:VALDIVIA | 481:√
155.5 98:2 | 123:JP | 144:MÁRQUEZ | 175:HUANCA | 260:√ | 318:67 | 345:FP | 366:LEIVA | 390:BAYLÓN | 481:√
214.4 98:8 | 122:PCO | 145:ALBAÑIL | 175:CARMONA | 261:√ | 319:73 | 345:RP | 367:MARTÍNEZ | 395:PAITAN | 501:√
244.4 96:11 | 124:JP | 146:AMBROSIO | 180:DOMÍNGUEZ | 261:√ | 319:76 | 345:FP | 367:MENDOZA | 400:BERNEDO | 481:LE
263.1 96:13 | 124:RP | 146:ARANDA | 175:VÁSQUEZ | 280:√ | 319:78 | 345:FP | 367:MEZA | 395:RIVERA | 482:√
"""


def test_parse_nominal():
    b = parse_nominal(_words(NOMINAL))
    assert (b["fecha"], b["hora"], b["tipo"]) == ("2026-08-05", "", "votacion")
    assert b["asunto"].startswith("APROBACION DEL NUMERO")
    assert b["totales"] == {"si": 111, "no": 15, "abst": 0}
    v = {n: (ban, x) for n, ban, x in b["votos"]}
    assert len(v) == 10
    assert v["RETO OTERO"] == ("PBG", "SINRESP")  # preside, sin marca
    assert v["MARTÍNEZ PAITAN"] == ("RP", "NO")
    assert v["ARANDA VÁSQUEZ"] == ("RP", "NO")
    assert v["MENDOZA BERNEDO"] == ("FP", "LE")
    assert v["LEIVA BAYLÓN"] == ("FP", "SI")
    assert not b["cuadra"]  # fragmento: 7 SI de 111


def test_pendientes():
    c = sqlite3.connect(":memory:")
    init_schema(c)
    c.executemany("INSERT INTO pleno_votacion_pdf VALUES (?,?,?,?,?,?)", [
        ("a.pdf", "senado", "2026-09-30", 5, 0, ""), ("b.pdf", "senado", "2026-10-07", 0, 5, ""),
        ("c.pdf", "diputados", "2026-08-05", 6, 0, "")])
    c.execute("INSERT INTO pleno_votacion_ocr VALUES ('c.pdf', 6, 6, 5, '')")
    assert pendientes(c) == [("senado", "a.pdf")]
