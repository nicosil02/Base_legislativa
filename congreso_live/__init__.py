"""Vigilancia en vivo del Congreso del Peru por YouTube.

Detecta cuando el Pleno o una comision entra en vivo (YouTube en Peru,
Facebook para las comisiones de Ecuador), transcribe el audio con Whisper,
lo resume y avisa por Telegram lo que interesa. Tambien recupera las sesiones
que no se captaron en vivo (backfill) e identifica a los oradores. Corre en
GitHub Actions, sin maquina dedicada. Entrada: `python -m congreso_live.cli`.
"""
