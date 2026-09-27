#!/usr/bin/env bash
# Baja una base de la rama `datos` (ver scripts/publicar_db.sh) y la deja
# descomprimida en DESTINO. Si `datos` todavia no la tiene (transicion),
# usa la copia vieja de data/ en el checkout.
#
# Uso: scripts/bajar_db.sh NOMBRE_GZ DESTINO_DB
#   ej. scripts/bajar_db.sh proyectos.db.gz proyectos.db
set -euo pipefail
GZ="$1"
DESTINO="$2"
if git fetch -q origin "+refs/heads/datos:refs/remotes/origin/datos" 2>/dev/null \
    && git show "origin/datos:data/$GZ" > "/tmp/bajar_$GZ" 2>/dev/null && [ -s "/tmp/bajar_$GZ" ]; then
  gunzip -c "/tmp/bajar_$GZ" > "$DESTINO"
  rm -f "/tmp/bajar_$GZ"
  echo "[bajar_db] $GZ desde la rama datos -> $DESTINO"
elif [ -f "data/$GZ" ]; then
  gunzip -kc "data/$GZ" > "$DESTINO"
  echo "[bajar_db] $GZ desde data/ del checkout (datos todavia no la tiene) -> $DESTINO"
else
  echo "[bajar_db] no encontre $GZ ni en datos ni en data/" >&2
  exit 1
fi
