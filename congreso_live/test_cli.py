"""Tests del filtro de avisos por comision seguida."""
from congreso_live.cli import _comision_seguida as F
from congreso_live.detector import _norm


def _seguidas(*nombres: str) -> set[str]:
    """El caller real (cmd_check) normaliza list_seguidas() antes de
    pasarlo - _comision_seguida espera el set YA normalizado."""
    return {_norm(n) for n in nombres}


def test_pleno_siempre_pasa():
    # Los Plenos avisan siempre, sin importar que este marcado.
    assert F("Pleno: Diputados", set()) is True
    assert F("Pleno: Senado", _seguidas("Salud")) is True


def test_sin_nada_marcado_pasa_todo():
    # Sin nada configurado en Seguimiento se avisa de todo.
    assert F("Comision: Salud", set()) is True


def test_comision_marcada_exacta():
    assert F("Comision: Energia Y Minas", _seguidas("Energía y Minas")) is True


def test_comision_marcada_nombre_largo_senado() -> None:
    # Nombres de comision del Senado son mas largos (combinan varios
    # temas) - el match es por substring, igual que clasificar_titulo()
    # ya usa para reconocer la comision en el titulo real del stream.
    nombre_senado = "Asuntos de Desarrollo Productivo, Energía y Minas, Infraestructura y Trabajo"
    assert F("Comision: Energia Y Minas", _seguidas(nombre_senado)) is True


def test_comision_no_marcada_no_pasa():
    assert F("Comision: Transportes", _seguidas("Salud", "Economía")) is False
