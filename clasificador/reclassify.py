"""Reclasificacion masiva: revisa categorias mal asignadas con el modelo.

Modos de operacion:

1. SUGERENCIAS (dry-run, por defecto): para cada PL en "Otros", si el
   modelo predice otra categoria con confianza >= 0.7, genera una fila
   en la tabla `clasificacion_sugerencias`. No modifica la columna tema.

2. APPLY: aplica directamente los cambios de PLs en "Otros" con
   confianza >= 0.85. Por debajo de eso, deja la sugerencia para revision
   manual.

3. RESPECT_MANUAL: NUNCA toca PLs con tema_manual=1. Solo afecta a:
   - PLs con tema = 'Otros' (no importa si es manual=1 o no — el usuario
     mismo dijo que esta categoria esta inflada)
   - PLs sin tema (tema IS NULL)
   - PLs con tema_manual=0 (auto-clasificados por scraper)

NOTA: el modulo NO sobrescribe categorias manualmente asignadas por el
equipo (excepto "Otros"). El usuario puede revisar las sugerencias y
aceptar/rechazar via UI o CLI.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .predict import predict_tema_batch


# Tabla para tracking de cambios sugeridos y aplicados.
SCHEMA_SUGERENCIAS = """
CREATE TABLE IF NOT EXISTS clasificacion_sugerencias (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  pley_num        INTEGER NOT NULL,
  per_par_id      INTEGER NOT NULL,
  cod_tipo_parl   TEXT NOT NULL DEFAULT 'C',
  tema_anterior   TEXT,
  tema_sugerido   TEXT NOT NULL,
  confidence      REAL NOT NULL,
  estado          TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente / aplicado / rechazado
  created_at      TEXT NOT NULL,
  decided_at      TEXT,
  decided_by      TEXT,
  UNIQUE (pley_num, per_par_id, cod_tipo_parl, tema_sugerido)
);
CREATE INDEX IF NOT EXISTS idx_sug_pley ON clasificacion_sugerencias(pley_num, per_par_id, cod_tipo_parl);
CREATE INDEX IF NOT EXISTS idx_sug_estado ON clasificacion_sugerencias(estado);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    with conn:
        conn.executescript(SCHEMA_SUGERENCIAS)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(clasificacion_sugerencias)").fetchall()}
        if "cod_tipo_parl" not in cols:
            conn.execute(
                "ALTER TABLE clasificacion_sugerencias ADD COLUMN cod_tipo_parl TEXT NOT NULL DEFAULT 'C'"
            )


def reclassify_otros(
    conn: sqlite3.Connection,
    apply_threshold: float = 0.85,
    suggest_threshold: float = 0.70,
    apply: bool = False,
    dry_run: bool = True,
) -> dict:
    """Re-corre el clasificador sobre todos los PLs con tema='Otros'.

    Args:
        conn: conexion a proyectos.db
        apply_threshold: si confidence >= esto Y apply=True, actualiza
                         la columna tema (manteniendo tema_manual=0 para
                         que el equipo sepa que fue cambio automatico).
        suggest_threshold: si apply_threshold > confidence >= esto, registra
                           sugerencia pendiente.
        apply: si False, todo se queda en sugerencias. Si True, aplica
               los high-confidence.
        dry_run: si True, no escribe a la DB (solo cuenta).

    Returns:
        Dict con estadisticas (procesados, sugerencias, aplicados, etc).
    """
    init_schema(conn)

    rows = conn.execute(
        """
        SELECT pley_num, per_par_id, cod_tipo_parl, titulo, sumilla
        FROM proyectos
        WHERE tema = 'Otros'
        """
    ).fetchall()
    n = len(rows)
    print(f"[reclassify] {n} PLs en 'Otros' a evaluar")

    # Predict en batches de 1000 para no cargar todo en memoria
    aplicados = 0
    sugerencias = 0
    sin_cambio = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch_size = 1000

    for batch_start in range(0, n, batch_size):
        batch = rows[batch_start : batch_start + batch_size]
        textos = [f"{r[3] or ''} {r[4] or ''}" for r in batch]
        preds = predict_tema_batch(textos)
        for (pley_num, per_par_id, cod_tipo_parl, _, _), (tema_pred, conf) in zip(batch, preds):
            if tema_pred == "Otros":
                sin_cambio += 1
                continue
            if conf >= apply_threshold and apply:
                if not dry_run:
                    with conn:
                        conn.execute(
                            "UPDATE proyectos SET tema=?, tema_manual=0 "
                            "WHERE pley_num=? AND per_par_id=? AND cod_tipo_parl=?",
                            (tema_pred, pley_num, per_par_id, cod_tipo_parl),
                        )
                        # Tambien dejamos huella en sugerencias como 'aplicado'
                        conn.execute(
                            """INSERT OR IGNORE INTO clasificacion_sugerencias
                               (pley_num, per_par_id, cod_tipo_parl, tema_anterior, tema_sugerido,
                                confidence, estado, created_at, decided_at, decided_by)
                               VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (pley_num, per_par_id, cod_tipo_parl, "Otros", tema_pred, conf,
                             "aplicado", now, now, "auto-reclassify"),
                        )
                aplicados += 1
            elif conf >= suggest_threshold:
                if not dry_run:
                    with conn:
                        conn.execute(
                            """INSERT OR IGNORE INTO clasificacion_sugerencias
                               (pley_num, per_par_id, cod_tipo_parl, tema_anterior, tema_sugerido,
                                confidence, estado, created_at)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (pley_num, per_par_id, cod_tipo_parl, "Otros", tema_pred, conf,
                             "pendiente", now),
                        )
                sugerencias += 1
            else:
                sin_cambio += 1
        if (batch_start // batch_size) % 5 == 0:
            print(f"[reclassify] procesados {min(batch_start + batch_size, n)}/{n}")

    return {
        "procesados": n,
        "aplicados": aplicados,
        "sugerencias_pendientes": sugerencias,
        "sin_cambio": sin_cambio,
        "apply_threshold": apply_threshold,
        "suggest_threshold": suggest_threshold,
    }


def aplicar_decisiones(conn: sqlite3.Connection, decisiones: list[dict]) -> dict:
    """Aplica decisiones humanas (aceptar/rechazar) sobre sugerencias
    pendientes, registradas desde pages/1_Peru.py via
    clasificador/decisiones_store.py (ver ese modulo para el por que del
    round-trip: la UI no puede escribir proyectos.db directo).

    "aceptar" pone tema_manual=1 (no 0, a diferencia del auto-apply de
    reclassify_otros de arriba) - un humano revisando y confirmando ES
    una clasificacion manual real, y de paso queda disponible como dato
    de entrenamiento futuro (cmd_train usa tema_manual=1).

    Devuelve las `sugerencia_id` efectivamente procesadas (aplicadas,
    rechazadas, o simplemente ya no encontradas/ya resueltas) para que
    el caller (clasificador.cli aplicar-decisiones) las saque del JSON
    de pendientes - una decision nunca debe quedar reintentandose para
    siempre."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    aceptadas = rechazadas = ya_resueltas = no_encontradas = 0
    procesadas: list[int] = []

    for d in decisiones:
        sid = d["sugerencia_id"]
        row = conn.execute(
            "SELECT pley_num, per_par_id, cod_tipo_parl, tema_sugerido, estado "
            "FROM clasificacion_sugerencias WHERE id=?", (sid,)
        ).fetchone()
        if row is None:
            no_encontradas += 1
            procesadas.append(sid)
            continue
        pley_num, per_par_id, cod_tipo_parl, tema_sugerido, estado = row
        if estado != "pendiente":
            # Ya resuelta por otra via (ej. el reclassify semanal la
            # re-genero con mayor confianza y la auto-aplico) - nada que
            # hacer, solo dejar de reintentarla.
            ya_resueltas += 1
            procesadas.append(sid)
            continue
        with conn:
            if d["decision"] == "aceptar":
                conn.execute(
                    "UPDATE proyectos SET tema=?, tema_manual=1 "
                    "WHERE pley_num=? AND per_par_id=? AND cod_tipo_parl=?",
                    (tema_sugerido, pley_num, per_par_id, cod_tipo_parl),
                )
                conn.execute(
                    "UPDATE clasificacion_sugerencias SET estado='aplicado', "
                    "decided_at=?, decided_by=? WHERE id=?",
                    (now, d.get("decided_by"), sid),
                )
                aceptadas += 1
            else:
                conn.execute(
                    "UPDATE clasificacion_sugerencias SET estado='rechazado', "
                    "decided_at=?, decided_by=? WHERE id=?",
                    (now, d.get("decided_by"), sid),
                )
                rechazadas += 1
        procesadas.append(sid)

    return {
        "aceptadas": aceptadas, "rechazadas": rechazadas,
        "ya_resueltas": ya_resueltas, "no_encontradas": no_encontradas,
        "procesadas": procesadas,
    }
