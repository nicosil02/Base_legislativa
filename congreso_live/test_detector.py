"""Checks del clasificador de titulos. Correr: python -m congreso_live.test_detector"""
from congreso_live.detector import clasificar_titulo as C


def test_pleno():
    # Titulos reales verificados en vivo 2026-09-15 (canal del Congreso).
    assert C("🔴EN VIVO: Sesión del Pleno de la Cámara de Diputados | 10 DE "
              "SEPTIEMBRE DEL 2026") == "Pleno: Diputados"
    assert C("🔴EN VIVO: Sesión del Pleno del Senado de la República | 9 DE "
              "SEPTIEMBRE DEL 2026") == "Pleno: Senado"
    # Sesion conjunta (sin "senado" ni "diputados" en el titulo) - fallback.
    assert C("🔴 EN VIVO: Pleno del Congreso | 19 DE JUNIO") == "Pleno: Congreso"


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


def test_las_25_comisiones_ordinarias_reales():
    # Bug real 2026-09-16 (Nicolas: "por que no llego a capturar la de
    # Desarrollo Agrario?"): 8 de las 25 comisiones ordinarias reales
    # (verificadas contra la tabla `sesiones`, no una lista supuesta) no
    # clasificaban con NINGUN keyword - ni se detectaban como EN VIVO.
    assert C("EN VIVO: Comisión de Desarrollo Agrario") == "Comision: Agrario"
    assert C("EN VIVO: Comisión de Asuntos de Gestión del Estado y "
              "Contraloría") == "Comision: Gestion Del Estado"
    assert C("EN VIVO: Comisión de Control Político sobre los Actos "
              "Normativos del Poder Ejecutivo y Regímenes de Excepción"
              ) == "Comision: Regimenes De Excepcion"
    assert C("EN VIVO: Comisión de Medio Ambiente y Sostenibilidad"
              ) == "Comision: Medio Ambiente"
    assert C("EN VIVO: Comisión de Ordenamiento y Seguimiento Legislativo"
              ) == "Comision: Seguimiento Legislativo"
    assert C("EN VIVO: Comisión de Ética Parlamentaria") == "Comision: Etica Parlamentaria"
    # "Procedimientos Especiales" es una comision ORDINARIA real, no una
    # comision especial/ad-hoc - "especiales" modifica "procedimientos",
    # no "comision". No debe caer en la exclusion de "comision especial".
    assert C("EN VIVO: Comisión de Procedimientos Especiales"
              ) == "Comision: Procedimientos Especiales"
    # Las comisiones Especiales/ad-hoc de verdad siguen excluidas (la
    # frase es "comision especial", no la palabra suelta).
    assert C("🔴 EN VIVO: Comisión Especial encargada de investigar...") is None


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
