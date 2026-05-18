"""Agenda parlamentaria de Ecuador.

Sincroniza el calendario publico de la Asamblea Nacional (Zimbra ICS feed,
expuesto sin auth en correo.asambleanacional.gob.ec) con la base local.

Cruza descripciones de sesiones con titulos de proyectos en proyectos_ec.db
para detectar que PL se debate en cada sesion (matching por substring
normalizado del titulo del proyecto contra el campo DESCRIPTION del VEVENT).

Tablas (en proyectos_ec.db):
  - sesiones_ec
  - sesion_ec_pl_referenciado
"""
