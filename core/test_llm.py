"""Reintentos y cadena de modelos de llm.generar con un cliente falso."""
from types import SimpleNamespace

import pytest

from core import llm


class Error(Exception):
    def __init__(self, code, msg=""):
        super().__init__(f"{code} {msg}")
        self.code = code


def _falso(monkeypatch, respuestas):
    """respuestas: {modelo: [Exception | str, ...]} consumidas en orden."""
    llamadas = []

    def generate_content(model, contents, config):
        llamadas.append((model, contents, config))
        r = respuestas[model].pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(text=r)

    monkeypatch.setattr(llm, "_cliente", SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    return llamadas


def test_503_reintenta_el_mismo_modelo(monkeypatch):
    ll = _falso(monkeypatch, {llm.FLASH: [Error(503, "UNAVAILABLE"), "ok"]})
    assert llm.generar("x") == "ok"
    assert [m for m, _, _ in ll] == [llm.FLASH, llm.FLASH]


def test_cupo_diario_pasa_al_siguiente_sin_esperar(monkeypatch):
    ll = _falso(monkeypatch, {llm.FLASH: [Error(429, "GenerateRequestsPerDayPerProjectPerModel")],
                              llm.LITE: ["lite"]})
    assert llm.generar("x") == "lite"
    assert [m for m, _, _ in ll] == [llm.FLASH, llm.LITE]


def test_lite_no_sube_a_flash_y_gemma_lleva_el_system_en_el_texto(monkeypatch):
    ll = _falso(monkeypatch, {llm.LITE: [Error(503)] * 3, llm.GEMMA: ['```json\n{"a": 1}\n```']})
    assert llm.generar("hola", system="SYS", modelo=llm.LITE, schema={"type": "object"}) == '{"a": 1}'
    assert [m for m, _, _ in ll] == [llm.LITE] * 3 + [llm.GEMMA]
    _, texto, config = ll[-1]
    assert texto.startswith("SYS") and "JSON" in texto and config.system_instruction is None


def test_error_que_no_es_de_cupo_se_levanta(monkeypatch):
    _falso(monkeypatch, {llm.FLASH: [Error(400, "INVALID_ARGUMENT")]})
    with pytest.raises(Error):
        llm.generar("x")


def test_todo_agotado_levanta_el_ultimo(monkeypatch):
    _falso(monkeypatch, {m: [Error(429, "PerDay")] for m in (llm.FLASH, llm.LITE, llm.GEMMA)})
    with pytest.raises(Error):
        llm.generar("x")
