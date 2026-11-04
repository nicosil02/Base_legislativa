"""Bandeja del analista: que alertas del Panel ya reviso y que hizo con cada una.

Estados: "alertar" (se armo la alerta), "interesante" (vale para el reporte
semanal pero no para una alerta), "despues" (la deja para mas tarde),
"descartar" (no va; las noticias ademas van a noticias/feedback_store para
que el juez aprenda). Va a un JSON del repo via core.store, asi sirve igual
en Streamlit Cloud y en cualquier PC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core import store

PATH = "data/bandeja_analista.json"
ESTADOS = {"alertar", "interesante", "despues", "descartar"}
GUARDAR_DIAS = 45  # el Panel mira 2 dias; el espacio por cliente (trafico quincenal de Bayer) mas


def estados() -> dict[str, dict]:
    return store.cargar(PATH, {}, ttl=20)


def marcar(clave: str, estado: str | None, por: str | None = None, titulo: str | None = None,
           item: dict | None = None) -> None:
    """estado None deshace. Lo de mas de GUARDAR_DIAS se borra al escribir.
    item: titulo, url, pais, resumen y porque {cliente: razon}, para el espacio por cliente."""
    if estado is not None and estado not in ESTADOS:
        raise ValueError(f"estado desconocido: {estado}")
    ahora = datetime.now(timezone.utc)
    corte = (ahora - timedelta(days=GUARDAR_DIAS)).isoformat(timespec="seconds")

    def cambio(d: dict) -> dict:
        d = {k: v for k, v in d.items() if v.get("fecha", "") >= corte and k != clave}
        if estado:
            d[clave] = {"estado": estado, "fecha": ahora.isoformat(timespec="seconds"), "por": por, "titulo": titulo}
            if item:
                d[clave]["item"] = item
        return d
    store.actualizar(PATH, cambio, f"bandeja: {estado or 'deshacer'} {clave[:40]}", {})


if __name__ == "__main__":  # chequeo rapido sin GitHub: usa el archivo local
    import tempfile
    from pathlib import Path
    from unittest import mock
    with tempfile.TemporaryDirectory() as tmp, mock.patch("core.store.ROOT", Path(tmp)), \
            mock.patch("core.store._cfg", return_value=None):
        (Path(tmp) / "data").mkdir()
        marcar("n1", "despues")
        marcar("n2", "alertar")
        marcar("n1", None)
        e = store.leer(PATH, {})[0]
        assert set(e) == {"n2"} and e["n2"]["estado"] == "alertar", e
        print("ok")
