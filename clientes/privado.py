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

Sin la clave en la PC (lo normal): buzon. `enviar` cifra los archivos que se
le pasan con la llave publica clientes/buzon.pub (RSA-OAEP + AES-GCM) y deja
`*.buzon`; al hacer push, buzon-clientes.yml los abre con la privada (secreto
CLIENTES_BUZON), los pasa a .cifrado con la clave de siempre y borra el buzon.
  python -m clientes.privado enviar clientes/acme      # carpeta o archivos
Solo lo que se nombra: mandar todo pisaria el historial que la web ya actualizo.
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


BUZON = ".buzon"
_MAGIA_BUZON = b"BUZON1"
LLAVE_PUBLICA = CARPETA / "buzon.pub"


def a_buzon(datos: bytes, publica_pem: bytes) -> str:
    """Cifrado hibrido: clave AES-GCM al azar, envuelta con RSA-OAEP."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    clave, nonce = AESGCM.generate_key(256), secrets.token_bytes(12)
    oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    envuelta = serialization.load_pem_public_key(publica_pem).encrypt(clave, oaep)
    cuerpo = AESGCM(clave).encrypt(nonce, datos, None)
    return base64.b64encode(_MAGIA_BUZON + len(envuelta).to_bytes(2, "big") + envuelta + nonce + cuerpo).decode("ascii")


def de_buzon(texto: str, privada_pem: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    crudo = base64.b64decode(texto)
    if not crudo.startswith(_MAGIA_BUZON):
        raise ValueError("no es un archivo de buzon")
    n = int.from_bytes(crudo[6:8], "big")
    envuelta, nonce, cuerpo = crudo[8:8 + n], crudo[8 + n:20 + n], crudo[20 + n:]
    oaep = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    clave = serialization.load_pem_private_key(privada_pem, None).decrypt(envuelta, oaep)
    return AESGCM(clave).decrypt(nonce, cuerpo, None)


def enviar(rutas: list[Path], carpeta: Path = CARPETA, publica: Path | None = None) -> list[Path]:
    """Deja `<archivo>.buzon` de cada archivo de datos nombrado (o de los que hay
    en cada carpeta nombrada). Devuelve los buzones escritos."""
    pem = (publica or LLAVE_PUBLICA).read_bytes()
    validos = set(privados(carpeta))
    elegidos = sorted({p.resolve() for r in rutas for p in ([r] if r.is_file() else r.rglob("*"))}
                      & {v.resolve() for v in validos})
    out = []
    for p in elegidos:
        b = p.with_name(p.name + BUZON)
        b.write_text(a_buzon(p.read_bytes(), pem), encoding="ascii")
        out.append(b)
    return out


def recibir(carpeta: Path = CARPETA) -> int:
    """CI: abre cada .buzon (CLIENTES_BUZON), lo pasa a .cifrado y lo borra."""
    privada = os.environ.get("CLIENTES_BUZON")
    if not privada:
        raise RuntimeError("falta CLIENTES_BUZON")
    textos = []
    for b in sorted(carpeta.rglob("*" + BUZON)):
        destino = b.with_name(b.name[:-len(BUZON)])
        destino.write_bytes(de_buzon(b.read_text(encoding="ascii"), privada.encode()))
        textos.append(destino)
        b.unlink()
    if textos:
        cerrar(carpeta, solo=textos)
    return len(textos)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["abrir", "cerrar", "enviar", "recibir"])
    ap.add_argument("rutas", nargs="*", type=Path, help="enviar: carpetas o archivos de clientes/")
    ap.add_argument("--pisar", action="store_true", help="abrir: reemplaza el texto local")
    a = ap.parse_args()
    if a.accion == "enviar":
        hechos = enviar(a.rutas)
        for b in hechos:
            print(f"  {b}")
        print(f"[clientes] {len(hechos)} buzon(es). Commit y push de esos .buzon: GitHub los cifra solo.")
    else:
        n = {"abrir": lambda: abrir(a.pisar), "cerrar": cerrar, "recibir": recibir}[a.accion]()
        print(f"[clientes] {a.accion}: {n} archivo(s)")
