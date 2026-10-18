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


def test_tipos_prohibidos_nunca_interesan():
    items = [{"titulo": "9 de cada 10 empresas", "resumen": "", "fecha": "2026-10-18", "fuente": "X", "pais": "PE"},
             {"titulo": "Embajador visita", "resumen": "", "fecha": "2026-10-18", "fuente": "X", "pais": "PE"}]

    def falso(prompt, system, modelo, schema):
        return json.dumps([{"indice": 1, "tipo": "encuesta_o_estudio", "interesa": True, "por_que": "IA"},
                           {"indice": 2, "tipo": "evento_o_protocolo", "interesa": True, "por_que": "EE.UU."}])

    assert filtro.juzgar("google", items, generar=falso) == {1: (False, "IA"), 2: (True, "EE.UU.")}
