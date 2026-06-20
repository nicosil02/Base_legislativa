"""Vigilancia en vivo del Congreso del Peru por YouTube.

Fase 0: detecta cuando el Pleno o una comision ordinaria entra EN VIVO en el
canal @congresodelarepublicaperu y avisa por WhatsApp. Corre en GitHub Actions
(repo publico = minutos gratis), sin maquina dedicada.

Fase 1 (pendiente): transcribir el audio en vivo (ffmpeg + STT), extraer numero
de PL y votacion (1ra/2da, a favor/contra/abstencion, aprobado), y notificar.
"""
