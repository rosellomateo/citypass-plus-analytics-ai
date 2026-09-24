# Documentación técnica — `citypass-plus-analytics-ai`

Análisis ejecutivo semanal de los dominios de CityPass+ con un modelo de lenguaje, sobre la capa gold.

> Versión corta de este documento: [`resumen-tecnico.md`](resumen-tecnico.md).
> Visión de negocio: [`documentacion-funcional.md`](documentacion-funcional.md).

---

## Índice

1. [Panorama](#1-panorama)
2. [Stack y dependencias](#2-stack-y-dependencias)
3. [Estructura del repositorio](#3-estructura-del-repositorio)
4. [Flujo de ejecución](#4-flujo-de-ejecución)
5. [Modelo de datos](#5-modelo-de-datos)
6. [Módulo por módulo](#6-módulo-por-módulo)
7. [Configuración](#7-configuración)
8. [Ingeniería de prompts](#8-ingeniería-de-prompts)
9. [Integración con el LLM](#9-integración-con-el-llm)
10. [Persistencia y concurrencia](#10-persistencia-y-concurrencia)
11. [Manejo de errores](#11-manejo-de-errores)
12. [Extensibilidad: agregar un dominio](#12-extensibilidad-agregar-un-dominio)
13. [Testing y CI](#13-testing-y-ci)
14. [Despliegue](#14-despliegue)
15. [Seguridad](#15-seguridad)
16. [Rendimiento y costos](#16-rendimiento-y-costos)
17. [Runbook](#17-runbook)
18. [Limitaciones conocidas](#18-limitaciones-conocidas)

---

## 1. Panorama

### Qué es

Una **Azure Function en Python 3.11** (modelo de programación v2, plan Flex Consumption) con un único
**timer trigger** semanal. Por cada dominio configurado: lee los snapshots semanales de la capa gold en
Blob Storage, calcula las tablas comparativas, se las manda a un LLM con salida estructurada y acumula el
resultado en un JSON por dominio.

```
Timer (lunes 10:00 UTC)
        │
        ▼
gold/<dominio>/<base>_<WW>_<YYYY>.parquet   (una foto acumulada por semana)
        │
        ▼
  casos.py      qué dimensiones, qué métrica y qué estados tiene el dominio
  datos.py      descubre y fecha los snapshots, arma la ventana
  metricas.py   altas = foto − foto anterior; stock por estado; totales
        │  3 o 4 tablas en CSV
        ▼
  prompts.py    system prompt por dominio + mensaje con las tablas
  llm_*.py      LLM con structured outputs (Pydantic)
        │
        ▼
  pipeline.py   entrada de la semana + metadata
  blob_io.py    escritura con ETag
        ▼
analisis/<caso>.json   (un archivo por dominio, con todas las semanas)
```

### Las cuatro decisiones de diseño que explican el código

**1. La aritmética la hace el código, no el modelo.**
La capa gold entrega *stock* (acumulado desde el día cero), no *flujo* (lo que entró esta semana). El flujo
sale de restar fotos consecutivas. Esa resta la hace `metricas.py`: restar decenas de filas a ojo es
exactamente lo que un LLM hace mal, y son las cifras que terminan en el resumen que lee una autoridad. El
modelo recibe las cifras ya calculadas e interpreta.

**2. El código es genérico; lo que cambia por dominio es data.**
`casos.py` es un registro declarativo: cada dominio es un `CasoDeUso` con su prefijo, su métrica, sus
dimensiones, sus estados y su glosario. `datos.py`, `metricas.py`, `prompts.py` y `pipeline.py` no
conocen ningún dominio en particular. Sumar un dominio es agregar una entrada al diccionario `CASOS`.

**3. La salida del modelo es estructurada, no texto libre.**
`esquema.py` define un modelo Pydantic (`ResumenEjecutivo`) que se le pasa al proveedor como
*structured output*. El tablero recibe siempre los mismos cuatro campos; no hay parseo de texto ni
heurísticas de formato.

**4. Un dominio roto no frena a los demás.**
El timer envuelve cada dominio en su propio `try/except`. Un dominio recién conectado (con un solo
snapshot) falla con un mensaje explícito y la corrida sigue.

### Por qué solo se leen los snapshots semanales

Cada capa gold escribe dos cosas en el mismo prefijo:

- `<base>_<WW>_<YYYY>.parquet` — la copia archivada del domingo, **inmutable**.
- `<base>.parquet` — la misma foto pero **mutable**: se pisa todos los días.

El módulo **ignora la mutable**. Si entrara, duplicaría la última semana o metería una semana a medio
terminar en el medio de la serie. El filtro está en `datos.es_snapshot()` y se aplica en la propia
consulta al container.

---

## 2. Stack y dependencias

| Componente | Tecnología | Nota |
|---|---|---|
| Runtime | Python 3.11 | La misma versión en local, en CI y en Azure |
| Hosting | Azure Functions, modelo v2, Flex Consumption | Una ejecución semanal entra en el nivel gratuito |
| Trigger | Timer (CRON de 6 campos, UTC) | `SCHEDULE` como App Setting |
| Almacenamiento | Azure Blob Storage | Entrada: container `gold`. Salida: container `analisis` |
| Formato de entrada | Parquet | Leído con `pandas` + `pyarrow` |
| Formato de salida | JSON (UTF-8, indentado) | Consumido por el tablero |
| LLM (default) | Azure OpenAI, deployment `gpt-5-mini` | `reasoning_effort="medium"` |
| LLM (alternativo) | Anthropic, Claude Opus 5 | `thinking={"type": "adaptive"}` |
| Validación de salida | Pydantic v2 | Structured outputs en ambos proveedores |

`requirements.txt` (producción):

```
azure-functions          azure-identity          azure-storage-blob>=12.20
anthropic>=1.5,<2        openai>=1.99
pandas>=2.2              pyarrow>=15             pydantic>=2.7
```

`requirements-dev.txt` (solo para tests, excluido del deploy por `.funcignore`): `pytest`, `pytest-cov`.

---

## 3. Estructura del repositorio

```
citypass-plus-analytics-ai/
├── function_app.py                  Timer trigger y orquestación por dominio
├── host.json                        Configuración del host de Functions
├── requirements.txt                 Dependencias de producción
├── requirements-dev.txt             Dependencias de test
├── pytest.ini                       Configuración de pytest (pythonpath, cobertura)
├── local.settings.json.example      Plantilla de configuración local
├── .funcignore                      Qué NO se sube a la Function App (tests, CI, venv)
├── analisis_semanal/
│   ├── config.py                    Settings desde variables de entorno
│   ├── casos.py                     Registro declarativo de los 5 dominios
│   ├── datos.py                     Snapshots, normalización y ventana
│   ├── metricas.py                  Las tablas que recibe el LLM
│   ├── prompts.py                   System prompt por dominio + mensaje
│   ├── esquema.py                   Esquema Pydantic de la respuesta
│   ├── llm_azure_openai.py          Proveedor Azure OpenAI
│   ├── llm.py                       Proveedor Anthropic
│   ├── pipeline.py                  Orquestación: ventana → tablas → LLM → entrada
│   └── blob_io.py                   Blob Storage: lectura de gold y escritura con ETag
├── tests/                           109 tests (ver sección 13)
├── docs/                            Esta documentación
└── .github/workflows/tests.yml      CI: tests + 60% de cobertura mínima
```

**Dependencias entre módulos** (sin ciclos):

```
function_app → pipeline → datos ─┐
             → blob_io → datos ──┼→ casos
             → casos            ─┘
             → config

pipeline → metricas → datos → casos
         → prompts  → casos
         → llm / llm_azure_openai → esquema, config
```

---

## 4. Flujo de ejecución

### 4.1 Disparo

```python
@app.timer_trigger(schedule="%SCHEDULE%", arg_name="timer",
                   run_on_startup=False, use_monitor=True)
def analisis_semanal(timer: func.TimerRequest) -> None:
```

`%SCHEDULE%` se resuelve contra el App Setting `SCHEDULE` (CRON de 6 campos en UTC). Valor sugerido:
`0 0 10 * * 1` = lunes 10:00 UTC = 07:00 ART. `run_on_startup=False` evita corridas accidentales en cada
reinicio del host; `use_monitor=True` hace que Functions recupere una ejecución perdida.

Si la ejecución viene atrasada (`timer.past_due`), queda un warning en el log.

### 4.2 Por cada dominio

```python
settings = Settings.desde_entorno()
cliente  = blob_io.crear_cliente(settings)

for nombre in settings.casos:
    try:
        logging.info(analizar_caso(cliente, nombre, settings))
    except Exception as error:
        fallados.append(nombre)
        logging.error("[%s] no se pudo analizar: %s", nombre, error)
```

`analizar_caso()` hace seis cosas, en este orden:

| # | Paso | Módulo |
|---|---|---|
| 1 | Resolver el `CasoDeUso` por nombre | `casos.obtener()` |
| 2 | Listar y descargar los snapshots del prefijo del dominio | `blob_io.leer_snapshots()` |
| 3 | Seleccionar la ventana, calcular tablas y llamar al LLM | `pipeline.ejecutar()` |
| 4 | Leer el historial actual y su ETag | `blob_io.leer_json()` |
| 5 | Agregar la semana al historial (reemplazando si ya estaba) | `pipeline.acumular()` |
| 6 | Escribir el historial con la condición del ETag | `blob_io.escribir_json()` |

Los pasos 4 a 6 ocurren en la misma corrida y a propósito lo más juntos posible: el ETag leído en el paso 4
es la condición de escritura del paso 6.

### 4.3 Detalle de `pipeline.ejecutar()`

```
snapshots (lista)
   │
   ├─ datos.seleccionar_ventana(semana_objetivo, semanas_historia)  → Ventana
   │
   ├─ metricas.resumen_tablas(ventana)  → {totales, altas, altas_detalle, [estado]}
   │
   ├─ _avisos(ventana)                  → saltos de semana + altas negativas
   │
   ├─ prompts.mensaje_usuario(tablas en CSV, semana, previas, avisos)
   │
   ├─ si USAR_LLM=false → devuelve la entrada con `entrada_llm` (el mensaje) y corta
   │
   ├─ import dinámico del proveedor según LLM_PROVIDER
   ├─ generar_resumen(mensaje, settings, prompts.system_prompt(caso))
   │
   └─ entrada = {semana, generado_en, resumen, metadata{...}}
```

El import del proveedor es **dentro de la función**, no en el encabezado del módulo: así el modo sin LLM no
necesita que el SDK del proveedor esté configurado, y un `LLM_PROVIDER` inválido falla antes de cualquier
llamada de red.

---

## 5. Modelo de datos

### 5.1 Entrada: la capa gold

Un blob Parquet por dominio y semana, bajo el prefijo del dominio dentro del container `gold`:

```
gold/Reclamos/reclamos_resumen_38_2026.parquet
gold/Emergencias y Seguridad/emergencias_resumen_38_2026.parquet
gold/Movilidad Urbana/viajes_resumen_38_2026.parquet
gold/Espacios Publicos y Cultura/reservas_resumen_38_2026.parquet
gold/Gestion de Residuos Inteligente/alertas_resumen_38_2026.parquet
```

El patrón que reconoce el módulo es `<base_archivo>_<WW>_<YYYY>.parquet`, case-insensitive, con 1 o 2
dígitos de semana. Todo lo demás en ese prefijo se ignora.

Columnas esperadas por dominio:

| Dominio | Métrica | Dimensiones | Estado | Promedios (peso) | Contadores |
|---|---|---|---|---|---|
| reclamos | `row_count` | barrio, categoria, prioridad, origenClasificacion | `estado_actual` | `tiempo_prom_hasta_estado_actual` (`row_count`) | — |
| emergencias | `cantidadEmergencias` | prioridad | `estado_actual` | `tiempoPromRespuestaDespacho`, `tiempoPromRespuestaLugar` (`cantidadEmergencias`) | — |
| movilidad | `cantidadViajes` | fechaInicio, estacionInicio, duracionViaje | — | `promDuracion` (`cantidadViajes`) | `duracionTotalViajes` |
| espacios | `cantidadTotal` | recursoId, tipoReserva, categoria, zona | — | `pctOcupacion` (`cantidadTotal`) | `cantidadConfirmadas`, `cantidadCanceladas`, `inscriptos` |
| residuos | `cantidadAlertas` | zona, tipoAlerta, prioridad, rangoNivelLlenado | — | `tiempoPromResolucion` (`cantidadResueltas`) | `cantidadResueltas` |

Columna opcional `fecha_snapshot`: si está, se usa como fecha de corte (y como fallback para fechar la
semana si el nombre del blob no la trae).

### 5.2 `Snapshot`

```python
@dataclass(frozen=True)
class Snapshot:
    caso: CasoDeUso
    anio: int
    semana: int
    corte: date | None      # de la columna fecha_snapshot, si existe
    ruta: str               # "<container>/<blob>" — queda en metadata.fuentes
    datos: pd.DataFrame     # ya normalizado
```

Propiedades derivadas: `etiqueta` (`"2026-W38"`), `orden` (`(anio, semana)`, la clave de ordenamiento) y
`total` (suma de la métrica).

**Normalización** (`datos.normalizar`), en este orden:

1. Verifica que estén todas las columnas requeridas (dimensiones + estado + métrica); si falta alguna,
   `ValueError` con la lista.
2. Convierte cada dimensión a `string`, reemplaza nulos por `"SIN_DATO"` y castea a `str`.
   Un nulo es un dato real (algo todavía sin clasificar): si quedara como `NaN`, el `groupby` lo
   descartaría y las restas entre fotos no cerrarían.
3. Convierte la métrica a `int64` (nulos a 0).
4. Convierte promedios y contadores a numérico con `errors="coerce"` (los ausentes quedan nulos).
5. Devuelve las columnas en orden canónico: dimensiones, estado, métrica, promedios, contadores.

### 5.3 `Ventana`

Serie de snapshots consecutivos `[base, ..., actual]`.

```python
ventana.base      # la foto más vieja: NO se analiza, es el sustraendo de la primera semana
ventana.actual    # la semana que se analiza
ventana.previos   # las intermedias
ventana.semanas   # etiquetas de las semanas analizadas (sin la base)
ventana.saltos()  # pares consecutivos separados por más de una semana
```

`seleccionar_ventana(snapshots, semana_objetivo, semanas_historia)`:

1. Ordena por `(anio, semana)` y rechaza semanas duplicadas.
2. Si hay `SEMANA_OBJETIVO`, corta la serie ahí (y falla listando las disponibles si no existe).
3. Se queda con las últimas `semanas_historia + 1` fotos. **El +1 es la base**: para analizar N semanas
   hacen falta N+1 fotos.
4. Si quedan menos de 2, `ValueError` explícito.

`saltos()` detecta domingos faltantes con dos criterios: si ambos snapshots tienen `corte`, más de 8 días
entre fotos; si no, diferencia de semana distinta de 1 dentro del mismo año.

### 5.4 Las tablas que recibe el modelo

`metricas.resumen_tablas(ventana)` devuelve 3 o 4 DataFrames, que se serializan a CSV.

**`totales`** — una fila por semana de la ventana (incluida la base):

| Columna | Contenido |
|---|---|
| `semana` | `2026-W38` |
| `altas_semana` | Altas de esa semana; **nulo en la fila base** |
| `acumulado_total` | Suma de la métrica al cierre |
| `abiertos` / `cerrados` / `descartados` | Solo si el dominio tiene columna de estado |
| contadores del dominio | `cantidadResueltas`, `inscriptos`, etc. |
| promedios del dominio | Ponderados sobre todo el acumulado |

**`altas`** — formato largo `semana × dimension × valor × altas`. Son las **marginales**: cada dimensión
abierta de a una por vez. Es deliberado: con decenas de altas repartidas en 4 dimensiones, casi todas las
combinaciones del cruce completo valen 1 y esas filas gastan tokens sin decir nada.

**`altas_detalle`** — el cruce completo de dimensiones, **solo de la semana analizada** y quedándose con
las `top` combinaciones más grandes (20 por defecto).

**`estado`** — stock por estado al cierre de cada semana, cruzado con `prioridad` cuando el dominio la
tiene entre sus dimensiones. Solo para dominios con `columna_estado` (reclamos y emergencias).

### 5.5 Cálculo de altas

```python
delta = acumulado_por_dimension(actual) − acumulado_por_dimension(previo)
```

El agrupamiento es por las **dimensiones estables**, explícitamente **sin la columna de estado**. Las
dimensiones de un hecho no cambian después del alta (un reclamo no cambia de barrio), así que la resta
cuenta hechos nuevos. Si se restara incluyendo el estado, el resultado sería el neto de cada bucket
—negativo cuando un reclamo pasa de ASIGNADO a CERRADO— y eso no es un alta.

Ejemplo verificado en los tests:

| | W37 | W38 | delta |
|---|---|---|---|
| Centro/BACHES/ALTA/MODELO — RECIBIDO | 10 | 8 | |
| Centro/BACHES/ALTA/MODELO — RESUELTO | 5 | 9 | |
| **Centro/BACHES/ALTA/MODELO (sin estado)** | **15** | **17** | **+2** |
| Norte/LUMINARIA/BAJA/CIUDADANO | 4 | 6 | +2 |
| Sur/RESIDUOS/MEDIA/OPERADOR | — | 3 | +3 |
| **Total** | **19** | **26** | **+7** |

Los 2 reclamos que pasaron de RECIBIDO a RESUELTO no aparecen como altas: la resta sin estado los absorbe.

### 5.6 Promedios ponderados

Los promedios de gold son **por combinación**, así que no se pueden promediar sin peso. `_agregar()`
reconstruye numerador y denominador:

```python
_num = (promedio × peso).fillna(0)
_den = peso.where(promedio.notna(), 0)     # las filas sin dato NO cuentan como 0
promedio_agregado = (Σ _num / Σ _den).where(Σ _den > 0).round(1)
```

La segunda línea es la importante: una alerta de FALLA_SENSOR no tiene tiempo de resolución, y
promediarla como 0 hundiría el indicador. Queda fuera del denominador.

### 5.7 Salida: `analisis/<caso>.json`

```jsonc
{
  "caso_de_uso": "reclamos",
  "version_esquema": "3.0",
  "actualizado_en": "2026-09-21T10:00:12+00:00",
  "ultima_semana": "2026-W38",
  "semanas": ["2026-W37", "2026-W38"],
  "analisis": [
    {
      "semana": "2026-W38",
      "generado_en": "2026-09-21T10:00:12+00:00",
      "resumen": {
        "parrafo_ejecutivo": "…",
        "puntos_destacados": ["…"],
        "riesgos": ["…"],
        "recomendaciones": ["…"]
      },
      "metadata": {
        "version_esquema": "3.0",
        "caso_de_uso": "reclamos",
        "semana_actual": "2026-W38",
        "semanas_comparadas": ["2026-W32", "…", "2026-W38"],
        "snapshot_base": "2026-W31",
        "fuentes": ["gold/Reclamos/reclamos_resumen_31_2026.parquet", "…"],
        "corte": "2026-09-20",
        "avisos": [],
        "cifras": {"altas_semana": 57, "acumulado_total": 469,
                   "abiertos": 288, "cerrados": 170, "descartados": 11},
        "filas_enviadas": 124,
        "llm": {"proveedor": "azure_openai", "deployment": "gpt-5-mini",
                "modelo_respuesta": "…", "request_id": "…",
                "finish_reason": "stop", "input_tokens": 9012, "output_tokens": 2634}
      }
    }
  ]
}
```

`metadata` es la trazabilidad: permite auditar cualquier afirmación del resumen contra los archivos y las
cifras que la originaron, y `metadata.llm` deja el consumo de cada corrida para control de costos.

En **modo sin LLM** (`USAR_LLM=false`), `resumen` queda en `null` y la entrada incluye `entrada_llm` con el
mensaje completo que se le habría enviado al modelo.

---

## 6. Módulo por módulo

### `config.py`

Un dataclass `Settings` congelado, con un único constructor `desde_entorno()`. Reglas:

- `_env()` trata una variable vacía o en blanco como ausente (un App Setting vacío usa el default).
- `_lista()` convierte `CASOS`: `"todos"` o `"*"` → los cinco; `"Reclamos, MOVILIDAD"` → normalizado a
  minúsculas y sin espacios.
- `USAR_LLM` es falso con `false`, `0` o `no` (case-insensitive); cualquier otra cosa es verdadero.
- `LLM_PROVIDER` se normaliza a minúsculas.

Que sea inmutable importa: `Settings` se pasa por parámetro a todo el pipeline en vez de leer el entorno
desde adentro, lo que hace los módulos testeables sin tocar `os.environ`.

### `casos.py`

Registro declarativo. `CasoDeUso` es un dataclass congelado:

```python
nombre, prefijo, base_archivo, metrica, etiqueta_metrica,
dimensiones, columna_estado, estados_abiertos, estados_cerrados, estados_descartados,
promedios: dict[columna, columna_peso], contadores: list[str], glosario: str
```

`dimensiones_todas` agrega la columna de estado cuando existe. `obtener(nombre)` normaliza y falla con la
lista de nombres conocidos. **Ningún otro módulo conoce un dominio por nombre.**

El `glosario` es texto que se inyecta en el system prompt: explica qué es cada fila, qué significan los
estados y qué unidades tienen los tiempos. Es la pieza que evita que el modelo lea mal un dominio.

### `datos.py`

Descubrimiento y forma de los datos. API:

| Función | Qué hace |
|---|---|
| `patron(caso)` / `semana_de_nombre()` / `es_snapshot()` | Reconocen `<base>_<WW>_<YYYY>.parquet` |
| `parsear_etiqueta("2026-W38")` | Formato de `SEMANA_OBJETIVO` |
| `normalizar(caso, df)` | Tipos consistentes y nulos explícitos (sección 5.2) |
| `construir_snapshot(caso, ruta, df)` | Fecha por nombre; si no, por `fecha_snapshot`; si no, error |
| `seleccionar_ventana(...)` | Ordena, valida y recorta (sección 5.3) |

### `metricas.py`

Todo el cálculo. Funciones públicas: `altas_detalladas`, `altas_por_dimension`, `altas_detalle_semana`,
`estado`, `totales`, `resumen_tablas`, `altas_negativas`, `a_csv`.

`altas_negativas()` cuenta filas con altas < 0. No debería haberlas: una foto con menos hechos que la
anterior solo puede venir de un reproceso, un borrado o un snapshot incompleto. En vez de taparlo, se
informa en la metadata **y** se le avisa al modelo.

### `prompts.py`

`system_prompt(caso)` arma cuatro bloques: encabezado (rol, de dónde salen los datos, qué es un stock),
descripción de las 3 o 4 tablas, glosario del dominio y reglas de lectura. `mensaje_usuario(...)` arma el
mensaje con la ventana, los avisos y las tablas en bloques CSV.

Cómo está compuesto y por qué cada pieza está donde está: **sección 8**. En resumen, las reglas de
lectura son defensas contra errores típicos de un LLM sobre datos acumulados:

- el acumulado siempre sube, no es noticia;
- los promedios son un nivel arrastrado por casos viejos, no el resultado de la semana;
- la primera fila de `totales` no tiene altas porque es la base;
- con menos de ~20 casos usar absolutos, no porcentajes;
- toda cifra sale de las tablas; las causas son hipótesis;
- `SIN_DATO` es un faltante, no una categoría.

### `esquema.py`

```python
class ResumenEjecutivo(BaseModel):
    parrafo_ejecutivo: str      # 120-180 palabras
    puntos_destacados: list[str]
    riesgos: list[str]
    recomendaciones: list[str]
```

Las descripciones de cada campo son parte del contrato: viajan en el JSON Schema que recibe el proveedor.

### `llm_azure_openai.py` y `llm.py`

Misma firma, mismo contrato:

```python
def generar_resumen(mensaje, settings, system_prompt, client=None) -> tuple[ResumenEjecutivo, dict]
```

El parámetro `client` opcional existe para inyectar un doble en los tests. Detalles en la sección 9.

### `pipeline.py`

`ejecutar()` (sección 4.3), `ruta_salida()` (`<OUTPUT_PREFIX><caso>.json`) y `acumular()`.

`acumular(historial, entrada, caso)` filtra la semana que se está escribiendo del historial anterior,
agrega la nueva, ordena por etiqueta de semana (lexicográfico = cronológico con el formato `YYYY-Www`) y
actualiza las claves de cabecera. Como parte de `dict(historial or {})`, **conserva claves extra** que
alguien haya agregado al archivo.

### `blob_io.py`

`crear_cliente()` elige entre connection string y `DefaultAzureCredential` sobre `STORAGE_ACCOUNT_URL`
(Managed Identity en Azure, `az login` en local). Si no hay ninguna de las dos, falla explícito.

`leer_snapshots()` lista el prefijo, filtra por `es_snapshot`, ordena por nombre, descarga y construye cada
`Snapshot`. Si no hay ninguno, `FileNotFoundError` con el patrón esperado.

`leer_json()` devuelve `(documento, etag)` o `(None, None)` si el blob no existe.
`escribir_json()` crea el container si hace falta y escribe con `ensure_ascii=False` e `indent=2`
(el JSON queda legible con acentos), content-type `application/json; charset=utf-8`, y la condición de
ETag de la sección 10.

### `function_app.py`

Registra el timer y contiene `analizar_caso()` (sección 4.2). Detalle: el override `INPUT_PREFIX` solo se
aplica **cuando hay un único caso configurado**; con varios, cada uno usa su propio prefijo. Es una
salvaguarda: apuntar los cinco dominios a la misma carpeta de prueba no tendría sentido.

También baja el logger de `azure` a WARNING: el SDK de Storage loguea cada request HTTP en INFO y llena el
log de la corrida.

---

## 7. Configuración

App Settings de la Function App (o `local.settings.json` en local, que no se versiona).

| Variable | Default | Descripción |
|---|---|---|
| `SCHEDULE` | — | CRON de 6 campos en UTC. `0 0 10 * * 1` = lunes 07:00 ART |
| `STORAGE_CONNECTION_STRING` | — | Connection string del storage de datos |
| `STORAGE_ACCOUNT_URL` | — | Alternativa con Managed Identity (`https://<cuenta>.blob.core.windows.net`) |
| `INPUT_CONTAINER` | `gold` | Container de entrada |
| `INPUT_PREFIX` | vacío | Override del prefijo; solo aplica con un único caso |
| `OUTPUT_CONTAINER` | `analisis` | Container de salida |
| `OUTPUT_PREFIX` | vacío | Prefijo dentro del container de salida |
| `CASOS` | `reclamos` | Lista separada por comas, o `todos` |
| `SEMANAS_HISTORIA` | `8` | Semanas analizadas; se leen 9 fotos (la base no se analiza) |
| `SEMANA_OBJETIVO` | vacío | `2026-W38` para rehacer una semana puntual |
| `USAR_LLM` | `true` | `false` = calcula todo pero no llama al modelo |
| `LLM_PROVIDER` | `azure_openai` | `azure_openai` o `anthropic` |
| `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` | — | Recurso de Azure OpenAI |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-5-mini` | Nombre del deployment |
| `AZURE_OPENAI_API_VERSION` | `2025-04-01-preview` | Versión de la API |
| `ANTHROPIC_API_KEY` | — | Solo con `LLM_PROVIDER=anthropic` (lo lee el SDK) |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Modelo de Anthropic |

Debe estar configurado `STORAGE_CONNECTION_STRING` **o** `STORAGE_ACCOUNT_URL`.

---

## 8. Ingeniería de prompts

El prompt es código: vive en `prompts.py` y `esquema.py`, se arma distinto para cada dominio y está
cubierto por tests. Esta sección explica cómo está compuesto y, sobre todo, **por qué cada pieza está
donde está**.

### 8.1 Estructura: qué es estable y qué cambia

| Pieza | Función | Contenido | Cambia cuando |
|---|---|---|---|
| **System prompt** | Cómo leer y cómo escribir | Rol, origen de los datos, contrato de las tablas, glosario del dominio, reglas de comparación, estilo | Cambia el dominio |
| **Mensaje de usuario** | Qué mirar esta semana | Semana analizada, semanas previas, avisos de la corrida, las 3 o 4 tablas en CSV | Cada semana |

La separación no es decorativa. **Todo lo que no depende de la corrida está en el system prompt**, así que
el prompt de un dominio es byte a byte el mismo todas las semanas: cualquier diferencia entre dos resúmenes
viene de los datos, no del pedido. Eso hace que el output sea comparable semana a semana y que un cambio de
comportamiento sea atribuible.

`system_prompt(caso)` concatena cuatro bloques:

| Bloque | Origen | Qué aporta |
|---|---|---|
| `ENCABEZADO` | Constante, con el nombre del dominio interpolado | Rol, audiencia y —clave— qué es una foto acumulada |
| `TABLAS` (+ `TABLA_ESTADO`) | Constante, condicional | El contrato del input: qué es cada tabla y qué significa cada columna |
| Glosario | **Data del `CasoDeUso`** | Qué es cada fila, qué significan los estados, qué unidad tienen los tiempos |
| `CIERRE` | Constante | Las reglas de comparación y el estilo |

Para reclamos son ~750 tokens de system prompt. El mensaje de usuario crece con los datos (~8.000 tokens
con 8 semanas de historia real).

### 8.2 La decisión de fondo: el modelo no calcula

El primer bloque del prompt no explica la tarea: explica **la naturaleza del dato**, porque es donde un
modelo se equivoca solo.

> De dónde salen los datos: la capa gold archiva todos los domingos una foto ACUMULADA de reclamos (todo lo
> que existe desde el día cero, repartido por las dimensiones del dominio). Esa foto es un stock: no dice
> cuántos/as reclamos entraron en la semana. **Las altas semanales ya fueron calculadas restando cada foto
> contra la anterior, así que no tenés que restar nada, usá las cifras como vienen.**

Hay dos instrucciones ahí, y las dos hacen falta:

1. **Qué significan los números** ("esto es un stock, no un flujo"). Sin esto, el modelo lee el acumulado
   como si fuera la actividad de la semana y escribe que "los reclamos crecieron un 5%" cuando ese 5% es
   el crecimiento del total histórico.
2. **Que no tiene que calcular nada.** No alcanza con darle las altas ya calculadas: si no se le cierra
   explícitamente la puerta, un modelo tiende a "verificar" restando los acumulados él mismo y termina
   citando su propia cuenta —que puede estar mal— en lugar de la cifra correcta que ya tenía.

Todo lo aritmético pasó antes, en `metricas.py`. El trabajo del modelo es **elegir qué es importante y
redactarlo**, que es donde efectivamente agrega valor.

### 8.3 El glosario es data, no prompt

`prompts.py` no menciona ningún dominio. Lo específico —que RECHAZADO es un cierre sin resolución, que
`tiempoPromRespuestaLugar` son minutos, que el rango de llenado viene vacío en FALLA_SENSOR— vive en el
campo `glosario` de cada `CasoDeUso`, al lado de las dimensiones y los estados que describe.

Dos razones:

- **Coherencia**: el glosario está junto a la definición que explica. Si alguien agrega un estado a
  `estados_cerrados` y no lo explica, la inconsistencia se ve en el mismo bloque de código.
- **Extensibilidad**: agregar un dominio es agregar un `CasoDeUso` con su glosario. No se toca el prompt,
  así que no hay riesgo de romper los otros cuatro dominios al sumar el quinto.

El glosario es, en la práctica, **la pieza que más define la calidad del resumen**: es lo que evita que el
modelo interprete mal un vocabulario que no conoce. Por eso el checklist de la sección 12 lo pide
explícitamente.

### 8.4 El prompt se adapta a la forma del dominio

```python
f"Recibís {'cuatro' if caso.columna_estado else 'tres'} tablas en CSV:\n"
+ TABLAS.format(...) + (f"\n{TABLA_ESTADO}" if caso.columna_estado else "")
```

Movilidad y espacios no tienen columna de estado, así que no reciben la tabla `estado` **y el prompt no la
menciona**. Describir una tabla que no llega es una invitación directa a que el modelo la invente o se
queje de que falta. El prompt siempre describe exactamente las tablas que va a recibir.

### 8.5 Las reglas de comparación: cada una tapa un modo de falla

El bloque `CIERRE` no es una lista de buenas intenciones: cada regla responde a un error concreto y
reproducible de un LLM leyendo datos acumulados.

| Regla del prompt | Error que previene |
|---|---|
| "El eje del resumen son las altas" | Que el resumen hable del total histórico en vez de la semana |
| "Los acumulados SIEMPRE suben; que `acumulado_total` crezca no es una noticia" | Presentar como hallazgo algo que pasa por definición todas las semanas |
| "Los promedios son del acumulado entero… tratalos como un nivel" | Atribuir a la semana un promedio que se mueve despacio y está arrastrado por casos viejos |
| "La primera semana de `totales` no tiene `altas_semana`: es la foto base" | Reportar la semana base como una semana sin actividad |
| "Con volúmenes chicos (menos de ~20) usá valores absolutos" | Titular con "+300%" cuando fueron 1 → 4 casos |
| "Toda cifra que cites tiene que salir de las tablas; no inventes datos" | Alucinación de cifras |
| "Si proponés una causa, presentala como hipótesis a validar" | Afirmar causalidad a partir de una correlación semanal |
| "SIN_DATO es un dato faltante, no una categoría" | Tratar los faltantes como un barrio o una categoría real |
| "Las semanas son ISO: 2026-W38 es la semana que cierra ese domingo" | Confundir la numeración de semanas con el día del mes |

La regla de los promedios y la de la foto base son las dos que más se notan: son errores que un lector no
técnico no puede detectar, porque el resumen suena perfectamente razonable.

### 8.6 Por qué los datos van en CSV

Las tablas viajan como bloques CSV etiquetados con el nombre de la tabla:

````
Tabla `totales`:
```csv
semana,altas_semana,acumulado_total,abiertos,cerrados,descartados,tiempo_prom_hasta_estado_actual
2026-W37,,19,14,5,0,8.3
2026-W38,7,26,17,9,0,10.3
```
````

- **CSV y no JSON**: el mismo dato en JSON cuesta entre dos y tres veces más tokens, porque repite el
  nombre de cada campo en cada fila. Con 120 filas por corrida eso es dinero y contexto.
- **Etiquetado y en bloque**: el nombre de la tabla en el prompt es el mismo que en el bloque, así que
  cuando el prompt dice "la tabla `altas`" no hay ambigüedad sobre a qué se refiere.
- **Redondeado a un decimal** (`a_csv` usa `float_format="%.1f"`): más precisión no aporta a un resumen
  ejecutivo y gasta tokens.
- **Marginales en vez del cruce completo**: con decenas de altas repartidas en cuatro dimensiones, casi
  todas las combinaciones valen 1. Esas filas gastan contexto y, peor, **diluyen la señal**: el modelo ve
  cien filas de valor 1 y ninguna tendencia. Por eso `altas` abre una dimensión por vez y el cruce
  completo (`altas_detalle`) va solo de la semana analizada y recortado a las combinaciones más grandes.

### 8.7 El esquema de salida también es prompt

No se le pide el formato por texto ("escribí un párrafo y después una lista de…"). El formato es un
**structured output**: el JSON Schema de `ResumenEjecutivo` viaja en el pedido y el proveedor garantiza que
la respuesta lo cumpla.

Las instrucciones de longitud y cantidad están en las `description` de cada campo, que forman parte de ese
esquema:

```python
parrafo_ejecutivo: str = Field(
    description="Un único párrafo de 120 a 180 palabras: cómo fue la última semana frente al histórico, "
                "integrando lo más importante de los puntos destacados, riesgos y recomendaciones.")
puntos_destacados: list[str] = Field(description="2 a 5 ítems, una oración cada uno, con cifras cuando aplique.")
riesgos: list[str] = Field(description="1 a 5 ítems, una oración cada uno.")
recomendaciones: list[str] = Field(
    description="2 a 5 acciones concretas que un área de gobierno pueda ejecutar, una oración cada una.")
```

Tres ventajas sobre pedir el formato en el texto del prompt:

1. **La estructura no puede fallar.** No hay parseo de markdown ni heurísticas: el tablero recibe siempre
   los mismos cuatro campos, con los tipos correctos.
2. **La instrucción está donde se valida.** El rango "2 a 5 ítems" viaja pegado al campo que lo cumple, no
   perdido en un párrafo de instrucciones.
3. **El prompt queda para lo que importa.** El system prompt habla de cómo leer los datos; el esquema, de
   cómo entregar la respuesta.

El pedido de que el párrafo ejecutivo "integre lo más importante de los puntos destacados, riesgos y
recomendaciones" es deliberado: muchos tableros muestran solo el párrafo, y tiene que poder leerse solo.

### 8.8 Avisos: grounding defensivo, calculado por el código

Además de los datos, el mensaje puede llevar avisos que **no salen del modelo sino del código**
(`pipeline._avisos`):

> Avisos sobre los datos: Entre 2026-W36 y 2026-W38 falta al menos un snapshot, así que las altas de
> 2026-W38 acumulan más de una semana.

Si falta la foto de una semana, las altas de la siguiente acumulan dos y el modelo vería un pico que no
existe. Detectarlo es determinístico —lo hace `Ventana.saltos()`— así que lo hace el código y se lo informa;
lo mismo con las altas negativas por un reproceso. **La anomalía se detecta en el código y se explica en el
prompt**: el modelo no tiene que adivinar que el dato es raro, y en vez de inventar una causa para el pico,
lo aclara.

Los mismos avisos quedan en `metadata.avisos`, así que lo que el modelo supo queda registrado en el
archivo de salida.

### 8.9 Encuadre de la ventana

Las dos primeras líneas del mensaje fijan qué se analiza y contra qué:

> Semana a analizar: 2026-W38, ya cerrada (la foto se tomó el domingo).
> Semanas previas para comparar: 2026-W37, 2026-W36, …

Sin esto, con 9 semanas en las tablas, nada le dice al modelo cuál es "la semana". El `"ya cerrada"` es
para que no relativice el dato ("la semana todavía está en curso"), y cuando no hay previas el texto lo
dice explícitamente (`"no hay"`) en vez de dejar el lugar vacío.

El mensaje cierra con una instrucción corta y sin ambigüedad: `Escribí el resumen ejecutivo.`

### 8.10 Parámetros de inferencia

| Parámetro | Valor | Por qué |
|---|---|---|
| `thinking={"type": "adaptive"}` (Anthropic) / `reasoning_effort="medium"` (Azure OpenAI) | Razonamiento habilitado | Comparar 9 semanas × 4 tablas y elegir qué contar requiere trabajo intermedio; sin razonamiento el resumen se vuelve una descripción fila por fila |
| `max_tokens` / `max_completion_tokens` = 16000 | Holgado | El razonamiento consume tokens de salida; quedarse corto corta la respuesta |
| Corte por longitud | Error explícito | Un resumen truncado no se escribe en el archivo: falla y se ve en el log (sección 9) |
| Temperatura | Sin tocar | El determinismo lo dan las cifras ya calculadas y el esquema; bajar la temperatura empobrece la redacción sin mejorar la exactitud |

### 8.11 El prompt completo, con datos de ejemplo

**System prompt** (reclamos, abreviado):

```
Sos analista de gestión del gobierno de la ciudad. Cada semana escribís el resumen ejecutivo del tablero
de reclamos de la app CityPass+, para autoridades que lo leen en un minuto.

De dónde salen los datos: la capa gold archiva todos los domingos una foto ACUMULADA de reclamos […]
Las altas semanales ya fueron calculadas restando cada foto contra la anterior, así que no tenés que
restar nada, usá las cifras como vienen.

Recibís cuatro tablas en CSV:
1. totales: una fila por semana. `altas_semana` son las altas de reclamos de esa semana; `acumulado_total`
   y el resto de las columnas son el stock al cierre del domingo.
2. altas: las altas de cada semana abiertas de a una dimensión por vez […]
3. altas_detalle: el cruce completo de dimensiones, solo de la semana analizada […]
4. estado: el stock al cierre de cada semana por estado (y prioridad cuando aplica).

Glosario de reclamos:
- Cada fila es una combinacion de barrio, categoria, prioridad, origen de clasificacion y estado actual.
- estado_actual: RECIBIDO, EN_REVISION, ASIGNADO y EN_PROCESO son reclamos abiertos; RESUELTO y CERRADO
  son reclamos resueltos; RECHAZADO es un cierre sin resolucion.
- origenClasificacion: quien asigno la categoria. MODELO = el clasificador automatico; CIUDADANO = el
  vecino al cargar el reclamo; OPERADOR = una persona del organismo.
- tiempo_prom_hasta_estado_actual son horas desde el ingreso hasta el estado en el que esta cada reclamo.
- Los rechazos de reclamos clasificados por MODELO pueden indicar errores de clasificacion automatica.

Cómo comparar:
- El eje del resumen son las altas […]
- Los acumulados SIEMPRE suben; que `acumulado_total` crezca no es una noticia […]
- Los promedios son del acumulado entero, no de la semana […]
- La primera semana de la tabla `totales` no tiene `altas_semana` […]
- Con volúmenes chicos (menos de ~20 en un grupo) las variaciones porcentuales exageran […]
- Toda cifra que cites tiene que salir de las tablas; no inventes datos […]
- SIN_DATO en cualquier columna es un dato faltante, no una categoría.
- Las semanas son ISO: 2026-W38 es la semana que cierra ese domingo.

Estilo: español rioplatense neutro, directo, sin jerga técnica, con cifras concretas.
```

**Mensaje de usuario** (con los datos chicos de los tests, para que entre en una página):

````
Semana a analizar: 2026-W38, ya cerrada (la foto se tomó el domingo).
Semanas previas para comparar: 2026-W37.

Tabla `totales`:
```csv
semana,altas_semana,acumulado_total,abiertos,cerrados,descartados,tiempo_prom_hasta_estado_actual
2026-W37,,19,14,5,0,8.3
2026-W38,7,26,17,9,0,10.3
```

Tabla `altas`:
```csv
semana,dimension,valor,altas
2026-W38,barrio,Sur,3
2026-W38,barrio,Centro,2
2026-W38,barrio,Norte,2
2026-W38,categoria,RESIDUOS,3
…
```

Tabla `altas_detalle`:
```csv
semana,barrio,categoria,prioridad,origenClasificacion,altas
2026-W38,Sur,RESIDUOS,MEDIA,OPERADOR,3
2026-W38,Centro,BACHES,ALTA,MODELO,2
2026-W38,Norte,LUMINARIA,BAJA,CIUDADANO,2
```

Tabla `estado`:
```csv
semana,estado_actual,prioridad,cantidad,tiempo_prom_hasta_estado_actual
2026-W37,RECIBIDO,ALTA,10,5.0
2026-W37,RESUELTO,ALTA,5,20.0
…
```

Escribí el resumen ejecutivo.
````

Nótese la celda vacía de `altas_semana` en la fila `2026-W37`: es la foto base, y el prompt explica
exactamente eso para que no se lea como una semana sin actividad.

### 8.12 Cómo iterar sobre el prompt

| Herramienta | Para qué |
|---|---|
| `USAR_LLM=false` | Guarda en `entrada_llm` el mensaje exacto que se habría enviado, sin gastar un token |
| `metadata.filas_enviadas` | Cuántas filas recibió el modelo en esa corrida; la señal de que el prompt está creciendo |
| `metadata.llm.input_tokens` | El costo real del prompt, por corrida y por dominio |
| `SEMANAS_HISTORIA` | Palanca directa sobre el tamaño del prompt, sin deploy |
| `tests/test_prompts.py` | Verifica que el prompt tenga las piezas: glosario del dominio, 3 o 4 tablas, avisos, encuadre |
| `VERSION_ESQUEMA` | Queda en cada entrada del historial: permite saber con qué versión del pipeline se generó un resumen |

El flujo para cambiar el prompt es: editar `prompts.py` (o el glosario del dominio) → correr con
`USAR_LLM=false` y leer `entrada_llm` → correr una semana real con `SEMANA_OBJETIVO` sobre una carpeta de
prueba → comparar el resumen contra el anterior.

### 8.13 Qué se dejó afuera a propósito

| Técnica | Por qué no |
|---|---|
| **Few-shot** (ejemplos de resúmenes) | Un ejemplo con cifras es un riesgo de contaminación: el modelo tiende a copiar sus números o su estructura narrativa. El formato ya lo fija el esquema y el estilo se especifica en una línea |
| **Chain-of-thought explícito** ("pensá paso a paso…") | Los dos proveedores tienen razonamiento nativo (`thinking` / `reasoning_effort`). Pedirlo por prompt duplicaría el trabajo y ensuciaría la salida |
| **Pedir el formato en texto** | Lo resuelve el structured output, que además no puede fallar |
| **Prompt único para los cinco dominios** | Un prompt genérico obliga al modelo a inferir el vocabulario del dominio. El glosario por caso es lo que evita que lea mal un estado o una unidad |
| **Pedirle que calcule algo** | Sección 8.2: toda la aritmética pasó antes, en código cubierto por tests |

---

## 9. Integración con el LLM

Qué se le manda y por qué está armado así: **sección 8**. Esta sección es cómo se le manda.

### Contrato común

Ambos proveedores exponen `generar_resumen(mensaje, settings, system_prompt, client=None)` y devuelven
`(ResumenEjecutivo, uso)`. `uso` va a `metadata.llm` con proveedor, modelo, request id, razón de fin y
tokens de entrada y salida.

Ambos validan tres fallas antes de devolver:

| Falla | Azure OpenAI | Anthropic | Resultado |
|---|---|---|---|
| Rechazo del modelo | `message.refusal` | `stop_reason == "refusal"` | `RuntimeError` con el motivo |
| Respuesta cortada | `finish_reason == "length"` | `stop_reason == "max_tokens"` | `RuntimeError` sugiriendo subir el límite o achicar el histórico |
| No se pudo parsear | `message.parsed is None` | `parsed_output is None` | `RuntimeError` con la razón de fin |

Que sean errores y no un resumen a medias es deliberado: el timer los captura por dominio, el dominio
queda sin análisis esa semana y el problema aparece en el log en vez de escribirse un resumen truncado en
el archivo que consume el tablero.

### Azure OpenAI (default)

```python
client.chat.completions.parse(
    model=settings.azure_openai_deployment,
    messages=[{"role": "system", ...}, {"role": "user", ...}],
    response_format=ResumenEjecutivo,     # structured outputs
    max_completion_tokens=16000,
    reasoning_effort="medium",
)
```

Cliente con `timeout=300.0` y `max_retries=3`. Falla temprano con `ValueError` si faltan endpoint o key.

### Anthropic

```python
client.beta.messages.parse(
    model=settings.anthropic_model,
    max_tokens=16000,
    thinking={"type": "adaptive"},
    system=system_prompt,
    messages=[{"role": "user", "content": mensaje}],
    output_format=ResumenEjecutivo,
    **extra,                               # fallback server-side si el modelo lo admite
)
```

`MODELOS_CON_FALLBACK = {"claude-opus-5", "claude-fable-5-1"}`: en esos modelos se agrega
`betas=["server-side-fallback-2026-07-01"]` y `fallbacks="default"`, que permite recuperar la corrida si
los clasificadores de seguridad rechazan el pedido. Con otros modelos esos parámetros no se envían.

### Tamaño del contexto

Con 8 semanas de historia y ~470 registros, la corrida de reclamos envía del orden de 120 filas entre las
cuatro tablas (~9.000 tokens de entrada). El campo `metadata.filas_enviadas` deja registro exacto por
corrida; si creciera mucho, la palanca es bajar `SEMANAS_HISTORIA` o el `top` de `altas_detalle`.

---

## 10. Persistencia y concurrencia

El historial es un único blob por dominio que se lee, se modifica y se vuelve a escribir. Entre la lectura
y la escritura otra corrida podría escribir el mismo archivo (una ejecución manual mientras corre el
timer, o un reintento de Functions).

La escritura usa **optimistic concurrency** con el ETag del blob:

```python
historial, etag = blob_io.leer_json(cliente, container, ruta)
documento = pipeline.acumular(historial, entrada, caso)
blob_io.escribir_json(cliente, container, ruta, documento, etag)
#   → upload_blob(..., etag=etag, match_condition=MatchConditions.IfNotModified)
```

Si el blob cambió, Azure responde 412 y el SDK levanta `ResourceModifiedError`, que se traduce a un
`RuntimeError` con instrucción explícita: *"cambió mientras se generaba el análisis; reintentar la
corrida"*. **No se pisa** el trabajo de la otra corrida. Cuando el archivo todavía no existe, `etag` es
`None` y la escritura va sin condición.

`acumular()` es idempotente por semana: volver a correr la misma semana reemplaza la entrada en vez de
duplicarla, así que un reintento es seguro.

---

## 11. Manejo de errores

### Aislamiento por dominio

El `try/except` del timer es por dominio. Los cinco dominios comparten proceso pero no destino: cada uno
escribe su propio archivo. Al final, los dominios que fallaron quedan listados en un warning.

Errores esperables que aíslan un dominio sin frenar la corrida:

| Situación | Excepción | Mensaje |
|---|---|---|
| Dominio sin snapshots en gold | `FileNotFoundError` | Indica el patrón de archivo esperado |
| Un solo snapshot | `ValueError` | "Se necesitan al menos 2 snapshots…" |
| `SEMANA_OBJETIVO` inexistente | `ValueError` | Lista las semanas disponibles |
| Dos snapshots de la misma semana | `ValueError` | Nombra la semana repetida |
| Faltan columnas en el parquet | `ValueError` | Lista las columnas faltantes |
| Snapshot sin semana ni `fecha_snapshot` | `ValueError` | Explica que no se puede fechar |
| Rechazo / corte / no parseable del LLM | `RuntimeError` | Sección 9 |
| El historial cambió en el medio | `RuntimeError` | Sección 10 |
| `LLM_PROVIDER` desconocido | `ValueError` | Antes de cualquier llamada de red |

### Anomalías que no son errores

Dos situaciones no abortan nada pero quedan registradas en `metadata.avisos` **y** se le informan al
modelo en el mensaje:

- **Snapshot faltante**: las altas de la semana siguiente acumulan más de una semana.
- **Altas negativas**: una foto con menos registros que la anterior (reproceso o borrado).

---

## 12. Extensibilidad: agregar un dominio

Alcanza con agregar un `CasoDeUso` al diccionario `CASOS` de `casos.py`. No hay que tocar `datos.py`,
`metricas.py`, `prompts.py` ni `pipeline.py`.

```python
TRANSPORTE = CasoDeUso(
    nombre="transporte",
    prefijo="Transporte Publico/",          # carpeta dentro del container gold
    base_archivo="transporte_resumen",      # <base>_<WW>_<YYYY>.parquet
    metrica="cantidadServicios",
    etiqueta_metrica="servicios",
    dimensiones=["linea", "franjaHoraria"], # las que NO cambian después del alta
    columna_estado=None,                    # o el nombre de la columna de estado
    promedios={"promPuntualidad": "cantidadServicios"},
    contadores=["serviciosDemorados"],
    glosario="""\
- Cada fila es una combinación de línea y franja horaria.
- promPuntualidad son minutos de desvío respecto del horario programado.""",
)

CASOS = {c.nombre: c for c in (RECLAMOS, EMERGENCIAS, MOVILIDAD, ESPACIOS, RESIDUOS, TRANSPORTE)}
```

Checklist:

1. **Dimensiones estables**: solo columnas que no cambian después del alta. Si una dimensión cambia, la
   resta entre fotos deja de contar hechos nuevos.
2. **Estados**: si hay columna de estado, clasificar los valores en abiertos, cerrados y descartados.
3. **Promedios**: cada uno con la columna que lo pondera, y esa columna tiene que estar en la métrica o en
   los contadores (los tests verifican esta invariante para los cinco dominios).
4. **Glosario**: qué es cada fila, qué significan los estados y qué unidad tienen los tiempos. Es lo que
   evita que el modelo lea mal el dominio.
5. **Tests**: agregar el dominio a los tests de `casos.py` y, si tiene una forma de datos distinta a las ya
   cubiertas, un caso en `test_metricas.py`.
6. Agregar el nombre a `CASOS` en los App Settings (o usar `todos`).

---

## 13. Testing y CI

### La suite

**109 tests, 99% de cobertura** sobre `analisis_semanal/` y `function_app.py`. Corren en segundos, **sin
Azure, sin credenciales y sin llamar a ningún LLM**: las fotos de gold se arman en memoria,
`BlobServiceClient` se reemplaza por un doble (`tests/conftest.py`) y los proveedores de LLM se inyectan
como cliente falso por el parámetro `client`.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest --cov=analisis_semanal --cov=function_app --cov-report=term-missing
```

| Archivo | Tests | Foco |
|---|---|---|
| `test_casos.py` | 6 | Registro de los 5 dominios; invariante de los promedios ponderados |
| `test_config.py` | 9 | Defaults, `CASOS`, `USAR_LLM`, variable en blanco = ausente |
| `test_datos.py` | 21 | Qué blob es un snapshot (la foto mutable se ignora), normalización, ventana, saltos |
| `test_metricas.py` | 21 | Las cuentas, verificadas a mano: altas, promedios ponderados, estado, contadores |
| `test_prompts.py` | 6 | 3 o 4 tablas según el dominio; avisos en el mensaje |
| `test_pipeline.py` | 12 | Metadata y cifras, `SEMANA_OBJETIVO`, avisos, historial sin duplicados |
| `test_llm.py` | 13 | Armado del pedido por proveedor y las tres fallas de la sección 9 |
| `test_blob_io.py` | 13 | Lectura de gold, `(None, None)` si no existe, ETag que no pisa |
| `test_function_app.py` | 8 | Timer de punta a punta; un dominio sin datos no frena a los demás |

Los dos caminos sin cubrir son ramas defensivas que ningún dominio actual puede alcanzar.

### Dobles de prueba

- **`ClienteFalso` / `ContenedorFalso`** (`tests/conftest.py`): Blob Storage en memoria con ETags
  incrementales, que reproduce `ResourceNotFoundError`, `ResourceExistsError` y `ResourceModifiedError`.
  Escribe y lee Parquet real, así que ejercita el mismo camino de `pandas`/`pyarrow` que producción.
- **Clientes de LLM falsos** (`tests/test_llm.py`): capturan los kwargs del pedido y devuelven respuestas
  armadas, incluidas las de rechazo y corte.
- **`llm_falso`** (`tests/test_pipeline.py`): reemplaza `generar_resumen` en los dos módulos proveedores.

### CI

`.github/workflows/tests.yml`: corre con cualquier push y con cada Pull Request hacia `main`, en
Ubuntu con Python 3.11, instala `requirements.txt` + `requirements-dev.txt` y ejecuta

```
pytest --cov=analisis_semanal --cov=function_app --cov-report=term-missing --cov-fail-under=60
```

El umbral de 60% es el mínimo de la rúbrica: si alguien agrega código sin tests y la cobertura cae, el
check se pone en rojo. Se puede desactivar desde la pestaña Actions sin tocar código.

---

## 14. Despliegue

### Local

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy local.settings.json.example local.settings.json   # y completar credenciales
.\.venv\Scripts\Activate.ps1; func start
```

Disparar el timer a mano sin esperar al lunes:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7071/admin/functions/analisis_semanal -ContentType application/json -Body '{}'
```

Para una prueba segura: `USAR_LLM=false`, `CASOS=reclamos` e `INPUT_PREFIX` apuntando a una carpeta de
prueba dentro de `gold`.

### Azure

```powershell
func azure functionapp publish <nombre-function-app> --python
```

`.funcignore` deja afuera del paquete `tests/`, `pytest.ini`, `requirements-dev.txt`, `.github/`, `.venv/`
y `README.md`: el deploy no cambió al agregar la suite de tests.

---

## 15. Seguridad

- **Secretos**: nunca en el repo. `local.settings.json` está en `.gitignore`; en Azure son App Settings.
- **Identidad recomendada en producción**: Managed Identity en lugar de keys, con los roles
  *Storage Blob Data Contributor* sobre el storage de datos y *Cognitive Services OpenAI User* sobre el
  recurso de OpenAI. `blob_io.crear_cliente()` ya soporta ese camino vía `STORAGE_ACCOUNT_URL`.
- **Datos**: el módulo solo lee tablas **agregadas**; no accede a datos personales de vecinos ni los envía
  al modelo.
- **Salida**: el JSON se escribe en un container privado; el tablero lo consume con sus propias credenciales.
- **Logs**: no registran contenido de los datos, solo cantidades, rutas y metadata de uso del modelo.

---

## 16. Rendimiento y costos

| Dimensión | Valor de referencia |
|---|---|
| Duración de una corrida | Segundos por dominio; el grueso es la latencia del LLM (timeout 300 s) |
| Tokens por corrida (reclamos, 8 semanas, ~470 registros) | ~9.000 de entrada, ~2.600 de salida |
| Costo del LLM | Del orden de centavos de dólar por dominio por semana, a precios de lista |
| Function App | Una ejecución semanal entra en el nivel gratuito de Flex Consumption |
| Datos leídos | 9 blobs Parquet por dominio y corrida |

El consumo real de cada corrida queda en `metadata.llm`, así que el costo es auditable por semana y por
dominio sin instrumentación extra.

---

## 17. Runbook

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Un dominio no tiene resumen esta semana | Menos de 2 snapshots, o el pipeline no archivó el domingo | Revisar el log del dominio; verificar que exista el parquet de la semana en gold |
| Todos los dominios fallan | Storage mal configurado o sin permisos | Verificar `STORAGE_CONNECTION_STRING` / `STORAGE_ACCOUNT_URL` y el rol de la identidad |
| `RuntimeError: … cambió mientras se generaba el análisis` | Dos corridas en paralelo sobre el mismo dominio | Volver a correr; `acumular()` es idempotente por semana |
| La respuesta se cortó por longitud | Histórico muy grande | Bajar `SEMANAS_HISTORIA` o subir el límite de tokens |
| Hay que rehacer una semana con datos corregidos | — | Correr con `SEMANA_OBJETIVO=2026-Wxx`; la entrada se reemplaza |
| Hay que validar sin gastar tokens | — | `USAR_LLM=false`: la entrada queda con `entrada_llm` |
| El resumen menciona un pico raro | Falta el snapshot de una semana | Mirar `metadata.avisos`; el módulo ya lo detecta y lo aclara |
| Cifras negativas en altas | Reproceso o borrado en gold | Mirar `metadata.avisos`; revisar el reproceso del pipeline |

---

## 18. Limitaciones conocidas

| Limitación | Impacto | Mitigación posible |
|---|---|---|
| `leer_snapshots()` descarga **todos** los snapshots del prefijo y recién después se recorta la ventana | El costo de lectura crece con la historia del dominio (52 blobs al año) | Filtrar por nombre antes de descargar, quedándose con las últimas N semanas |
| `Ventana.saltos()` no detecta huecos **a través del cambio de año** cuando el parquet no trae `fecha_snapshot` | Un domingo faltante entre diciembre y enero podría no avisarse | Comparar por fecha ISO en vez de por número de semana |
| Los dominios se procesan secuencialmente | La corrida dura la suma de las latencias del LLM | Paralelizar por dominio si llegara a importar |
| Los fallos solo quedan en el log | Nadie se entera si un dominio queda sin análisis | Alerta en Application Insights sobre el warning de cierre |
| El análisis es semanal y sobre semana cerrada | No hay lectura intrasemanal | Fuera de alcance por diseño |
| `SEMANAS_HISTORIA` afecta tamaño de prompt y costo linealmente | — | Está expuesto como App Setting, se ajusta sin deploy |
