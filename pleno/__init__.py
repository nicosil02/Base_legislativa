"""Modulo de sesiones del Pleno del Congreso del Peru.

Paralelo a `sesiones/` (que cubre solo Comisiones Ordinarias), este modulo
consume la API publica del visor adp-portal:
  https://wb2server.congreso.gob.pe/adp-portal-service/api/

Cobertura: agendas del Pleno desde 2011. Esa API no tiene el Pleno
bicameral 2026-2031: ese sale de los PDF de cada camara (pleno/agenda_pdf.py).
"""
