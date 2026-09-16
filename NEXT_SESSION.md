# Estado al 2026-09-16 (fin de sesión larga)

Notas para retomar desde cualquier PC — `git pull` trae todo lo de acá, incluida
`clientes/_plantillas/matriz_monitoreo/` (recién publicada, antes local-only).

## Lo más importante de hoy

**Bug de fondo encontrado y arreglado:** `vigilar-congreso.yml` y `backfill-vod.yml`
(los workflows que transcriben sesiones en vivo) estaban pisando en silencio los
avances de `refrescar-pe.yml` (noticias, PLs) cada vez que ganaban una carrera de
push — usaban su propio `proyectos.db` local (potencialmente horas viejo, corren
hasta 170 min) como base del merge de conflicto en vez de `origin/main`. Fix real
en 5 puntos de esos 2 workflows, commit `49e13a5`. Verificado en vivo: un sync de
noticias post-fix sobrevivió intacto pese a comisiones corriendo en paralelo.

**`noticias/fuentes.py`:** pase completo de triage sobre ~44 fuentes marcadas como
"sin ninguna noticia". De 144 fuentes activas bajó a ~118, cada desactivación con
causa raíz real verificada en vivo (no por sospecha) — DNS caído, 404, feeds
vacíos, páginas de gobierno abandonadas, colisión de sigla (ALAFAR real vs.
fabricantes de refractarios), bot-blocks genuinos. Se documentaron (sin
desactivar) los casos de bloqueo por IP de datacenter de GitHub Actions (CONAIE,
SOLCA, Ministerio del Ambiente EC) porque funcionan bien desde otra IP.

**Matriz de monitoreo aplicada:** `clientes/_plantillas/matriz_monitoreo/` tenía
investigación real (2026-09-12) sobre 2 fusiones ministeriales en Ecuador
(Ambiente+Energía; Agricultura+Finanzas+Producción → un solo MDEP) que nunca se
había aplicado a `fuentes.py`. Ya está aplicada, con RSS reales verificados en
vivo. También se confirmó contra el `notas.md` real de Google que Ecuador no está
en su lista de entidades — se sacó un tag `"google"` que era solo una inferencia.

**Bug de UI arreglado:** `StreamlitDuplicateElementKey` en Agenda PE / pestaña
Transcripciones — una sesión que aparecía a la vez en "En vivo" y "Sesiones
previas" generaba dos `st.toggle` con la misma key. Fix en
`pages/3_Agenda_PE.py`.

## Pendiente / a verificar en la próxima sesión

1. **Confirmar que el bug de silent-overwrite no volvió a pasar.** El fix se
   subió a las 19:05 UTC del 16/09, pero un job de `vigilar-congreso.yml` que
   ya había arrancado antes siguió corriendo con el código viejo hasta que
   terminó su ventana (hasta 170 min). Si algo de noticias/PLs se ve "revertido"
   sin razón aparente, chequear `noticias_sync_runs.finished_at` contra el
   historial real de runs de `refrescar-pe.yml` antes de asumir que el sync
   está roto de nuevo. Ver memoria `noticias_sync_silent_overwrite_bug.md`.
2. **Ver si hace falta reintentar alguna de las fuentes con bloqueo de IP**
   (CONAIE, SOLCA Ecuador, Ministerio del Ambiente EC — dan 429/403 solo desde
   IPs de datacenter de GitHub Actions, funcionan bien desde otra IP). No se
   tocó nada más allá de documentarlo.
3. **El campo `"clientes"` de `matriz_sheet1.json` no está conectado a
   `noticias/fuentes.py`** (que no tiene ese campo) — el filtro real de
   relevancia por cliente sigue siendo solo `noticias/temas.py` +
   `TEMAS_CLIENTE`. Si se quiere usar la matriz para algo más que referencia,
   falta esa integración.
4. Pedido explícito pendiente de una sesión anterior: automatizar la tabla de
   agenda semanal si Nicolas la sigue pidiendo cada lunes (nunca se programó).

## Dónde mirar si algo no cuadra

- `clientes/_plantillas/matriz_monitoreo/matriz_sheet1.json` — catálogo de
  URLs reales PE/EC con tag de a qué cliente le importa cada una.
- `.github/workflows/{refrescar-pe,vigilar-congreso,backfill-vod}.yml` — los
  3 workflows que escriben `data/proyectos.db.gz`; ver comentarios sobre el
  merge de conflicto antes de tocarlos.
- `noticias/fuentes.py` — cada fuente desactivada tiene su `notas` con la
  evidencia real de por qué.
