"""Modulo de sesiones del Pleno del Congreso del Peru.

Paralelo a `sesiones/` (que cubre solo Comisiones Ordinarias), este modulo
consume la API publica del visor adp-portal:
  https://wb2server.congreso.gob.pe/adp-portal-service/api/

Cobertura: agendas del Pleno desde 2011 hasta hoy. Por default sincronizamos
solo el periodo parlamentario actual (2021-2026, 177 agendas) para coherencia
con el resto de la app.
"""
