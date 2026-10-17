"""Tests de sesiones/sync.py."""
from sesiones.sync import _comisiones_del_periodo


def test_comisiones_del_periodo_filtra_por_per_par_id():
    # Mismo nombre en Senado y Diputados: la camara sale del comisionId.
    # No debe mezclar comisiones de otro periodo ni perder las del pedido.
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
