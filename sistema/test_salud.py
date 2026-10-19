from datetime import datetime, timezone

from sistema import salud


def _t(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_cron_ventanas_reales():
    vigilar = ["*/10 13-23 * * 1-5", "*/10 0-3 * * 2-6"]
    # sabado 17/10 03:50 UTC es la ultima de la semana (viernes 22:50 Lima)
    assert salud.ultimo_disparo(vigilar, _t(2026, 10, 19, 12, 0)) == _t(2026, 10, 17, 3, 50)
    assert salud.ultimo_disparo(["0 0-3,13-23 * * *"], _t(2026, 10, 18, 9, 0)) == _t(2026, 10, 18, 3, 0)
    assert salud.ultimo_disparo(["35 */3 * * *"], _t(2026, 10, 18, 7, 0)) == _t(2026, 10, 18, 6, 35)


def test_sin_correr_con_margen():
    crons = ["0 11 * * *"]
    corrio = [{"created_at": "2026-10-18T11:40:00Z", "status": "completed"}]
    assert salud.sin_correr("TV", crons, corrio, _t(2026, 10, 18, 15, 0)) == {}
    # el de hoy todavia esta dentro del margen: se mira el de ayer
    assert salud.sin_correr("TV", crons, corrio, _t(2026, 10, 19, 12, 0)) == {}
    assert "sin_correr:TV" in salud.sin_correr("TV", crons, corrio, _t(2026, 10, 19, 13, 0))


def test_fallas_seguidas_ignora_canceladas():
    r = lambda c: {"status": "completed", "conclusion": c, "created_at": "2026-10-18T10:00:00Z", "html_url": "u"}
    ahora = _t(2026, 10, 18, 12, 0)
    assert salud.fallas("X", [r("failure"), r("cancelled"), r("failure"), r("success")], ahora)
    assert salud.fallas("X", [r("failure"), r("success"), r("failure")], ahora) == {}


def test_mensaje_avisa_una_vez_y_cuando_se_recupera():
    assert salud.mensaje({"a": "A"}, {"a": "A otra fecha"}) is None
    m = salud.mensaje({"a": "A"}, {"b": "B"})
    assert "B" in m.split("Se recuper")[0] and "A" in m.split("Se recuper")[1]
