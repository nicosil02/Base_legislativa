# Scraper de Proyectos de Ley — Congreso del Perú

Base de datos local de los proyectos de ley del período parlamentario 2021-2026,
construida sobre el API público del portal `spley-portal` del Congreso.

## Instalación

```bash
pip install -r requirements.txt
```

## Uso

```bash
# 1. Crear DB y cargar la lista de 24 comisiones
python -m scraper.cli init

# 2. Cargar / actualizar proyectos (uso diario)
python -m scraper.cli update                # sólo trae detalle de los nuevos o con estado cambiado
python -m scraper.cli update --full         # vuelve a pedir el detalle de todos
python -m scraper.cli update --limit 50     # útil para probar

# 3. Exportar a JSON
python -m scraper.cli export --out proyectos.json

# 4. Consultar
python -m scraper.cli query --comision 4
python -m scraper.cli query --estado "EN COMISIÓN" --limit 20
python -m scraper.cli show 14515            # detalle e historial de un proyecto
```

## Cómo funciona

El portal oficial (`https://wb2server.congreso.gob.pe/spley-portal/`) es una SPA
en Angular que consume un API REST en `https://api.congreso.gob.pe/spley-portal-service`.

- **Listado**: `POST /proyecto-ley/lista-con-filtro` con `{perParId: 2021, first, rows}`.
  Devuelve un índice rápido con estado, autores y fechas.
- **Detalle**: `GET /expediente/{enc(perParId)}/{enc(pleyNum)}`. Los parámetros
  se cifran con AES-128-ECB + PKCS7 (clave en `scraper/api.py`) y se codifican
  en base64 url-safe. El detalle trae las **comisiones asignadas**, el
  **historial completo de seguimientos** (cambios de estado con fecha) y los
  **firmantes** (autores y coautores con DNI y página web).
- **Comisiones**: `GET /comisiones` (catálogo de 24).
- **PDF**: `GET /archivo/{base64(proyectoArchivoId)}/pdf`.

El sync **sólo llama al detalle** para proyectos nuevos o cuyo `desEstado`
cambió respecto a lo guardado — así un update incremental diario hace pocas
docenas de llamadas en lugar de 14k.

## Esquema

- `proyectos` (clave: `per_par_id`, `pley_num`) — fila principal con
  `first_seen_at`, `last_seen_at` y `last_changed_at`.
- `proyecto_comision` — relación N:M con las comisiones asignadas.
- `firmantes` — autores/coautores con `tipo_firmante` (1=autor, 2=coautor).
- `seguimientos` — historial de cambios tal como lo da el servidor.
- `archivos` — PDFs adjuntos por seguimiento.
- `comisiones` — catálogo.
- `sync_runs` — bitácora de cada corrida.

## Notas

- El primer load completo tarda ~20–40 min (14.6k proyectos × ~150 ms por llamada).
- `proyectos.db` y `proyectos.json` están en `.gitignore`.
- Para extender al período 2016-2021 cuando se quiera, cambiar `PER_PAR_ID_ACTUAL`
  en `scraper/sync.py` o agregar un argumento `--per-par-id` al CLI.
