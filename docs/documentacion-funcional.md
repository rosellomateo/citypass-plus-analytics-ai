# Documentación funcional — Análisis ejecutivo semanal con IA

- **Módulo:** `citypass-plus-analytics-ai`
- **Producto:** CityPass+ — plataforma de servicios ciudadanos
- **Versión del esquema de salida:** 3.0

---

## 1. Para qué existe este módulo

CityPass+ genera tableros analíticos con la actividad de los cinco dominios de la ciudad (reclamos,
emergencias, movilidad, espacios públicos y residuos). Los tableros muestran **números**: cuántos reclamos
hay, cómo se reparten por barrio, cuánto tarda cada estado.

El problema es que un número sin lectura no es información de gestión. Alguien tiene que mirar el tablero,
comparar contra las semanas anteriores, darse cuenta de qué cambió y escribirlo en un párrafo que un
funcionario pueda leer en un minuto. Esa tarea es semanal, repetitiva y se hace tarde o no se hace.

**Este módulo la automatiza.** Todos los lunes a la mañana lee las fotos semanales de cada dominio,
calcula qué pasó realmente en la semana y le pide a un modelo de lenguaje que escriba el resumen
ejecutivo. El resultado queda disponible para el tablero, con el mismo formato todas las semanas.

### Qué aporta

| Sin el módulo | Con el módulo |
|---|---|
| El tablero muestra el acumulado; hay que interpretarlo a mano | Cada lunes hay un resumen escrito de la semana cerrada |
| La comparación contra semanas anteriores se hace de memoria | La comparación es contra las últimas 8 semanas, con cifras |
| El análisis depende de que alguien tenga tiempo | Corre solo, y si un dominio falla los demás siguen |
| Cada persona escribe el resumen distinto | Formato fijo: párrafo, destacados, riesgos, recomendaciones |

---

## 2. Alcance

### Dominios cubiertos

Los cinco dominios de CityPass+, cada uno con su propio análisis y su propio archivo de salida:

| Dominio | Qué mide | Indicador principal |
|---|---|---|
| **Reclamos** | Reclamos de vecinos por barrio, categoría, prioridad y quién los clasificó | Reclamos nuevos por semana y horas hasta el estado actual |
| **Emergencias y seguridad** | Avisos de emergencia por prioridad y estado del operativo | Emergencias nuevas y minutos de respuesta (despacho y llegada) |
| **Movilidad urbana** | Viajes por fecha, estación de origen y franja de duración | Viajes nuevos y duración promedio |
| **Espacios públicos y cultura** | Reservas de espacios e inscripciones a eventos por recurso y zona | Reservas nuevas, confirmadas, canceladas y % de ocupación |
| **Gestión de residuos** | Alertas de contenedores por zona, tipo y nivel de llenado | Alertas nuevas, resueltas y horas hasta la recolección |

### Qué hace y qué no hace

**Hace:**
- Calcula, con precisión aritmética, cuántos hechos nuevos hubo en la semana en cada dominio.
- Compara esa semana contra las anteriores (8 por defecto).
- Escribe un resumen ejecutivo en lenguaje claro, con cifras concretas.
- Señala riesgos y propone acciones concretas para el área de gobierno.
- Acumula el historial: el tablero puede mostrar la evolución semana a semana.

**No hace:**
- No genera los datos: los toma de la capa gold, que produce el pipeline de datos.
- No reemplaza el tablero: lo complementa con la lectura de lo que el tablero muestra.
- No toma decisiones ni ejecuta acciones: recomienda.
- No analiza la semana en curso: siempre trabaja sobre la última semana **cerrada** (domingo a domingo).
- No muestra datos personales: trabaja sobre datos ya agregados, sin identificar vecinos ni casos.

---

## 3. Cómo funciona, en términos de negocio

```
     Domingo                      Lunes 07:00 (hora Argentina)
        │                                   │
        ▼                                   ▼
  El pipeline de datos            El módulo de análisis
  archiva la "foto" de       ──▶  1. lee las últimas 9 fotos de cada dominio
  cada dominio en la              2. resta foto contra foto: cuántos hechos
  capa gold                          nuevos hubo cada semana
                                   3. arma las tablas comparativas
                                   4. el modelo de lenguaje escribe el resumen
                                   5. lo agrega al historial del dominio
                                                │
                                                ▼
                                   El tablero muestra el resumen
                                   de la semana y su evolución
```

### El concepto clave: la foto es un acumulado, no la semana

Esto explica casi todo el diseño del módulo y conviene entenderlo.

La capa gold **no guarda la fecha de alta** de cada hecho: guarda, cada domingo, una foto de **todo lo que
existe desde el día cero**, agrupado por las dimensiones del dominio. La foto del domingo 20 de septiembre
de reclamos no tiene los reclamos de esa semana: tiene los 469 reclamos que existen desde que arrancó el
sistema.

Entonces, para saber cuántos reclamos entraron en la semana, hay que **restar la foto del domingo contra la
del domingo anterior**. Si la foto de esta semana tiene 469 y la anterior tenía 412, hubo **57 reclamos
nuevos**.

Dos consecuencias funcionales:

1. **Para analizar una semana hacen falta dos fotos.** Un dominio recién conectado, con una sola foto, no
   se puede analizar todavía: el módulo lo informa y sigue con los demás.
2. **El acumulado siempre sube.** Que "el total de reclamos creció" no es una noticia; la noticia es a qué
   ritmo entran (las altas) y cómo se reparte lo que está abierto. El resumen está escrito con esa regla.

### Por qué la cuenta la hace el sistema y no el modelo

Las restas entre decenas de filas las hace el código, no el modelo de lenguaje. Es una decisión deliberada:
sumar y restar tablas largas es justo lo que un modelo hace mal, y esas son las cifras que después aparecen
en el resumen que lee una autoridad. El modelo recibe las cifras ya calculadas y su trabajo es
**interpretarlas y redactarlas**, no computarlas.

---

## 4. Qué produce: el resumen ejecutivo

Cada semana, cada dominio produce una entrada con cuatro partes:

| Parte | Contenido |
|---|---|
| **Párrafo ejecutivo** | Un único párrafo de 120 a 180 palabras: cómo fue la semana frente al histórico |
| **Puntos destacados** | 2 a 5 ítems de una oración, con cifras |
| **Riesgos** | 1 a 5 ítems de una oración |
| **Recomendaciones** | 2 a 5 acciones concretas que un área de gobierno pueda ejecutar |

El formato es siempre el mismo: el tablero sabe qué esperar y la lectura semana a semana es comparable.

### Ejemplo (reclamos)

> **Párrafo ejecutivo:** La semana cerró con 57 reclamos nuevos, un 12% por encima de la semana anterior
> (51) y en línea con el promedio de las últimas ocho semanas (54). El crecimiento se concentra en Centro,
> que aportó 21 altas, casi todas de la categoría BACHES. El stock abierto llegó a 288 reclamos, y el
> tiempo promedio hasta el estado actual se mantiene en 34 horas […]
>
> **Puntos destacados:**
> - Centro aportó 21 de las 57 altas de la semana, el doble que cualquier otro barrio.
> - Los reclamos abiertos con prioridad ALTA pasaron de 40 a 47.
>
> **Riesgos:**
> - El stock abierto crece más rápido que la capacidad de cierre: 57 altas contra 38 cierres.
>
> **Recomendaciones:**
> - Reforzar la cuadrilla de bacheo en Centro durante la próxima semana.
> - Revisar los reclamos ALTA con más de 72 horas sin asignar.

### Reglas de redacción que respeta el resumen

Están escritas en las instrucciones que recibe el modelo y son parte del producto:

- **Toda cifra sale de las tablas.** No se inventan datos. Si el resumen propone una causa, la presenta
  como hipótesis a validar, no como un hecho.
- **El eje son las altas**, no el acumulado.
- **Los promedios son un nivel, no el resultado de la semana**: están calculados sobre todo el acumulado y
  arrastrados por casos viejos, así que se mueven despacio.
- **Con volúmenes chicos se usan valores absolutos**: con menos de ~20 casos en un grupo, los porcentajes
  exageran, y el resumen lo aclara.
- **`SIN_DATO` es un dato faltante**, no una categoría real (por ejemplo, un reclamo todavía sin clasificar).
- **Estilo**: español rioplatense neutro, directo, sin jerga técnica.

---

## 5. Reglas de negocio por dominio

Cada dominio tiene su propio vocabulario, y el módulo se lo explica al modelo para que no lea mal los datos.

### Reclamos
- Estados **abiertos**: RECIBIDO, EN_REVISION, ASIGNADO, EN_PROCESO.
- Estados **resueltos**: RESUELTO, CERRADO. **Descartado**: RECHAZADO (cierre sin resolución).
- `origenClasificacion` dice quién asignó la categoría: MODELO (clasificador automático), CIUDADANO
  (el vecino) u OPERADOR (personal del organismo). Los rechazos de reclamos clasificados por MODELO pueden
  indicar errores de clasificación automática, y el resumen lo mira.
- El tiempo promedio son **horas** desde el ingreso hasta el estado en el que está cada reclamo.

### Emergencias y seguridad
- Ciclo: PENDIENTE → VALIDADA → DESPACHADA → EN_CAMINO → EN_LUGAR → RESUELTA → CERRADA, con la rama
  DESCARTADA para los avisos que no se confirman.
- Dos tiempos, en **minutos**: hasta despachar el móvil y hasta llegar al lugar. En este dominio el tiempo
  de respuesta es el indicador que importa, más que el volumen.
- La prioridad es ALTA, MEDIA o BAJA (no existe CRITICA).

### Movilidad urbana
- Los viajes **en curso** (todavía sin evento de fin) no entran en la tabla hasta que terminan: aparecen
  recién en la foto siguiente.
- La duración se agrupa en franjas: <15min, 15-30min, 30-60min y >60min.
- A diferencia de los otros dominios, la fecha del viaje está en el grano, así que se puede leer la
  actividad día por día.

### Espacios públicos y cultura
- `ESPACIO` es la reserva de un lugar físico; `EVENTO` es una inscripción a una actividad.
- Confirmadas y canceladas son acumulados sobre el total de reservas de cada recurso: la diferencia entre
  el total y la suma de ambas son las que siguen pendientes.
- El % de ocupación solo aplica a los recursos con cupo máximo definido.

### Gestión de residuos
- Tipos de alerta: LLENO, FALLA_SENSOR, VOLCADO e INCENDIO.
- Una alerta se considera **resuelta** cuando llega la recolección correspondiente; el tiempo de
  resolución son las **horas** hasta esa recolección.
- El rango de nivel de llenado viene vacío en las alertas de FALLA_SENSOR, porque no hay lectura del sensor.

---

## 6. Operación

### Cuándo corre
Todos los **lunes a las 07:00 hora Argentina** (configurable). Analiza la semana ISO que cerró el domingo
anterior. Las semanas se nombran como `2026-W38`: la semana 38 de 2026, la que cerró ese domingo.

### Qué pasa si algo falla
- **Un dominio sin datos suficientes** (por ejemplo, con una sola foto) se saltea con un mensaje en el log
  y **no frena a los demás**. Un dominio recién conectado no puede dejar sin resumen a los otros cuatro.
- **Si falta la foto de una semana** (porque el pipeline no corrió ese domingo), el módulo lo detecta y
  avisa: las altas de la semana siguiente acumulan dos semanas y el resumen lo aclara en vez de presentar
  un pico inexistente.
- **Si una foto tiene menos registros que la anterior** (solo puede venir de un reproceso o un borrado),
  también queda avisado, y el resumen trata esas cifras con reserva.

### Rehacer una semana
Se puede volver a generar el análisis de una semana pasada (por ejemplo, después de corregir datos). La
entrada nueva **reemplaza** a la anterior en vez de duplicarse: el tablero siempre ve una sola entrada por
semana.

### Modo prueba sin IA
Existe un modo que hace todo el recorrido —lee las fotos, calcula las tablas, arma el mensaje— pero **no
llama al modelo**. Sirve para verificar la infraestructura y ver exactamente qué datos se le enviarían,
sin consumir el servicio de IA. Es el modo con el que se prueba el despliegue.

---

## 7. Quién consume la salida

El tablero de CityPass+ lee un archivo por dominio (`analisis/reclamos.json`, `analisis/movilidad.json`,
etc.). Cada archivo contiene **todas las semanas analizadas**, así que el tablero puede:

- mostrar el resumen de la semana corriente (la última entrada), o
- recorrer el historial para ver cómo evolucionó la lectura semana a semana.

Cada entrada incluye, además del texto, la **trazabilidad** del análisis: qué semanas se compararon, de qué
archivos salieron los datos, qué avisos hubo y las cifras principales. Eso permite auditar cualquier
afirmación del resumen contra los datos que la originaron.

---

## 8. Supuestos y limitaciones

| Supuesto / límite | Implicancia |
|---|---|
| La capa gold archiva una foto por dominio cada domingo | Si no corre, esa semana no se puede analizar por separado |
| Hacen falta al menos 2 fotos por dominio | La primera semana de un dominio nuevo no tiene resumen |
| El análisis es de la semana cerrada | No hay resumen "en vivo" de la semana en curso |
| El resumen lo escribe un modelo de lenguaje | Las cifras son exactas (las calcula el sistema), pero las causas que propone son hipótesis a validar |
| Los datos vienen ya agregados | El resumen no puede bajar al caso individual |
| Corre una vez por semana | Un cambio dentro de la semana se ve recién el lunes siguiente |

---

## 9. Glosario

| Término | Significado |
|---|---|
| **Capa gold** | Última capa del pipeline de datos: tablas agregadas, listas para consumo analítico |
| **Snapshot / foto** | Copia archivada de la tabla gold de un dominio al cierre de una semana |
| **Acumulado (stock)** | Todo lo que existe desde el día cero hasta ese domingo |
| **Altas (flujo)** | Hechos nuevos de la semana; se obtienen restando una foto contra la anterior |
| **Foto base** | La foto más vieja de la ventana: no se analiza, sirve para restar la primera semana |
| **Semana ISO** | Numeración estándar de semanas; `2026-W38` cierra el domingo de esa semana |
| **Caso de uso / dominio** | Cada uno de los cinco verticales de CityPass+ |
| **Resumen ejecutivo** | La salida: párrafo, puntos destacados, riesgos y recomendaciones |
| **Aviso** | Anomalía detectada en los datos que se informa al modelo y queda registrada |
