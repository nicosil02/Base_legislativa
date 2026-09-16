"""Checks de sesiones/sync.py. Correr: python -m sesiones.test_sync"""
from sesiones.sync import _comisiones_del_periodo


def test_comisiones_del_periodo_filtra_por_per_par_id():
    # Bug real 2026-09-16: el mapeo viejo (nombreComision -> camara) no
    # podia distinguir Senado de Diputados para nombres repetidos (la
    # inmensa mayoria de comisiones ordinarias en un Congreso bicameral) -
    # 2209 de 2274 sesiones quedaban con camara=NULL. El fix real es pedir
    # sesiones POR comisionId (una comision = una camara, sin ambiguedad) -
    # este check verifica que el filtro por periodo no mezcle comisiones
    # de otra epoca (2021 unicameral) ni pierda ninguna del periodo pedido.
    criterios = {
        "comisiones": [
            {"comisionId": 15, "nombreComision": "Justicia", "perParId": 2021, "codTipoParl": "C"},
            {"comisionId": 67, "nombreComision": "Justicia", "perParId": 2026, "codTipoParl": "S"},
            {"comisionId": 80, "nombreComision": "Justicia", "perParId": 2026, "codTipoParl": "D"},
        ]
    }
    out = _comisiones_del_periodo(criterios, 2026)
    assert set(out) == {(67, "Senado"), (80, "Diputados")}, out
    out_2021 = _comisiones_del_periodo(criterios, 2021)
    assert out_2021 == [(15, "Congreso")], out_2021


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK {name}")
    print("todos los checks pasaron")
