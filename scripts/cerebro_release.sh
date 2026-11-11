#!/usr/bin/env bash
# Adjuntos del release publico "cerebro" (cerebro.db, grafo.tar.gz). Llevan
# perfiles y relevancia por cliente, asi que viajan cifrados con CLIENTES_CLAVE
# (clientes/privado.py, AES-256-GCM). Necesita gh con GH_TOKEN y pycryptodome.
#
#   bash scripts/cerebro_release.sh bajar cerebro.db   # release -> data/cerebro.db
#   bash scripts/cerebro_release.sh subir cerebro.db   # data/cerebro.db -> release
#
# bajar: si el adjunto no existe no falla (la primera vez se arma de cero),
# pero si existe y no se puede bajar o abrir, falla: armar de cero ahi
# pisaria lo publicado.
set -euo pipefail
accion="$1"; nombre="$2"
mkdir -p data
adjuntos=$(gh release view cerebro --json assets --jq '.assets[].name')
hay() { grep -qxF "$1" <<<"$adjuntos"; }

case "$accion" in
  bajar)
    if hay "$nombre.cifrado"; then
      gh release download cerebro -p "$nombre.cifrado" -D data --clobber
      python -X utf8 -m clientes.privado abrir-archivo "data/$nombre.cifrado" "data/$nombre"
      rm "data/$nombre.cifrado"
    elif hay "$nombre"; then  # adjunto en claro, de antes del 11/11/2026
      gh release download cerebro -p "$nombre" -D data --clobber
    else
      echo "sin $nombre previo, se arma de cero"
    fi ;;
  subir)
    python -X utf8 -m clientes.privado cerrar-archivo "data/$nombre" "data/$nombre.cifrado"
    gh release upload cerebro "data/$nombre.cifrado" --clobber
    rm "data/$nombre.cifrado"
    if hay "$nombre"; then gh release delete-asset cerebro "$nombre" -y; fi ;;
  *) echo "uso: $0 bajar|subir <adjunto>" >&2; exit 2 ;;
esac
