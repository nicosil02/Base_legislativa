"""clientes/<slug>/historial_alertas.md: las alertas ya enviadas a cada
cliente. El chat las lee para dar continuidad y el cerebro las indexa."""
from __future__ import annotations

import re
from datetime import date

from clientes import config
from core import store
from core.db import ROOT

_ENCABEZADO = re.compile(r"^## (\d{4}-\d{2}-\d{2})(.*)$", re.MULTILINE)


def ruta(slug: str) -> str:
    return f"clientes/{slug}/historial_alertas.md"


def leer(slug: str) -> str:
    """Lo ultimo publicado (GitHub si hay credenciales), asi una alerta
    recien guardada entra al contexto sin esperar el redeploy."""
    texto, _ = store.leer_texto(ruta(slug), "")
    return texto or ""


def entrada(titulo: str, texto: str, pais: str, url: str | None = None,
            linea: str | None = None, fecha: str | None = None) -> str:
    partes = [fecha or date.today().isoformat()] + [p for p in (linea, pais) if p]
    cuerpo = texto.strip() + (f"\nFuente: {url}" if url and url not in texto else "")
    return f"## {' — '.join(partes)}\n**{titulo.strip()}**\n{cuerpo}\n"


def agregar(slug: str, entrada_md: str, autor: str | None = None) -> None:
    """Agrega la entrada al final del historial (commit en GitHub)."""
    store.actualizar_texto(
        ruta(slug), lambda t: t.rstrip() + "\n\n" + entrada_md,
        f"alertas: enviada a {slug}" + (f" ({autor})" if autor else ""),
        default=f"# {slug} — historial de alertas enviadas\n\n---\n")


def entradas(slug: str, texto: str | None = None) -> list[dict]:
    """[{fecha, encabezado, cuerpo}] en orden. Lee el archivo local del repo
    salvo que se pase `texto`."""
    if texto is None:
        p = ROOT / ruta(slug)
        texto = p.read_text(encoding="utf-8") if p.exists() else ""
    marcas = list(_ENCABEZADO.finditer(texto))
    out = []
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        out.append({"fecha": m.group(1), "encabezado": m.group(0)[3:].strip(),
                    "cuerpo": texto[m.end():fin].strip()})
    return out


def paises(slug: str) -> set[str]:
    """Paises que se monitorean para el cliente ("paises" de su cliente.json)."""
    return set(config.todos().get(slug, {}).get("paises", ["PE", "EC"]))


def clientes(pais: str | None = None) -> list[str]:
    """Clientes (clientes/<slug>/cliente.json), opcionalmente solo los que cubren `pais`."""
    return config.slugs(pais)
