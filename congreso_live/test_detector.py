"""Checks del clasificador de titulos. Correr: python -m congreso_live.test_detector"""
from congreso_live.detector import clasificar_titulo as C


def test_pleno():
    assert C("🔴 EN VIVO: Pleno del Congreso | 19 DE JUNIO") == "Pleno"


def test_ordinarias():
    assert C("EN VIVO: Comisión de Economía, Banca y Finanzas") == "Comision: Economia"
    assert C("Comisión Agraria - sesión ordinaria") == "Comision: Agraria"
    assert C("🔴 Comisión de Salud y Población") == "Comision: Salud"
    assert C("Comisión de Energía y Minas") == "Comision: Energia Y Minas"


def test_excluye_especiales_y_noticias():
    assert C("🔴 EN VIVO: Comisión Especial proyecto Puyango – Tumbes") is None
    assert C("Comisión Especial Multipartidaria Pro-Inversión") is None
    assert C("Comisión Investigadora sobre ...") is None
    assert C("🔴 EN VIVO: Congreso Noticias – Edición Central") is None
    assert C("CONGRESO TV DIGITAL EN VIVO") is None
    assert C("Distinción Nacional al Emprendimiento") is None


def test_vacio_y_no_relacionado():
    assert C("") is None
    assert C(None) is None
    assert C("Concierto en el auditorio") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
