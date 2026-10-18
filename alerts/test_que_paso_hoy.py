from alerts import que_paso_hoy as q


def test_partir_respeta_parrafos():
    texto = "\n\n".join(["a" * 2000, "b" * 2000, "c" * 100])
    partes = q.partir(texto, largo=3500)
    assert len(partes) == 2 and partes[0] == "a" * 2000 and partes[1].startswith("b")


def test_escribir_cae_a_lite_si_flash_falla():
    usados = []

    def falso(prompt, system, modelo):
        usados.append(modelo)
        if modelo == q.llm.FLASH:
            raise RuntimeError("429")
        return "ok"

    m = {"noticias": ["[PE] algo"], "normas": [], "pls": [], "sesiones": [], "tv": []}
    assert q.escribir(m, generar=falso) == "ok" and usados == [q.llm.FLASH, q.llm.LITE]
    assert "NOTICIAS" in q.prompt(m) and "NORMAS" not in q.prompt(m)


def test_fresca_descarta_notas_viejas():
    assert not q._fresca({"fecha_pub": "2016-07-18T10:00:00Z"})
    from datetime import datetime, timezone
    assert q._fresca({"fecha_pub": datetime.now(timezone.utc).isoformat()})
