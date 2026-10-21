import json

from congreso_live import resumen_vivo


def test_sin_interes_no_manda_nada():
    falso = lambda *a, **k: json.dumps({"hay_algo": False, "clientes": [], "puntos": []})
    assert resumen_vivo.resumir("Comision: Salud", "Sesion", "texto " * 300, generar=falso) is None


def test_con_interes_arma_el_mensaje_y_pasa_perfiles_del_pais():
    vistos = []

    def falso(prompt, **k):
        vistos.append(prompt)
        return json.dumps({"hay_algo": True, "clientes": ["bayer"],
                           "puntos": ["Se aprobo el dictamen del PL 1234 sobre medicamentos."]})

    msg = resumen_vivo.resumir("Comision: Derecho a la Salud (EC)", "Sesion 45", "x" * 900, generar=falso)
    assert msg.startswith("📝 *Comision: Derecho a la Salud (EC)* en vivo (Bayer)")
    assert "• Se aprobo el dictamen" in msg
    assert "=== bayer ===" in vistos[0] and "=== google ===" not in vistos[0]  # Google es solo PE


def test_lo_avisado_se_pasa_y_se_acumula():
    vistos = []

    def falso(prompt, **k):
        vistos.append(prompt)
        return json.dumps({"hay_algo": True, "clientes": ["bayer"], "puntos": ["Se voto el PL 99."]})

    avisado = ["Se debate el PL 99."]
    resumen_vivo.resumir("Comision: Salud", "Sesion", "x" * 900, avisado, generar=falso)
    assert "- Se debate el PL 99." in vistos[0]
    assert avisado == ["Se debate el PL 99.", "Se voto el PL 99."]


def test_alerta_final_solo_si_hubo_avisos():
    falso = lambda *a, **k: json.dumps({"hay_algo": True, "clientes": ["bayer"], "alerta": "*Titulo*"})
    assert resumen_vivo.alerta_final("Comision: Salud", "S", "x" * 900, [], generar=falso) is None
    msg = resumen_vivo.alerta_final("Comision: Salud", "S", "x" * 900, ["algo"], generar=falso)
    assert msg.startswith("✅ Fin de sesión · Comision: Salud (para Bayer)") and "*Titulo*" in msg
