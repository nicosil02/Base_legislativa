import pytest

from clientes import matrices as m


def test_coincide_con_noticia_por_sigla():
    pl = "Proyecto de ley reformatoria a la Ley Constitutiva del INIAP"
    assert m.coincide_con_noticia(pl, "ECUADOR: Comisión aprueba informe para reformar la Ley del INIAP")
    assert not m.coincide_con_noticia(pl, "Presidenta Fujimori entrega ayuda humanitaria a población de Purús")


@pytest.mark.skipif(not m.BAYER_CROP_XLSX.exists(), reason="sin el Excel de Bayer Crop")
def test_matriz_bayer_crop_con_titulos():
    pytest.importorskip("openpyxl")
    for pais in ("PE", "EC"):
        filas = m.matriz_bayer_crop(pais)
        assert filas, pais
        assert all(f["pl_numero"] and f["titulo_matriz"] for f in filas), pais


@pytest.mark.skipif(not m.INCODE_XLSX.exists(), reason="sin el Excel de Incode")
def test_pls_trackeados_ec_suma_ambas_matrices():
    pytest.importorskip("openpyxl")
    trackeados = m.pls_trackeados_ec()
    assert len(trackeados) == len(m.matriz_bayer_crop("EC")) + len(m.matriz_incode_ec())
    assert all("clientes" in f for f in trackeados)


def test_config_clientes():
    from clientes import config
    assert config.slugs("PE") == ["bayer", "google", "incode", "syngenta"]
    assert "google" not in config.slugs("EC")
    assert config.por_campo("categorias_pl")["Agricultura"] == ["bayer", "syngenta"]
    for c in config.todos().values():
        assert c["nombre"] and set(c["paises"]) <= {"PE", "EC"}
