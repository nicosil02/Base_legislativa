# Prompt: alerta de WhatsApp (noticia / norma nueva / proyecto de ley)

Fuente: prompts de la compañera de Nicolas (`Noticias 2026.docx`, recibido 2026-09-11), más ajustes
confirmados contra ejemplos reales pegados por Nicolas el mismo día — ver `ejemplos_alertas.md`.

## Regla de oro (Nicolas, 2026-09-11)
No es solo contar que pasó X. **Antes de redactar, revisar `historial_alertas.md` del cliente** para ver
si hay algo previo relacionado (un anuncio anterior, una posición ya tomada, un antecedente) y tejerlo en
la alerta como valor agregado — ej.: si un ministro anuncia una reorganización, y ya habíamos reportado
antes que ese ministro venía insinuando esa intención, esa conexión ES la alerta, no un dato de relleno.

## Formato (confirmado con ejemplos reales — más completo que el prompt original)

```
<emoji país> <emoji tipo> <País>: <Título corto y directo>

¿Qué pasó?
<Una frase que resume el hecho de forma directa, simple, clara y profesional — para
profesionales del sector que NO conocen el país en profundidad>

Puntos a tener en cuenta
* <bullet 1 — contexto de lo informado, info relevante para entender el evento>
* <bullet 2 — más detalle + puntos de interés directo para la empresa/sector>
* <bullet 3 — reacciones de otros actores / posiciones relevantes (si no hay, más detalle/interés
  para la empresa)>
* <bullet 4, opcional — SOLO si hay una implicancia real: análisis de implicaciones para la
  discusión, priorizando el interés de la empresa, + cuándo ocurriría aproximadamente>

[Solo si es un proyecto de ley:]
Probabilidades de avance <Alta/Media/Baja o combinada, ej. "Media-baja">
<1-2 líneas justificando el pronóstico: mayorías, coaliciones, sensibilidad del tema, precedentes>

<link a la fuente oficial>
```

## Regla de profundidad (Nicolas, 2026-09-12, via comparacion directa con ejemplos reales)
No alcanza con resumir la nota fuente. Los ejemplos reales de la compañera de Nicolas meten contexto que
NO está en el artículo único (acuerdos previos, marco institucional, nombres de organismos/declaraciones
relacionadas) y agregan juicio informado sobre el actor/institución involucrado (ej. "el Parlamento Andino
históricamente ha tenido baja capacidad de acción") — eso es lo que hace que el bullet de análisis valga la
pena, no un resumen más largo de la misma nota. Antes de dar por buena una alerta: ¿hay algo que investigar
más allá de la única fuente? ¿hay algo que ya se sabe sobre cómo funciona esa institución/actor que cambie
cómo se debe leer la noticia?

## Regla de tono (Nicolas, 2026-09-12)
Tiene que sonar natural, como lo escribiría una persona, no como IA. **Evitar dos puntos (`:`) y guiones
largos/em-dash como conectores de idea** (ej. "sin decreto todavía — vale seguir su evolución") — son un
tic típico de redacción de IA. Conectar ideas con palabras normales ("aunque", "aunque todavía", aunque
sin embargo). Y el bullet 4 es *opcional de verdad*: si no hay una implicancia real y concreta, no forzarlo
— 3 bullets bien escritos es mejor que 4 con el último de relleno.

## Calibrado contra el chat.txt real del equipo (Nicolas + Alma, jun-sep 2026, ~2400 mensajes, 2026-09-12)
Nicolas compartió el export real del grupo de WhatsApp donde él y su colega Alma redactan y triage-an
las alertas antes de mandarlas a clientes. Esto ajusta/corrige varias reglas de arriba que eran solo
hipótesis a partir de 2-3 ejemplos:

- **Los bullets usan `*`, `•` o `-` indistintamente** — la misma persona los mezcla en el mismo mensaje.
  No hay una convención estricta de marcador, cualquiera de los tres sirve.
- **"Probabilidades de avance" (o "Posibilidades de avanzar"/"Probabilidad de avance"/"Posibilidad de
  avance" — la redacción exacta varía) casi siempre va como el ÚLTIMO bullet de la misma lista**, no como
  una sección aparte con su propio párrafo separado (la plantilla de arriba lo dibuja separado; en la
  práctica real casi nunca lo está).
- **El límite de 830 caracteres/150 palabras sigue siendo la intención real** (Nicolas, 2026-09-12) — no
  es que se haya abandonado. Pero cuando el tema amerita más por ser complejo, se permiten pasarse; no
  cortar contenido real solo para cumplir el conteo en un tema que de verdad lo requiere.
- **Patrón "designación/nombramiento"** (muy frecuente: alguien asume un cargo) tiene su propia forma:
  título con el nombre + cargo, "¿Qué pasó?" con el nombramiento en sí, y 2-4 bullets sobre qué hace ese
  despacho/cargo + trayectoria de la persona + qué anticipa ese perfil para la gestión (continuidad vs.
  cambio). No lleva "Probabilidades de avance" (no es un PL).
- **Proceso real confirmado por Nicolas (2026-09-12): para temas de Crop, se redacta UNA alerta dirigida a
  Syngenta o a Bayer Crop, y después se parafrasea para el otro** — no son dos redacciones independientes
  desde cero, es una base + una adaptación. Ojo: en el chat real, **Bayer aparece dividido en "Bayer Farma"
  y "Bayer Crop" como audiencias/canales distintos**, no un solo "Bayer" — el emparejamiento real es
  Crop+Syngenta juntos (agro) y Farma aparte (salud/farmacéutico). **Resuelto (Nicolas, 2026-09-12): NO
  separar en dos slugs.** Cuando el tema es transversal a ambas líneas (política nacional de gobierno,
  pedido de facultades legislativas, etc.) se manda UNA sola alerta a Bayer, no una por línea — que es
  justo lo que ya hace el sistema (`CATEGORIA_CLIENTES`/`TEMA_CLIENTES`: "Agricultura"→bayer+syngenta,
  "Salud"→bayer, lo transversal cae en "todos" que ya incluye a bayer una sola vez). Dividir en
  `bayer_farma`/`bayer_crop` rompería ese comportamiento transversal; se queda como un slug único `bayer`.
- **Las cuentas de cliente pueden ser específicas por país** — hay un incidente real registrado donde
  Diana corrigió a Alma porque "Google Perú es una cuenta aparte" de una alerta regional que ya se había
  mandado por el chat de Colombia: cubrir un país no exime de cubrir el mismo evento para la cuenta de
  otro país del mismo cliente.
- **La coyuntura política/diplomática general SÍ importa mucho a Google/Incode aunque no tenga ángulo
  sectorial obvio** — hay un incidente real donde el cliente (Irene) se molestó porque no se alertó la
  visita de Marco Rubio a Perú el mismo día que ocurrió ("si no me alertan, no me sirve el servicio").
  No esperar a que una noticia tenga un gancho regulatorio directo para considerarla relevante a estos
  clientes.

## Regla de destinatario (Nicolas, 2026-09-13)
Nunca escribir "Para Bayer, ..." / "Para Google, ..." (ni ninguna variante tipo "esto le importa a X
porque...") dentro del texto de la alerta. Ya se sabe para qué cliente es — cada cliente tiene su propio
canal/hilo — así que nombrarlo adentro es redundante y delata que es una plantilla genérica en vez de algo
escrito pensando en ese cliente puntual. El interés del cliente se transmite implícito en QUÉ se elige
contar y en el ángulo de los bullets, no diciéndolo explícito.

## Reglas de formato WhatsApp
- Negrita con asteriscos simples: `*¿Qué pasó?*`, `*Puntos a tener en cuenta*` (WhatsApp renderiza `*texto*`
  como negrita, no `**texto**` de Markdown normal).
- Cada bullet: ~1.5 líneas en pantalla de celular, máximo.
- **Toda la alerta debe caber en un screenshot de WhatsApp en formato celular: menos de 830 caracteres y
  150 palabras en total.**
- Emojis de tipo de alerta (van al inicio del título):
  - 🏛️ = Congreso / Asamblea (trámite legislativo)
  - 🎯 = Gobierno / Ejecutivo (decretos, anuncios, nombramientos)
  - 🚨 = urgente
  - 🗓️ = evento
- **Bandera del país (🇵🇪 / 🇪🇨) — regla confirmada por Nicolas (2026-09-11): SOLO para Google e Incode**
  (van bandera + emoji de ámbito). **Para el resto de clientes (Bayer, Syngenta) va únicamente el emoji de
  ámbito, sin bandera** — reciben sus alertas ya segmentadas por país/línea de negocio (grupos de WhatsApp
  separados), así que la bandera sería redundante.
- Cerrar siempre con el link a la fuente oficial (El Peruano, portal del Congreso/Asamblea, etc.).

## Prompt base para generar la alerta
> Resume esta noticia/nueva norma/nuevo proyecto de ley/proyecto normativo para una alerta formal de
> WhatsApp con el formato de arriba. Antes de escribir, revisa el historial de alertas de este cliente por
> si hay continuidad con algo reportado antes (una posición previa del actor, un anuncio anterior, un
> antecedente legislativo) y tejerlo en el bullet de análisis si aplica.
