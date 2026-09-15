"""Checks del clasificador de temas. Correr: python -m noticias.test_temas"""
from noticias.temas import clasificar as C


def test_ana_no_colisiona_con_nombre_propio():
    # Bug real 2026-09-15: "ANA" (Autoridad Nacional del Agua) sola
    # matcheaba el nombre "Ana" en cualquier texto - una sesion de la
    # Comision de Salud que citaba a "Ana Luisa Yufra Lugo" quedaba mal
    # clasificada como "Crop".
    assert "Crop" not in C(
        "Sesión de la Comisión de Salud",
        "propuesto por la diputada Ana Luisa Yufra Lugo",
    )
    # La sigla completa (institucion real) sigue detectando Crop.
    assert "Crop" in C("Nota", "La Autoridad Nacional del Agua (ANA) otorgó licencias de riego")


def test_fiscal_solo_no_colisiona_con_carpeta_fiscal():
    # Bug real 2026-09-15: "fiscal" sola matcheaba tanto el sentido
    # tributario (KYC/AML) como el judicial ("carpeta fiscal" = denuncias
    # ante el Ministerio Publico, nada financiero).
    assert "KYC / AML / Financiero" not in C(
        "Sesión de la Comisión de Salud",
        "se denunció una carpeta fiscal con 140 folios de denuncias",
    )
    # El sentido tributario real sigue detectando la categoria.
    assert "KYC / AML / Financiero" in C("Nota", "el gobierno anunció una reforma del régimen tributario")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
