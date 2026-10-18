#!/usr/bin/env bash
# Publica bases SQLite comprimidas en la rama `datos` como UN SOLO commit
# sin padre (sin historial), en vez de commitearlas en main: en `datos` cada
# publicacion REEMPLAZA a la anterior (el repo llego a 15 GB con la base en
# main, ver memoria git_history_bloat).
#
# proyectos.db va en partes, una por dueño (core/partes.py). Cada workflow
# publica SOLO las partes que escribe; las partes con varios escritores
# (transcripciones, tv) se unen fila por fila con lo ya publicado. El push va
# con --force-with-lease atado al commit que se bajo: si otro workflow
# publico en el medio, se rechaza y se rehace desde el principio.
#
# Uso: scripts/publicar_db.sh proyectos.db PARTE [PARTE ...]
#        PARTE: base (solo refrescar-pe), transcripciones, tv, votaciones
#      scripts/publicar_db.sh unico proyectos_ec.db
#        sin partes ni union: un solo workflow la escribe.
set -euo pipefail

LOCAL="$1"
shift
PARTES=("$@")
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ "$LOCAL" = "unico" ]; then
  LOCAL="${PARTES[0]}"
  PARTES=()
fi

for intento in 1 2 3 4 5 6; do
  REMOTO_SHA="$(git ls-remote origin refs/heads/datos | cut -f1)"
  [ -n "$REMOTO_SHA" ] && git fetch -q origin "+refs/heads/datos:refs/remotes/origin/datos"

  # Arbol nuevo = arbol actual de `datos` con lo nuestro reemplazado. Index
  # temporal: no toca el checkout ni el index del workflow.
  export GIT_INDEX_FILE="$TMP/index"
  if [ -n "$REMOTO_SHA" ]; then git read-tree "$REMOTO_SHA"; else git read-tree --empty; fi

  if [ ${#PARTES[@]} -eq 0 ]; then
    gzip -9nc "$LOCAL" > "$TMP/final.gz"
    git update-index --add --cacheinfo "100644,$(git hash-object -w "$TMP/final.gz"),data/$(basename "$LOCAL").gz"
  else
    # Base entera vieja (antes de las partes): si un workflow con el codigo
    # anterior la volvio a publicar, sus filas se rescatan en la union.
    VIEJA=""
    if [ -n "$REMOTO_SHA" ] && git show "origin/datos:data/proyectos.db.gz" > "$TMP/vieja.gz" 2>/dev/null; then
      gunzip -c "$TMP/vieja.gz" > "$TMP/vieja.db" && VIEJA="$TMP/vieja.db"
    fi
    for parte in "${PARTES[@]}"; do
      ARCH="proyectos.$parte.db"
      python -X utf8 -m core.partes extraer "$LOCAL" "$parte" "$TMP/$ARCH"
      if [ "$parte" != "base" ]; then
        if [ -n "$REMOTO_SHA" ] && git show "origin/datos:data/$ARCH.gz" > "$TMP/r.gz" 2>/dev/null; then
          gunzip -c "$TMP/r.gz" > "$TMP/r.db"
          python -X utf8 -m core.partes unir "$TMP/$ARCH" "$TMP/r.db" "$parte"
        fi
        if [ -n "$VIEJA" ]; then
          python -X utf8 -m core.partes extraer "$VIEJA" "$parte" "$TMP/rv.db"
          python -X utf8 -m core.partes unir "$TMP/$ARCH" "$TMP/rv.db" "$parte"
        fi
      fi
      gzip -9nc "$TMP/$ARCH" > "$TMP/$ARCH.gz"
      git update-index --add --cacheinfo "100644,$(git hash-object -w "$TMP/$ARCH.gz"),data/$ARCH.gz"
    done
    # Con las tres partes publicadas, la base entera vieja solo confunde.
    if git ls-files --error-unmatch data/proyectos.base.db.gz data/proyectos.transcripciones.db.gz \
         data/proyectos.tv.db.gz > /dev/null 2>&1; then
      git update-index --force-remove data/proyectos.db.gz
    fi
  fi
  ARBOL="$(git write-tree)"
  unset GIT_INDEX_FILE

  QUE="${PARTES[*]:-$(basename "$LOCAL")}"
  if [ -n "$REMOTO_SHA" ] && [ "$ARBOL" = "$(git rev-parse "$REMOTO_SHA^{tree}")" ]; then
    echo "[publicar_db] $QUE sin cambios en datos, nada que publicar."
    exit 0
  fi
  COMMIT="$(git commit-tree "$ARBOL" -m "datos: $QUE $(date -u +%Y-%m-%dT%H:%M:%SZ)")"
  if git push -q --force-with-lease="refs/heads/datos:$REMOTO_SHA" origin "$COMMIT:refs/heads/datos"; then
    echo "[publicar_db] $QUE publicado en datos (intento $intento)."
    exit 0
  fi
  echo "[publicar_db] otro workflow publico en el medio (intento $intento), rehago..."
  sleep $(( (RANDOM % 10) + 5 ))
done
echo "[publicar_db] no pude publicar $QUE despues de 6 intentos." >&2
exit 1
