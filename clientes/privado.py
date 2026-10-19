"""Datos de clientes cifrados dentro del repo publico.

En git solo van los `*.cifrado` (perfiles, historial de alertas, matrices);
el texto plano queda fuera (.gitignore). La web y los workflows los abren al
arrancar con la clave que ya tienen (GEMINI_API_KEY, o CLIENTES_CLAVE si se
define): no hace falta ningun secreto nuevo. Si se cambia la clave de
Gemini, primero `abrir` con la vieja y despues `cerrar` con la nueva.

Cifrado solo con la libreria estandar (corre igual en Streamlit, en cada
workflow y en Windows): flujo HMAC-SHA256 en modo contador + etiqueta
HMAC-SHA256 sobre nonce y texto cifrado (cifrar y despues autenticar).

Uso local:
  python -m clientes.privado abrir [--pisar]   # .cifrado -> texto (tras git pull)
  python -m clientes.privado cerrar            # texto -> .cifrado (antes de commit)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

CARPETA = Path(__file__).resolve().parent
SUFIJO = ".cifrado"
_MAGIA = b"VALI1"


def _claves() -> tuple[bytes, bytes] | None:
    base = os.environ.get("CLIENTES_CLAVE") or os.environ.get("GEMINI_API_KEY")
    if not base:
        return None
    raiz = hashlib.sha256(b"vali-clientes|" + base.encode()).digest()
    return (hmac.new(raiz, b"cifrar", hashlib.sha256).digest(),
            hmac.new(raiz, b"autenticar", hashlib.sha256).digest())


def _flujo(clave: bytes, nonce: bytes, n: int) -> bytes:
    bloques = (hmac.new(clave, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest()
               for i in range((n + 31) // 32))
    return b"".join(bloques)[:n]


def cifrar(datos: bytes, claves: tuple[bytes, bytes] | None = None) -> str:
    k_cif, k_mac = claves or _claves() or _sin_clave()
    nonce = secrets.token_bytes(16)
    cuerpo = bytes(a ^ b for a, b in zip(datos, _flujo(k_cif, nonce, len(datos))))
    etiqueta = hmac.new(k_mac, nonce + cuerpo, hashlib.sha256).digest()
    return base64.b64encode(_MAGIA + nonce + etiqueta + cuerpo).decode("ascii")


def descifrar(texto: str, claves: tuple[bytes, bytes] | None = None) -> bytes:
    k_cif, k_mac = claves or _claves() or _sin_clave()
    crudo = base64.b64decode(texto)
    if not crudo.startswith(_MAGIA):
        raise ValueError("no es un archivo cifrado de clientes")
    nonce, etiqueta, cuerpo = crudo[5:21], crudo[21:53], crudo[53:]
    if not hmac.compare_digest(etiqueta, hmac.new(k_mac, nonce + cuerpo, hashlib.sha256).digest()):
        raise ValueError("clave equivocada o archivo alterado")
    return bytes(a ^ b for a, b in zip(cuerpo, _flujo(k_cif, nonce, len(cuerpo))))


def _sin_clave():
    raise RuntimeError("falta GEMINI_API_KEY (o CLIENTES_CLAVE) para abrir los datos de clientes")


# Lo que la plataforma necesita (lo mismo que antes se versionaba en claro).
# Lo demas de clientes/ (Word de alertas, bluebooks originales, reportes) no
# se sube ni cifrado.
PATRONES = ["*/cliente.json", "*/notas.md", "*/historial_alertas.md", "*/formato_alertas.md",
            "_plantillas/whatsapp_alerta.md", "_plantillas/ejemplos_alertas.md",
            "_plantillas/matriz_monitoreo/*", "MatrizPLAndinos_Bayer CROP.xlsx",
            "140125 - Matriz - Matriz Legislativa y Regulatoria INCODE.xlsx"]


def privados(carpeta: Path = CARPETA) -> list[Path]:
    """Archivos de datos en texto que van (cifrados) al repo."""
    return sorted({p for pat in PATRONES for p in carpeta.glob(pat)
                   if p.is_file() and not p.name.endswith(SUFIJO)})


def abrir(pisar: bool = False, carpeta: Path = CARPETA) -> int:
    """Escribe el texto de cada .cifrado que falte (o todos con `pisar`).
    Sin clave no hace nada: lo que dependa de clientes vera la carpeta vacia."""
    claves = _claves()
    if not claves:
        return 0
    n = 0
    for c in carpeta.rglob("*" + SUFIJO):
        destino = c.with_name(c.name[:-len(SUFIJO)])
        if destino.exists() and not pisar:
            continue
        datos = descifrar(c.read_text(encoding="ascii"), claves)
        if not destino.exists() or destino.read_bytes() != datos:
            destino.write_bytes(datos)
            n += 1
    return n


def cerrar(carpeta: Path = CARPETA, solo: list[Path] | None = None) -> int:
    """Cifra cada archivo de datos cuyo contenido cambio (no reescribe los
    iguales: el nonce aleatorio haria un diff en cada corrida)."""
    claves = _claves() or _sin_clave()
    n = 0
    for p in solo or privados(carpeta):
        c = p.with_name(p.name + SUFIJO)
        datos = p.read_bytes()
        if c.exists():
            try:
                if descifrar(c.read_text(encoding="ascii"), claves) == datos:
                    continue
            except ValueError:
                pass
        c.write_text(cifrar(datos, claves), encoding="ascii")
        n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["abrir", "cerrar"])
    ap.add_argument("--pisar", action="store_true", help="abrir: reemplaza el texto local")
    a = ap.parse_args()
    n = abrir(a.pisar) if a.accion == "abrir" else cerrar()
    print(f"[clientes] {a.accion}: {n} archivo(s)")
