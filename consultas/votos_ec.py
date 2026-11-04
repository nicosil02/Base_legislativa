"""Votos nominales del Pleno de la Asamblea de Ecuador (2025-2029).

Salen del Observatorio Legislativo (Fundacion Ciudadania y Desarrollo), que publica
cada votacion con el voto de los 151 asambleistas en su API de WordPress
(/wp-json/wp/v2/votacion). El sitio de la Asamblea no publica el detalle en un
formato que se pueda leer y bloquea a los programas (403). El Observatorio carga
con meses de atraso: lo mas nuevo sale de las transcripciones (solo totales).
Algunas votaciones vienen mal cargadas: ver creible().

Se baja una vez al dia en la app; si falla queda la copia data/votos_ec.json.gz.
    python -m consultas.votos_ec   # renueva la copia
"""
from __future__ import annotations

import gzip
import json
import threading
import time
from pathlib import Path

from consultas.personas import id_ec

COPIA = Path(__file__).resolve().parent.parent / "data" / "votos_ec.json.gz"
API = "https://observatoriolegislativo.ec/wp-json/wp/v2/votacion"
_VOTO = {"SI": "SI", "NO": "NO", "AB": "ABST", "BL": "BLANCO"}  # vacio: no voto


def _limpia(x: dict) -> dict:
    d, m, a = x["acf"]["fecha"].split("/")
    return {"fecha": f"{a}-{m}-{d}", "asunto": x["title"]["rendered"], "url": x["link"],
            "votos": {id_ec(v["asambleista"]): _VOTO.get(v["voto"]) for v in x["acf"].get("listado_de_votos") or []}}


def bajar() -> list[dict]:
    import html

    from core.http import session
    s, filas = session(), []
    for pagina in range(1, 50):
        r = s.get(API, params={"per_page": 100, "page": pagina, "_fields": "link,title,acf.fecha,acf.listado_de_votos"}, timeout=90)
        if r.status_code == 400:  # se acabaron las paginas
            break
        r.raise_for_status()
        filas += r.json()
    for x in filas:
        x["title"]["rendered"] = html.unescape(x["title"]["rendered"])
    limpias = [_limpia(x) for x in filas if x["acf"].get("fecha", "").count("/") == 2]  # 1 viene sin fecha
    return sorted((v for v in limpias if creible(v)), key=lambda v: v["fecha"])


def creible(v: dict) -> bool:
    """Descarta las votaciones con 148 o mas votos iguales. Un 20% trae a toda la
    Asamblea votando lo mismo por error: la ley minera del 26/02/2026 salio 77-70-3
    y el Observatorio la carga con 151 a favor. Una unanimidad real se pierde, pero
    no dice nada de la postura de nadie."""
    cuenta: dict = {}
    for x in v["votos"].values():
        cuenta[x] = cuenta.get(x, 0) + 1
    return max(cuenta.values(), default=0) < 148


_estado: dict = {"datos": None, "hora": 0.0}
_CANDADO = threading.Lock()


def _renovar() -> None:
    try:
        _estado["datos"] = bajar()
    except Exception as e:  # queda lo que habia; se reintenta en un dia
        print(f"[votos_ec] sigo con la copia: {e}")


def votaciones() -> list[dict]:
    """De la mas vieja a la mas nueva. Responde con la copia y renueva por detras una vez al dia."""
    with _CANDADO:
        if _estado["datos"] is None:
            _estado["datos"] = json.loads(gzip.decompress(COPIA.read_bytes()))
        if time.time() - _estado["hora"] > 24 * 3600:
            _estado["hora"] = time.time()
            threading.Thread(target=_renovar, daemon=True, name="vali-votos-ec").start()
        return _estado["datos"]


if __name__ == "__main__":
    v = _limpia({"acf": {"fecha": "21/05/2026", "listado_de_votos": [{"asambleista": "Acuña Vaca María Cristina", "voto": "AB"},
                                                                       {"asambleista": "Aguas Flores Milton", "voto": ""}]},
                 "title": {"rendered": "Ley X"}, "link": "u"})
    assert v["fecha"] == "2026-05-21" and v["votos"] == {"EC:acuna vaca": "ABST", "EC:aguas flores": None}, v
    assert creible(v) and not creible({"votos": {str(i): "SI" for i in range(151)}})
    datos = bajar()
    assert len(datos) >= 300 and all(len(x["votos"]) >= 140 for x in datos), len(datos)
    COPIA.write_bytes(gzip.compress(json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode()))
    print("ok", len(datos), datos[0]["fecha"], datos[-1]["fecha"], f"{COPIA.stat().st_size // 1024} KB")
