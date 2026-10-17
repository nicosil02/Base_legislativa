"""clientes/<slug>/historial_alertas.md: las alertas ya enviadas a cada
cliente. El chat las lee para dar continuidad y el cerebro las indexa."""
from __future__ import annotations

import re
from datetime import date

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


_PAISES = re.compile(r"^Pa[ií]ses:\s*(.+)$", re.MULTILINE)


def paises(slug: str) -> set[str]:
    """Paises que se monitorean para el cliente, de la linea `Países: PE, EC`
    de su notas.md. Sin esa linea, los dos."""
    p = ROOT / "clientes" / slug / "notas.md"
    m = _PAISES.search(p.read_text(encoding="utf-8")) if p.exists() else None
    return {x.strip().upper() for x in m.group(1).split(",")} if m else {"PE", "EC"}


def clientes(pais: str | None = None) -> list[str]:
    """Carpetas de clientes/ con bluebook (notas.md), opcionalmente solo las
    que cubren `pais`. Deja afuera _plantillas y reportes."""
    d = ROOT / "clientes"
    todos = sorted(p.parent.name for p in d.glob("*/notas.md")) if d.is_dir() else []
    return [c for c in todos if not pais or pais in paises(c)]
