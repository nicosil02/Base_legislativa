from datetime import date

import pytest

from cerebro import grafo


@pytest.mark.skipif(grafo._db("proyectos.db") is None, reason="sin proyectos.db local")
def test_documentos_ids_estables_y_solo_dias_cerrados():
    docs = grafo.documentos()
    ids = [i for i, _ in docs]
    assert len(ids) == len(set(ids))
    assert not any(i.endswith(date.today().isoformat()) for i in ids)
    assert any(i.startswith("cliente_bayer_") for i in ids)
    assert grafo.documentos() == docs  # determinista
