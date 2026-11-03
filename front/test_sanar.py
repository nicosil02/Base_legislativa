import sys
import types


def test_reimporta_modulo_a_medio_cargar():
    """Nube 3/11/2026: el hilo de secciones quedo con un que_paso_hoy sin hallazgos."""
    from front import vistas
    roto = types.ModuleType("alerts.que_paso_hoy")
    viejo = vistas.q
    vistas.q, sys.modules["alerts.que_paso_hoy"] = roto, roto
    try:
        assert callable(vistas._armar(lambda: vistas.q.hallazgos))
        assert vistas.q is not roto
    finally:
        sys.modules["alerts.que_paso_hoy"] = vistas.q if vistas.q is not roto else viejo
