"""Utilidades de infraestructura (cross-cutting).

Modulos:
  - heartbeat: registra que un workflow / step corrio exitosamente
    (independiente de si hubo cambios en los datos). Usado para mostrar
    en la UI "actualizado hace X min" basado en la corrida real del
    workflow, no en si los datos del Congreso cambiaron.
"""
