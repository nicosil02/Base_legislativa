"""Modulo de sesiones del Pleno del Congreso del Peru.

Paralelo a `sesiones/` (que cubre solo Comisiones Ordinarias), este modulo
consume la API publica del visor adp-portal:
  https://wb2server.congreso.gob.pe/adp-portal-service/api/

Cobertura: agendas del Pleno desde 2011 hasta hoy. Por default sincronizamos
el periodo unicameral 2021-2026 (histórico, 180 agendas) y el bicameral
2026-2031 (vigente — todavía sin agendas publicadas por acá al 2026-09-11)
para coherencia con el resto de la app.
"""
