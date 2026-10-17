"""Mapeo de noticias de interes: medios, instituciones, sectores.

Cobertura Peru + Ecuador en categorias:
  - Coyuntura Politica (medios principales)
  - Institucion (Congreso/Asamblea, ministerios, agencias regulatorias)
  - Temas Agrarios (Midagri, Senasa, Conveagro, gremios)
  - Temas Salud (Minsa/MSP, Digemid/ARCSA, pacientes)
  - Temas Tech (DPL, Niubox, Hiperderecho, gremios digitales)
  - Temas KYC/AML (SBS, SuperProteccion Datos EC)

Cada fuente tiene un metodo de captura:
  - rss: la mayoria de medios y muchos sitios WordPress
  - html: scraping de pagina de noticias (cuando no hay RSS)
  - gobpe: API de busqueda de gob.pe
  - custom: scrapers propios (el_peruano.py, registro_oficial_ec.py)
  - twitter / manual: solo en el catalogo, sin captura automatica

Schema:
  noticias_fuentes (catalogo: id, categoria, pais, nombre, url, rss_url, tipo)
  noticias (items: id, fuente_id, titulo, url, fecha, resumen, captured_at)
  noticias_sync_runs (log)

CLI:
  python -m noticias.cli init           # crea tablas
  python -m noticias.cli seed           # importa catalogo desde fuentes.py
  python -m noticias.cli sync [--pais PE/EC] [--categoria X]
  python -m noticias.cli stats
"""
