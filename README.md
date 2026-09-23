# citypass-plus-analytics-ai

Azure Function (Python 3.11, modelo v2, plan Flex Consumption) que corre **una vez por semana**, lee los
**snapshots semanales** de la capa gold de CityPass+ y le pide a un LLM que **compare la última semana
terminada contra las anteriores**. El resultado se **acumula** en un JSON por caso de uso, que es lo que
consume el tablero.

Este repo contiene únicamente el código que se despliega en la nube. La generación de datos de prueba y las
herramientas de backfill viven fuera.

```
Timer (lunes 07:00 ART) ──> gold/<dominio>/<base>_<WW>_<YYYY>.parquet   (una foto acumulada por semana)
                              │
                              ▼
                      casos.py     (qué dimensiones, qué métrica y qué estados tiene el dominio)
                      datos.py     (descubre y ordena snapshots, elige la ventana)
                      metricas.py  (altas = foto - foto anterior; stock por estado)
                              │  3 o 4 tablas en CSV
                              ▼
                      LLM con salida estructurada (Pydantic)
                        · azure_openai: gpt-5-mini   (default)
                        · anthropic:    Claude Opus 5
                              │
                              ▼
                      analisis/<caso>.json   (un archivo por caso, con todas las semanas)
```

## Lo importante: la capa gold da stock, no flujo

Las capas gold agrupan **toda** la tabla de silver, sin filtrar por fecha, y archivan el resultado cada
domingo como `<base>_<semana>_<anio>.parquet`. O sea:

- **Cada snapshot es acumulado**: `reclamos_resumen_38_2026.parquet` tiene todos los reclamos desde el día
  cero, no los de la semana 38. El número de la semana dice **cuándo se sacó la foto**, no de cuándo son
  los registros.
- **La capa gold no guarda la fecha de alta** (salvo movilidad, que tiene `fechaInicio` en el grano), así
  que no hay forma de leer las altas de una semana directo de un archivo.
- La tabla sin semana en el nombre es la misma foto pero mutable (se pisa todos los días). **El módulo la
  ignora**: mezclarla duplicaría la última semana o metería una semana a medio terminar.

Por eso `metricas.py` calcula las **altas restando cada foto contra la anterior**, agrupando por las
dimensiones que **no cambian después del alta** y dejando afuera la columna de estado. Si se restara
incluyendo el estado, el resultado sería el neto de cada bucket (negativo cuando algo pasa de `ASIGNADO` a
`CERRADO`), que no es un alta.

Esa resta la hace el código y no el LLM a propósito: restar decenas de filas a ojo es justo lo que un
modelo hace mal, y son las cifras que después aparecen en el resumen.

Consecuencia práctica: **para analizar N semanas hacen falta N+1 snapshots**, porque la primera foto es la
base contra la que se resta. Con un solo snapshot el caso falla con un mensaje explícito y la corrida sigue
con los demás.

## Los cinco casos de uso

| Caso | Carpeta en gold | Métrica | Dimensiones | Estado |
|---|---|---|---|---|
| `reclamos` | `Reclamos/` | `row_count` | barrio, categoria, prioridad, origenClasificacion | `estado_actual` |
| `emergencias` | `Emergencias y Seguridad/` | `cantidadEmergencias` | prioridad | `estado_actual` |
| `movilidad` | `Movilidad Urbana/` | `cantidadViajes` | fechaInicio, estacionInicio, duracionViaje | — |
| `espacios` | `Espacios Publicos y Cultura/` | `cantidadTotal` | recursoId, tipoReserva, categoria, zona | — |
| `residuos` | `Gestion de Residuos Inteligente/` | `cantidadAlertas` | zona, tipoAlerta, prioridad, rangoNivelLlenado | — |

Los dominios con estado reciben además la tabla `estado` (el stock del backlog). Los que no, llevan su
estado en contadores acumulados (`cantidadConfirmadas`, `cantidadResueltas`, …) que van en `totales`.

**Para sumar un dominio nuevo alcanza con agregar un `CasoDeUso` en `casos.py`**: prefijo, nombre base del
archivo, métrica, dimensiones, estados y glosario. No hay que tocar el resto del código.

## Estructura

| Archivo | Qué hace |
|---|---|
| `function_app.py` | Timer trigger: recorre los casos configurados y acumula el JSON de cada uno |
| `analisis_semanal/casos.py` | Registro de los 5 dominios: prefijo, métrica, dimensiones, estados, glosario |
| `analisis_semanal/datos.py` | Descubre los snapshots, los fecha y arma la ventana (base + semanas) |
| `analisis_semanal/metricas.py` | Altas por resta entre fotos, stock por estado y totales por semana |
| `analisis_semanal/prompts.py` | Prompt de sistema armado a partir del caso + mensaje con las tablas |
| `analisis_semanal/esquema.py` | Esquema de la respuesta: párrafo, destacados, riesgos, recomendaciones |
| `analisis_semanal/llm_azure_openai.py` | Proveedor Azure OpenAI (`LLM_PROVIDER=azure_openai`) |
| `analisis_semanal/llm.py` | Proveedor Claude (`LLM_PROVIDER=anthropic`) |
| `analisis_semanal/pipeline.py` | Orquesta: ventana → tablas → LLM → entrada del historial |
| `analisis_semanal/blob_io.py` | Blob Storage: lee snapshots, lee/escribe el JSON acumulado (con ETag) |
| `tests/` | Suite de pytest: datos inventados, Blob Storage y LLM mockeados (ver **Tests**) |

## Qué recibe el LLM

Tablas en CSV, ya calculadas (el modelo no tiene que restar nada):

| Tabla | Grano | Para qué |
|---|---|---|
| `totales` | una fila por semana | El hilo del resumen: altas, acumulado, stock y promedios |
| `altas` | semana × dimensión × valor | Altas de cada semana, marginales en formato largo |
| `altas_detalle` | semana analizada, cruce completo | Las combinaciones más grandes de la última semana |
| `estado` | semana × estado × prioridad | Cómo quedó el backlog (solo si el dominio tiene estado) |

Las marginales en vez del cruce completo para todas las semanas son a propósito: con decenas de altas
repartidas en varias dimensiones casi todas las combinaciones valen 1 y esas filas gastan tokens sin decir
nada.

El prompt le aclara al modelo que los acumulados siempre suben, que los promedios son un nivel arrastrado
por casos viejos (no el resultado de la semana) y que la primera semana de `totales` no tiene altas porque
es la foto base.

## Salida: un JSON por caso de uso, acumulativo

`analisis/<caso>.json` — cada corrida **agrega** su semana al arreglo; si la semana ya estaba (se volvió a
correr), se **reemplaza** en vez de duplicarse. La escritura usa el ETag del blob para no pisar otra
corrida en paralelo.

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
        "parrafo_ejecutivo": "…",          // un párrafo de ~120-180 palabras
        "puntos_destacados": ["…"],
        "riesgos": ["…"],
        "recomendaciones": ["…"]
      },
      "metadata": {
        "caso_de_uso": "reclamos", "semana_actual": "2026-W38",
        "semanas_comparadas": ["…"], "snapshot_base": "2026-W31",
        "fuentes": ["…"], "corte": "2026-09-20", "avisos": ["…"],
        "cifras": { "altas_semana": 57, "acumulado_total": 469, "abiertos": 288 },
        "llm": { "proveedor": "…", "modelo_respuesta": "…", "input_tokens": 0, "output_tokens": 0 }
      }
    }
  ]
}
```

`metadata.avisos` son las cosas raras que el código detecta y que además se le avisan al modelo: snapshots
faltantes (una semana que acumula dos) y altas negativas (una foto con menos registros que la anterior, que
solo puede venir de un reproceso).

El tablero lee la última entrada de `analisis` para la semana corriente, o recorre el arreglo para ver la
evolución.

## Configuración (App Settings / local.settings.json)

| Variable | Valor |
|---|---|
| `SCHEDULE` | `0 0 10 * * 1` (CRON de 6 campos en UTC = lunes 07:00 ART) |
| `STORAGE_CONNECTION_STRING` | connection string del storage de datos |
| `INPUT_CONTAINER` | `gold` |
| `INPUT_PREFIX` | vacío = el prefijo que declara cada caso; sirve para apuntar a una carpeta de prueba cuando se analiza un solo caso |
| `OUTPUT_CONTAINER` / `OUTPUT_PREFIX` | `analisis` / vacío |
| `CASOS` | `reclamos` (lista separada por comas, o `todos` para los cinco) |
| `SEMANAS_HISTORIA` | `8` = semanas analizadas; se leen 9 snapshots (la base no se analiza) |
| `SEMANA_OBJETIVO` | vacío = última semana terminada (o `2026-W38` para rehacer una) |
| `LLM_PROVIDER` | `azure_openai` (o `anthropic`) |
| `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` | endpoint y key del recurso de Azure OpenAI |
| `AZURE_OPENAI_DEPLOYMENT` / `AZURE_OPENAI_API_VERSION` | `gpt-5-mini` / `2025-04-01-preview` |
| `USAR_LLM` | `true` (`false` = no llama al LLM y guarda en `entrada_llm` lo que se enviaría) |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | solo si `LLM_PROVIDER=anthropic` |

Copiar `local.settings.json.example` a `local.settings.json` y completar las credenciales; ese archivo no
se versiona.

## Correr y publicar

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\Activate.ps1; func start    # activar el venv es necesario para que func use Python 3.11

# Disparar el timer a mano sin esperar al lunes:
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7071/admin/functions/analisis_semanal -ContentType application/json -Body '{}'
```

```powershell
func azure functionapp publish <nombre-function-app> --python
```

Mejoras para producción: Managed Identity en lugar de keys (rol *Cognitive Services OpenAI User* sobre el
recurso de OpenAI y *Storage Blob Data Contributor* sobre el storage de datos), y las keys restantes en
Key Vault.

## Tests

La suite corre entera **en local, sin Azure y sin llamar al LLM**: las fotos de gold se arman en memoria,
`BlobServiceClient` se reemplaza por un doble y los dos proveedores de LLM se inyectan como cliente falso.
No hace falta ninguna credencial.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest --cov=analisis_semanal --cov=function_app --cov-report=term-missing
```

| Archivo | Qué cubre |
|---|---|
| `tests/test_casos.py` | El registro de los 5 dominios y sus promedios ponderados |
| `tests/test_config.py` | Defaults de los App Settings y parseo de `CASOS` / `USAR_LLM` |
| `tests/test_datos.py` | Qué blob es un snapshot (la foto mutable del día se ignora), normalización y ventana |
| `tests/test_metricas.py` | Las cuentas: altas por resta entre fotos, promedios ponderados, stock por estado |
| `tests/test_prompts.py` | El prompt según el dominio (3 o 4 tablas) y los avisos sobre los datos |
| `tests/test_pipeline.py` | Metadata y cifras de la entrada, avisos, e historial que no duplica semanas |
| `tests/test_llm.py` | Cómo se arma el pedido a cada proveedor y qué pasa ante rechazo o corte |
| `tests/test_blob_io.py` | Lectura de gold y escritura del historial con ETag (no pisa una corrida paralela) |
| `tests/test_function_app.py` | El timer de punta a punta: un caso sin datos no frena a los demás |

Cada push y cada Pull Request hacia `main` los corre en GitHub Actions
(`.github/workflows/tests.yml`), que además exige **60% de cobertura mínima**.

## Costo

Con 8 semanas de historia y ~470 registros, una corrida de `reclamos` usa ~9.000 tokens de entrada y ~2.600
de salida: del orden de centavos de dólar por ejecución a precios de lista. La Function App con una
ejecución semanal entra en el nivel gratuito de Flex Consumption. El consumo de cada corrida queda en
`metadata.llm`.
