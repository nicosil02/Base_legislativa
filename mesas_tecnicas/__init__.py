"""Mesas de trabajo + eventos del Congreso PE.

Fuente: WordPress publico de Comunicaciones del Congreso
  https://comunicaciones.congreso.gob.pe/agenda/

A diferencia de las sesiones formales (modulo sesiones/, via API
visor-sesiones) y del Pleno (modulo pleno/, via API adp-portal), las
mesas de trabajo y eventos puntuales se publican como posts del CMS
del Congreso. Cada item tiene:
  - tipo: "Mesa de trabajo" / "Ceremonia" / "Evento" / "Sesion descentralizada"
  - tema: descripcion del proposito
  - hora de inicio
  - congresista que organiza + bancada
  - lugar (sala del Congreso)

Tabla: mesas_tecnicas en proyectos.db (junto con sesiones, pleno, etc).
"""
