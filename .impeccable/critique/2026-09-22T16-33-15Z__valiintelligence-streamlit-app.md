---
target: corré un critique general de la app
total_score: 26
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "url:https://valiintelligence.streamlit.app/"
timestamp: 2026-09-22T16-33-15Z
slug: valiintelligence-streamlit-app
---
## Critique general — Vali Intelligence / Radar Legislativo

**Method:** dual-agent (Assessment A: revision de diseno, Assessment B: detector automatico + evidencia de navegador), corridos en paralelo, aislados entre si.

### Design Health Score (heuristicas de Nielsen)

| # | Heuristica | Score | Hallazgo clave |
|---|---|---|---|
| 1 | Visibilidad del estado del sistema | 3/4 | Buen feedback en vivo, pero "Nuevos hoy" es ambiguo |
| 2 | Match con el mundo real | 4/4 | Vocabulario legislativo real usado con precision |
| 3 | Control y libertad del usuario | 2/4 | "Descartar" no tiene confirmacion ni undo |
| 4 | Consistencia y estandares | 3/4 | Botones centralizados, pero la grilla de PLs no hereda el sistema |
| 5 | Prevencion de errores | 2/4 | Cero friccion en Descartar |
| 6 | Reconocimiento vs. recordar | 3/4 | Tooltips "?" inconsistentes |
| 7 | Flexibilidad y eficiencia | 2/4 | Sin paginacion, export ni bulk actions en 427 filas |
| 8 | Diseno estetico y minimalista | 3/4 | Noticias se satura con chips+metadata+KPIs a la vez |
| 9 | Recuperacion de errores | 3/4 | Mensajes de error accionables |
| 10 | Ayuda y documentacion | 1/4 | Sin onboarding, tooltips inconsistentes |
| **Total** | | **26/40** | **Aceptable** |

### Veredicto de especificidad de diseno
Split: el copy esta autorado para el dominio (vocabulario legislativo real y preciso); la capa visual se parte en dos - Inicio genuinamente disenado, pantallas de uso diario (grilla de PLs) son Streamlit stock con reskin, y la seleccion de celda vuelve al azul default. El detector confirma desde otro angulo: el hover del sidebar-nav anima padding-left (layout thrash, app.py:396-402), contradiciendo el propio docstring de ui_kit.py.

Detector: contraste bajo en #ff4b4b (rojo default Streamlit, no en la paleta, no ubicado en DOM estatico); cramped-padding descartado como falso positivo; "Created by nicosil02" es chrome de Streamlit Cloud, fuera de control. Nota: el detector no devolvio hallazgos en /peru-noticias y /alertas (ni mobile) por hidratacion lenta (~10-11s) excediendo su ventana de espera - no son paginas confirmadamente limpias.

### Lo que funciona
1. Vocabulario y estructura autenticos del dominio.
2. El rediseno "Mas filtros" de Noticias - mejor ejemplo de progressive disclosure de la app.
3. Copy de tranquilidad en momentos correctos (Alertas, Sugerencias de reclasificacion).

### Priority Issues

**[P0] "Nuevos hoy" mezcla PLs y noticias sin avisar** - mostro 210 vs "Presentados: 45" sin explicacion visible salvo tooltip hover. Fix: separar en dos tiles. Comando: /impeccable clarify

**[P1] Emoji de bandera fallan en Windows** - PE/EC no renderizan como bandera de color, sidebar no renderiza nada. Fix: icono SVG/PNG estatico. Comando: /impeccable harden

**[P1] Agenda PE sigue en 0 sesiones - bug conocido desde 09-17, sigue vivo** - visible ahora en KPIs de la pagina. No es un fix de diseno, requiere investigar el pipeline de datos.

**[P2] Tabla de PLs desperdicia altura de fila en celdas vacias** - titulos de ~6 lineas fuerzan la altura de toda la fila aunque Autor/Bancada/Comision esten vacios. Fix: truncar a 2 lineas + ellipsis. Comando: /impeccable distill

**[P2] Hover del sidebar anima padding-left (layout thrash)** - confirmado en app.py:396-402, contradice la politica propia del codigo. Fix: transform: translateX() en vez de padding-left. Comando: /impeccable optimize

**[P3] "Descartar" sin confirmacion ni undo** - un click, mismo peso visual que Marcar/Combinar, escribe inmediato a store persistente. Fix: patron toast-con-undo. Comando: /impeccable harden

**[P3] Seccion "Alertas" del Inicio rompe su propio patron de grilla** - 1 card + 2 columnas vacias. Fix: dar un segundo tile real o expandir a ancho completo. Comando: /impeccable layout

### Persona Red Flags
**Alex (power user):** tabla de 427 filas sin paginacion/export/bulk action, filas 3-4x mas altas de lo necesario; "Nuevos hoy" ambiguo.
**Sam (accesibilidad):** puntos de color sin leyenda de texto en Alertas; tooltips hover-only no expuestos a teclado/lector de pantalla.
**Riley (stress-tester):** Peru 0 sesiones vs Ecuador 7/7 el mismo dia; posible session bleed entre pestanas del mismo login (no confirmado, vale la pena probar 2 paises en 2 pestanas).

### Minor Observations
- Footer expone "GITHUB.COM/NICOSIL02/BASE_LEGISLATIVA" a cualquier viewer.
- Tooltips "?" inconsistentes entre campos con jerga similar.
- Case-mismatch chip vs header en tema ("Coyuntura política" vs "COYUNTURA POLÍTICA").
- Link de PL no distingue visualmente destino externo vs accion interna.

### Questions to Consider
1. "Nuevos hoy" mezcla PLs y noticias - deliberado o drift no advertido?
2. El sistema de bandera nunca se probo en Windows real?
3. Descartar sin undo - como sabrias si ya perdio algo importante para un cliente?
