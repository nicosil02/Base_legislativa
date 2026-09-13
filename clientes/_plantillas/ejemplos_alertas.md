# Ejemplos reales de alertas (referencia gold-standard)

**Nota (2026-09-12):** además de los ejemplos puntuales de abajo, Nicolas compartió `clientes/chat.txt`,
el export completo del grupo de WhatsApp donde él y Alma redactan/triagean alertas reales (~2400
mensajes, jun-sep 2026). Es un corpus mucho más grande que estos ejemplos sueltos — ver el resumen de
patrones ya incorporado en `whatsapp_alerta.md` ("Calibrado contra el chat.txt real"). No se pegó el chat
completo acá por tamaño; consultarlo directamente si hace falta más contexto o más ejemplos de un tipo
específico (ej. designaciones, alertas regionales multi-país).

Pegados por Nicolas el 2026-09-11 para mostrar el formato real (más completo que el prompt crudo de
`whatsapp_alerta.md` — de acá se confirmó lo del emoji de país, el link al final, y la sección
"Probabilidades de avance" exclusiva de proyectos de ley).

## Ejemplo 1 — Perú, gobierno/norma (aplica a Bayer Farma)

```
🎯 Perú: El Gobierno declara en reorganización el Ministerio de Salud

¿Qué pasó? Mediante Decreto Supremo, el Ejecutivo declaró en reorganización al Ministerio de Salud
(Minsa) por un plazo de 90 días calendario, con el fin de evaluar su situación administrativa,
organizacional y de gestión, y proponer reformas.

Puntos a tener en cuenta
* El proceso contempla dos etapas. A los 60 días se presentará un informe de diagnóstico y, a los 90
  días, las medidas de reforma y una nueva estructura orgánica, con el fin de corregir duplicidades y
  fortalecer la rectoría del sector.
* El ministro Luis Dyer ha anunciado que la medida busca impulsar la transformación digital del sector
  y enfrentar el desabastecimiento de medicamentos, uno de los principales problemas del sistema de
  salud.
* La reorganización abarca las competencias del Minsa en productos farmacéuticos y podría derivar en
  cambios en la DIGEMID, en línea con la estrategia ya anunciada por el ministro para agilizar y
  digitalizar los procesos regulatorios y reducir los tiempos de evaluación y autorización de
  medicamentos.

https://busquedas.elperuano.pe/dispositivo/NL/2552411-1
```
**Por qué funciona:** el 3er bullet no es relleno — conecta el anuncio con algo *ya sabido/anunciado
antes* por el mismo ministro (su intención de digitalizar/agilizar DIGEMID). Esa costura hacia atrás es
justo la "regla de oro" que pidió Nicolas.

## Ejemplo 2 — Perú, Congreso/PL (aplica a Bayer Crop + Syngenta)

```
🏛️ Perú: Proyecto de ley propone moratoria de dos años a la importación de arroz

¿Qué pasó? El diputado Olver Peña de Juntos por el Perú (oposición / izquierda) presentó una
iniciativa de ley que propone suspender por dos años la importación de arroz para priorizar la
producción nacional.

Puntos a tener en cuenta
* La iniciativa legislativa señala responder al estancamiento económico del sector arrocero interno.
* El proyecto suspende la importación del producto por un plazo de dos años para proteger el mercado
  interno frente a compras externas que en 2024 sumaron 144,398 toneladas, procedentes principalmente
  de Uruguay, Brasil y Paraguay.
* En el periodo parlamentario previo se presentaron iniciativas similares sin avances importantes.
  Respondía a un pedido del sector arrocero.
* De aprobarse, una eventual suspensión de importaciones podría incrementar la demanda interna de
  insumos fitosanitarios por parte de los productores locales.

Probabilidades de avance Media-baja. Aunque la oposición cuenta con mayoría en el Pleno y en la
Comisión de Desarrollo Agrario, es probable una resistencia dentro de los sectores de centro
favorables al libre mercado (que forman parte de la coalición opositora). La suspensión de
importaciones por dos años es una medida sensible que podría generar cuestionamientos.

https://wb2server.congreso.gob.pe/spley-portal/#/diputados/expediente/2026/130
```
**Nota técnica:** el link usa la ruta `#/diputados/expediente/...` — ya bajo el Congreso bicameral. Buena
pista real de cómo luce una URL de PL de origen en Cámara de Diputados post-reforma.
**Por qué funciona:** el 4to bullet conecta con el interés directo de Syngenta/Bayer Crop (insumos
fitosanitarios) en vez de quedarse en el dato político puro, y el pronóstico está justificado con la
composición real de la coalición, no es un "media" tirado al aire.

## Ejemplo 3 — Ecuador, Asamblea/PL (aplica a Incode)

```
🇪🇨 🏛️ Ecuador: Continúa avance del Proyecto de Ley de Cédula Digital

¿Qué pasó? La Comisión de Justicia recibió criterios técnicos de expertos en derecho digital dentro
del tratamiento del proyecto de ley que equipara la validez de la cédula digital con la física.

Puntos a tener en cuenta
* La propuesta busca obligar a entidades públicas y privadas a aceptar la cédula digital, sancionando
  su rechazo injustificado con multas. Exige al Estado implementar protocolos de interoperabilidad
  para la verificación electrónica de identidad.
* La comisión recibió la opinión de Andrés Terán y Pablo Vargas, especialistas en Derecho Digital.
* Los expertos sugirieron precisar la definición técnica del documento digital, definir causales
  excepcionales de rechazo por protección de datos y evaluar la aplicabilidad del régimen sancionador
  al sector privado.
* Si avanza, podría facilitar la adopción de mecanismos de autenticación digital en servicios públicos
  y privados; los efectos concretos dependerán del texto aprobado y su eventual reglamentación.

Posibilidades de avanzar Medias. A pesar de ser una propuesta de un asambleísta de Pachakutik
(proyecto indígena minoritario), el proyecto tiene respaldo de sectores del oficialismo. Su trámite
avanza con prioridad media y se encuentra en una etapa inicial de discusión.

https://www.asambleanacional.gob.ec/es/node/118953
```
**Nota:** acá usan "Posibilidades de avanzar" (no "Probabilidades de avance" como en el ejemplo 2) — mismo
concepto, redacción no 100% estandarizada entre alertas. Al generar, usar cualquiera de las dos
consistentemente, o preguntar a Nicolas cuál prefiere fijar como estándar.

## Ejemplo 4 — Perú, gobierno/viaje oficial (pegado por Nicolas, 2026-09-12)

```
Perú: Viaje de la Presidenta a la 81.ª Asamblea General de la ONU y agenda en EE. UU.

¿Qué pasó? El Poder Ejecutivo presentó la solicitud al Senado para autorizar el viaje de la Presidenta a
Nueva York (21 al 25 de septiembre) para participar en la Asamblea General de la ONU y reuniones con el
sector privado estadounidense, sin precisar aún los ministros acompañantes.

Puntos a tener en cuenta:
* En la agenda destacan los encuentros empresariales como el desayuno en Americas Society / Council of
  the Americas, el diálogo con la CAF y la reunión con el Atlantic Council para discutir la agenda
  económica del Gobierno.
* No se especifican aún los ministros acompañantes; no obstante, la agenda de la Presidenta prevé
  espacios de diálogo directo con líderes inversionistas y representantes de la economía global.
* El Pleno del Senado deberá votar si autoriza dicho viaje. Aún no se ha convocado la citación para su
  discusión.

https://wb2server.congreso.gob.pe/spley-portal/#/senado/expediente/2026/8
```
**Por qué funciona:** nombra las organizaciones concretas de cada reunión (Americas Society/Council of the
Americas, CAF, Atlantic Council) en vez de decir genéricamente "reuniones con el sector privado" — ese
nivel de detalle nominal es lo que separa una alerta útil de un resumen vago. Cierra con el paso procesal
real pendiente (voto del Senado), no con una especulación.

## Ejemplo 5 — Perú, Farma/Crop, MISMA noticia que el ejemplo del bot (comparación directa, 2026-09-12)

```
Parlamento Andino impulsa compra conjunta de medicamentos

¿Qué pasó? La vicepresidenta del Parlamento Andino por Perú, Maali Del Pomar, coordinó con el Organismo
Andino de Salud-Conhu (ORAS-Conhu) una propuesta para avanzar hacia la compra y negociación conjunta de
medicamentos entre países de la región.

Puntos a tener en cuenta
* La propuesta busca aprovechar la escala regional para fortalecer el poder de negociación frente a
  proveedores, mejorar condiciones de adquisición y reducir costos.
* La iniciativa se alinea con la Declaración de Lima 2026 de los ministros de Salud del ORAS-Conhu (forman
  parte Bolivia, Chile, Colombia, Ecuador, Perú y Venezuela).
* Maali Del Pomar y el presidente del ORAS-Conhu acordaron continuar evaluando mecanismos para articular
  la propuesta con las acciones que ya viene desarrollando el organismo de salud.
* De avanzar, podría generar a mediano plazo un mecanismo regional de negociación o adquisición conjunta;
  aún no existe una decisión de implementación ni un cronograma definido. No obstante, el Parlamento
  Andino históricamente ha tenido baja capacidad de acción.

https://andina.pe/agencia/noticia-parlamento-andino-coordina-propuesta-para-compra-conjunta-medicamentos-la-region-1091166.aspx
```
**Por qué importa este ejemplo específicamente:** el bot (Claude, esta sesión, 2026-09-12) redactó una
alerta sobre esta MISMA noticia usando solo el artículo de Andina como fuente — quedó correcta pero más
delgada. Esta versión real mete la Declaración de Lima 2026 y la lista de países del ORAS-Conhu, que NO
están en el artículo de Andina (investigación/conocimiento adicional), y cierra con un juicio informado
sobre la baja capacidad de ejecución histórica del Parlamento Andino — eso es lo que la regla de
profundidad de arriba pide replicar.
