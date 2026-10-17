import json

from alerts import filtro


def test_juzgar_parsea_y_descarta_indices_raros():
    items = [{"titulo": "A", "resumen": "", "fecha": "2026-10-17", "fuente": "X", "pais": "PE"},
             {"titulo": "B", "resumen": "r", "fecha": "2026-10-17", "fuente": "Y", "pais": "EC"}]
    vistos = {}

    def falso(prompt, system, modelo, schema):
        vistos["prompt"] = prompt
        return json.dumps([{"indice": 1, "interesa": True, "por_que": "toca DIGEMID"},
                           {"indice": 2, "interesa": False, "por_que": "coyuntura"},
                           {"indice": 9, "interesa": True, "por_que": "no existe"}])

    v = filtro.juzgar("bayer", items, generar=falso)
    assert v == {1: (True, "toca DIGEMID"), 2: (False, "coyuntura")}
    assert "[2] (EC, Y, 2026-10-17)" in vistos["prompt"] and 'cliente "bayer"' in vistos["prompt"]
