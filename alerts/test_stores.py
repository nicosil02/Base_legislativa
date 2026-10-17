"""borradores_store y seguimiento_store en modo local (sin GitHub)."""
import pytest

from core import store
from alerts.borradores_store import guardar_borrador, list_borradores, marcar_pendiente
from alerts.seguimiento_store import list_seguidas, set_seguidas


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "_cache", {})


def _uno(cliente, item_id):
    return next(b for b in list_borradores(cliente) if b["item_id"] == item_id)


def test_guardar_borrador_crea_y_actualiza():
    kw = dict(cliente="bayer", item_id="n_1", item_tipo="noticia", pais="PE",
              item_titulo="Titulo", item_url="http://x")
    assert guardar_borrador(texto="Version 1", **kw)
    assert [b["texto"] for b in list_borradores("bayer")] == ["Version 1"]
    assert guardar_borrador(texto="Version 2", **kw)
    items = list_borradores("bayer")
    assert len(items) == 1 and items[0]["texto"] == "Version 2" and items[0]["estado"] == "borrador"


def test_marcar_pendiente_uno_por_cliente_y_no_pisa_borrador():
    guardar_borrador(cliente="bayer", item_id="n_1", item_tipo="noticia", pais="PE",
                     item_titulo="T", item_url="http://x", texto="Redactado")
    assert marcar_pendiente(clientes=["bayer", "syngenta"], item_id="n_2", item_tipo="noticia",
                            pais="PE", item_titulo="Otra", item_url="http://y",
                            item_resumen="resumen")
    p = _uno("syngenta", "n_2")
    assert p["estado"] == "pendiente" and p["texto"] == ""
    assert len(list_borradores("bayer")) == 2

    marcar_pendiente(clientes=["bayer"], item_id="n_1", item_tipo="noticia", pais="PE",
                     item_titulo="T", item_url="http://x")
    n1 = _uno("bayer", "n_1")
    assert n1["estado"] == "borrador" and n1["texto"] == "Redactado"


def test_fuentes_adicionales_y_creado_por_no_se_pisa():
    extra = [{"item_titulo": "Otro angulo", "item_url": "http://w"}]
    marcar_pendiente(clientes=["syngenta"], item_id="n_4", item_tipo="noticia", pais="PE",
                     item_titulo="T", item_url="http://q", fuentes_adicionales=extra,
                     creado_por="ana@vali.com")
    assert _uno("syngenta", "n_4")["fuentes_adicionales"] == extra
    guardar_borrador(cliente="syngenta", item_id="n_4", item_tipo="noticia", pais="PE",
                     item_titulo="T", item_url="http://q", texto="Texto del agente")
    assert _uno("syngenta", "n_4")["creado_por"] == "ana@vali.com"


def test_seguimiento_guarda_y_lee():
    assert list_seguidas() == set()
    set_seguidas({"Comision: Salud", "Comision: Economia"})
    store._cache.clear()
    assert list_seguidas() == {"Comision: Salud", "Comision: Economia"}
