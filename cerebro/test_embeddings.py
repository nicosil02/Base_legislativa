import pytest

pytest.importorskip("sqlite_vec")

from cerebro import embeddings as E  # noqa: E402


def _fake(textos):
    out = []
    for t in textos:
        v = [0.0] * E.DIM
        v[0 if "agro" in t else 1 if "futbol" in t else 3 if "lavado" in t else 2] = 1.0
        out.append(v)
    return out


def _item(clave, texto, tipo="noticia", pais="PE", titulo=None):
    return {"clave": clave, "tipo": tipo, "pais": pais, "titulo": titulo or clave.upper(),
            "fecha": "", "url": "", "extra": "{}", "texto": texto}


def test_sincroniza_busca_y_afinidad(tmp_path, monkeypatch):
    items = [_item("a", "agro plaguicidas"), _item("b", "futbol clasico"),
             _item("c", "agro semillas", tipo="pl", pais="EC")]
    monkeypatch.setattr(E, "CEREBRO_DB", tmp_path / "c.db")
    monkeypatch.setattr(E, "embeber", _fake)
    monkeypatch.setattr(E, "corpus", lambda: items)

    r = E.sincronizar()
    assert r["nuevos"] == 3 and r["total"] == 3, r
    assert E.sincronizar()["nuevos"] == 0  # nada cambió
    items[0]["texto"] = "agro plaguicidas SENASA"
    assert E.sincronizar()["nuevos"] == 1  # solo se re-embebe lo que cambió
    quitado = items.pop(1)
    assert E.sincronizar()["total"] == 2  # salió del corpus -> sale del índice
    items.insert(1, quitado)
    assert E.sincronizar()["nuevos"] == 1

    top = E.buscar("agro", k=3)
    assert {t["clave"] for t in top[:2]} == {"a", "c"} and top[0]["similitud"] > 0.99, top
    assert [t["clave"] for t in E.buscar("agro", k=3, pais="EC")] == ["c"]
    assert [t["clave"] for t in E.buscar("agro", k=3, tipo="noticia")][0] == "a"

    # Híbrida: códigos exactos que el vector no encuentra.
    items += [
        _item("d", "Resolucion UAFE-DG-2026-0014 sobre lavado", pais="EC",
              titulo="Nueva resolución contra el lavado"),
        _item("pl_PE_00565-2026-2031-CD", "semillas certificadas", tipo="pl",
              titulo="PL 00565-2026-2031-CD: Ley de semillas"),
    ] + [_item(f"r{i}", f"relleno {i}", pais="EC") for i in range(5)]
    assert E.sincronizar()["nuevos"] == 7
    q = "UAFE-DG-2026-0014"
    assert E.vecinos(_fake([q])[0], k=3)[0]["clave"] != "d"
    top = E.buscar(q, k=3)
    assert top[0]["clave"] == "d" and top[0]["coincide"] == "palabras", top
    assert E.buscar("uafe", k=3, pais="EC")[0]["clave"] == "d"
    assert E.buscar("uafe", k=3, pais="PE")[0]["clave"] != "d"
    assert E.buscar("PL 565", k=3)[0]["clave"] == "pl_PE_00565-2026-2031-CD"
    assert E.buscar("resolución", k=3)[0]["clave"] == "d"
    assert E.buscar("biometria", k=4) == E.vecinos(_fake(["biometria"])[0], k=4)
    for raro in ('"; DROP -- ("', "a*b", "NEAR(x y)", "-", "AND OR NOT"):
        E.buscar(raro, k=2)  # no rompe la sintaxis de MATCH

    # cerebro.db viejo sin items_fts: se crea y se rellena con títulos.
    conn = E.conectar()
    conn.execute("DROP TABLE items_fts")
    conn.commit()
    conn.close()
    assert E.palabras("lavado", conn=E.conectar()) and not E.palabras("UAFE", conn=E.conectar())

    conn = E.conectar()
    conn.execute("DELETE FROM perfiles WHERE cliente='bayer'")
    conn.execute("INSERT INTO perfiles VALUES ('bayer',0,'x','agro',?)", (E._blob(_fake(["agro"])[0]),))
    conn.execute("INSERT INTO perfiles VALUES ('bayer',1,'','futbol',?)", (E._blob(_fake(["futbol"])[0]),))
    af = E.afinidad(["a", "b", "c", "no-existe"], "bayer", conn)
    assert af["a"] > 0.99 and af["b"] > 0.99 and "no-existe" not in af, af


def test_fragmentos_perfil():
    frs = E.fragmentos_perfil("### Crop\n\n" + "x" * 500 + "\n\n**Peru.**\n\n" + "y" * 500)
    assert len(frs) == 2 and frs[0].startswith("### Crop") and frs[1].startswith("**Peru.**"), frs


def test_modelo_no_se_carga_en_la_app_web(monkeypatch):
    E._modelo.cache_clear()
    monkeypatch.setattr(E, "_en_app_web", lambda: True)
    with pytest.raises(RuntimeError):
        E._modelo()
    E._modelo.cache_clear()
