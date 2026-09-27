#!/usr/bin/env bash
# Publica una base SQLite comprimida en la rama `datos` como UN SOLO commit
# sin padre (sin historial), en vez de commitearla en main.
#
# Por que: data/proyectos.db.gz (~27 MB, ya comprimido: git no lo puede
# delta-comprimir) se commiteaba en main en cada corrida - 226 versiones en
# 5 dias, el repo volvio a 15 GB (ya se habia limpiado de 43 GB el
# 2026-09-22). En `datos` cada publicacion REEMPLAZA a la anterior: la rama
# siempre tiene 1 commit, y lo viejo queda inalcanzable (GitHub lo borra).
#
# Misma proteccion que antes contra pisarse entre workflows (bug real
# 2026-09-15/16, transcripciones borradas por un push desde una copia
# vieja): se baja lo ultimo de `datos`, se mezcla con merge_db, y se sube
# con --force-with-lease atado al commit que se bajo. Si otro workflow
# publico en el medio, el push se rechaza y se reintenta desde el principio.
#
# Uso: scripts/publicar_db.sh MODO BASE_LOCAL [NOMBRE_GZ]
#   MODO base_local  : la copia local es la base (dueña de PLs/agenda/noticias)
#                      y se le suman las transcripciones que tenga `datos`.
#                      Para refrescar-pe.yml.
#   MODO base_remota : la version de `datos` es la base y se le suman las
#                      transcripciones locales. Para vigilar-congreso.yml y
#                      los backfill (solo escriben sesiones_transcripciones).
#   MODO unico       : sin merge (proyectos_ec.db: un solo workflow la escribe).
#   NOMBRE_GZ        : default <basename de BASE_LOCAL>.gz, en data/ de `datos`.
set -euo pipefail

MODO="$1"
LOCAL="$2"
GZ="${3:-$(basename "$LOCAL").gz}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for intento in 1 2 3 4 5 6; do
  REMOTO_SHA="$(git ls-remote origin refs/heads/datos | cut -f1)"
  HAY_REMOTO=""
  if [ -n "$REMOTO_SHA" ]; then
    git fetch -q origin "+refs/heads/datos:refs/remotes/origin/datos"
    if git show "origin/datos:data/$GZ" > "$TMP/remoto.gz" 2>/dev/null && [ -s "$TMP/remoto.gz" ]; then
      gunzip -c "$TMP/remoto.gz" > "$TMP/remoto.db"
      HAY_REMOTO=1
    fi
  fi

  case "$MODO" in
    base_local)
      [ -n "$HAY_REMOTO" ] && python -X utf8 -m congreso_live.merge_db "$LOCAL" "$TMP/remoto.db"
      cp "$LOCAL" "$TMP/final.db" ;;
    base_remota)
      if [ -n "$HAY_REMOTO" ]; then
        cp "$TMP/remoto.db" "$TMP/final.db"
        python -X utf8 -m congreso_live.merge_db "$TMP/final.db" "$LOCAL"
        # NO se copia el resultado de vuelta a $LOCAL: en vigilar-congreso.yml
        # live-watch sigue ESCRIBIENDO en esa base mientras esto corre, y
        # pisarle el archivo por debajo la puede corromper. Cada publicacion
        # rehace el merge desde `datos`, asi que no hace falta.
      else
        cp "$LOCAL" "$TMP/final.db"
      fi ;;
    unico)
      cp "$LOCAL" "$TMP/final.db" ;;
    *) echo "MODO invalido: $MODO" >&2; exit 2 ;;
  esac
  gzip -9nc "$TMP/final.db" > "$TMP/final.gz"

  # Arbol nuevo = arbol actual de `datos` (conserva la OTRA base, ej.
  # proyectos_ec.db.gz) con data/$GZ reemplazado. Index temporal: no toca
  # el checkout ni el index del workflow.
  export GIT_INDEX_FILE="$TMP/index"
  if [ -n "$REMOTO_SHA" ]; then git read-tree "$REMOTO_SHA"; else git read-tree --empty; fi
  BLOB="$(git hash-object -w "$TMP/final.gz")"
  git update-index --add --cacheinfo "100644,$BLOB,data/$GZ"
  ARBOL="$(git write-tree)"
  unset GIT_INDEX_FILE

  if [ -n "$REMOTO_SHA" ] && [ "$ARBOL" = "$(git rev-parse "$REMOTO_SHA^{tree}")" ]; then
    echo "[publicar_db] $GZ sin cambios en datos, nada que publicar."
    exit 0
  fi
  COMMIT="$(git commit-tree "$ARBOL" -m "datos: $GZ $(date -u +%Y-%m-%dT%H:%M:%SZ)")"
  if git push -q --force-with-lease="refs/heads/datos:$REMOTO_SHA" origin "$COMMIT:refs/heads/datos"; then
    echo "[publicar_db] $GZ publicado en datos (intento $intento, modo $MODO)."
    exit 0
  fi
  echo "[publicar_db] otro workflow publico en el medio (intento $intento), rehago el merge..."
  sleep $(( (RANDOM % 10) + 5 ))
done
echo "[publicar_db] no pude publicar $GZ despues de 6 intentos." >&2
exit 1
