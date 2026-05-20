"""Clasificador supervisado de temas para proyectos de ley.

Reemplaza al sistema de keywords-regex de `scraper/categorias.py` con un
modelo de Machine Learning entrenado sobre los 14,589 PLs etiquetados a
mano por el equipo de Vali.

Stack:
- TF-IDF (word n-grams 1-2 + char n-grams 4-5) para representar el texto
- Logistic Regression multinomial como clasificador (rapido, interpretable,
  funciona bien en problemas de clasificacion de texto con dataset
  moderado y muchas clases)
- joblib para persistir el modelo (~2 MB)

Arquitectura:
  scraper/categorias.py  -> taxonomia (lista de categorias)
  clasificador/train.py  -> entrena modelo desde proyectos con tema_manual=1
  clasificador/predict.py -> infiere tema + confianza para un PL nuevo
  clasificador/reclassify.py -> revisa "Otros" y sugiere cambios
  clasificador/cli.py     -> train / evaluate / reclassify / predict

Aprendizaje continuo:
- Tabla `clasificacion_sugerencias` para tracking de cambios automaticos
  vs los aprobados/rechazados.
- Workflow re-entrena cuando hay correcciones nuevas (>= 50 labels
  cambiados desde el ultimo train), o manualmente con `clasificador.cli train`.
"""
