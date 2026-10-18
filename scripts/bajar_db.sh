#!/usr/bin/env bash
# Baja una base de la rama `datos` (ver scripts/publicar_db.sh) y la deja
# descomprimida en DESTINO. proyectos.db se publica en partes (core/partes.py):
# se bajan todas y se arma la base completa, igual que siempre.
#
# Uso: scripts/bajar_db.sh NOMBRE_GZ DESTINO_DB
#   ej. scripts/bajar_db.sh proyectos.db.gz proyectos.db
set -euo pipefail
GZ="$1"
DESTINO="$2"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if ! git fetch -q origin "+refs/heads/datos:refs/remotes/origin/datos" 2>/dev/null; then
  echo "[bajar_db] no pude bajar la rama datos" >&2
  exit 1
fi

if [ "$GZ" = "proyectos.db.gz" ] && git cat-file -e "origin/datos:data/proyectos.base.db.gz" 2>/dev/null; then
  for parte in base transcripciones tv votaciones; do
    if git show "origin/datos:data/proyectos.$parte.db.gz" > "$TMP/$parte.gz" 2>/dev/null; then
      gunzip -c "$TMP/$parte.gz" > "$TMP/proyectos.$parte.db"
    fi
  done
  python -X utf8 -m core.partes armar "$DESTINO" "$TMP"
  echo "[bajar_db] proyectos.db armada desde sus partes en la rama datos -> $DESTINO"
elif git show "origin/datos:data/$GZ" > "$TMP/x.gz" 2>/dev/null && [ -s "$TMP/x.gz" ]; then
  gunzip -c "$TMP/x.gz" > "$DESTINO"
  echo "[bajar_db] $GZ desde la rama datos -> $DESTINO"
else
  echo "[bajar_db] no encontre $GZ en la rama datos" >&2
  exit 1
fi
