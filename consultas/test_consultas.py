from consultas import hora_a_minutos


def test_hora_a_minutos():
    assert [hora_a_minutos(h) for h in ["9:00AM", "12:00AM", "12:00PM", "2:30PM", "14:30", "", None, "x"]] \
        == [540, 0, 720, 870, 870, -1, -1, -1]
