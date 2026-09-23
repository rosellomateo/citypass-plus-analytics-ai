# Resumen técnico — `citypass-plus-analytics-ai`

Versión corta para entender la solución tecnológica en 5 minutos.
Detalle completo en [`documentacion-tecnica.md`](documentacion-tecnica.md); visión de negocio en
[`documentacion-funcional.md`](documentacion-funcional.md).

---

## Qué es

Una **Azure Function en Python 3.11** con un **timer semanal** que, para cada uno de los cinco dominios de
CityPass+, lee los snapshots de la capa gold, calcula qué pasó en la semana y le pide a un **LLM con salida
estructurada** que escriba el resumen ejecutivo. El resultado se acumula en un JSON por dominio, que
consume el tablero.

```
Timer (lunes 07:00 ART)
   │
   ▼
gold/<dominio>/<base>_<WW>_<YYYY>.parquet        ← 9 fotos semanales por dominio
   │
   ├─ 1. seleccionar ventana        datos.py      8 semanas + la foto base
   ├─ 2. altas = foto − anterior    metricas.py   3 o 4 tablas en CSV
   ├─ 3. armar el prompt            prompts.py    system prompt por dominio
   ├─ 4. llamar al LLM              llm_*.py      structured output (Pydantic)
   └─ 5. acumular y escribir        blob_io.py    con ETag
   │
   ▼
analisis/<dominio>.json                          ← historial de todas las semanas
```

## Stack

| Capa | Tecnología |
|---|---|
| Runtime / hosting | Python 3.11 · Azure Functions modelo v2 · Flex Consumption |
| Disparo | Timer trigger, CRON de 6 campos en UTC (`SCHEDULE`) |
| Entrada | Azure Blob Storage, container `gold`, archivos Parquet (`pandas` + `pyarrow`) |
| IA | Azure OpenAI `gpt-5-mini` (default) o Anthropic Claude Opus 5, ambos con structured outputs |
| Contrato de salida | Pydantic v2 |
| Salida | Azure Blob Storage, container `analisis`, un JSON por dominio |
| Tests / CI | pytest + pytest-cov · GitHub Actions |

## El concepto que explica todo el diseño

La capa gold entrega **stock**, no **flujo**: cada archivo es una foto acumulada de *todo lo que existe
desde el día cero*, no de lo que pasó esa semana. Para saber qué entró en la semana hay que **restar la
foto del domingo contra la del domingo anterior**.

Tres consecuencias:

1. **La resta la hace el código, no el modelo.** Sumar y restar decenas de filas es lo que un LLM hace
   peor, y esas cifras terminan en el resumen que lee una autoridad. El modelo recibe las cifras ya
   calculadas e interpreta.
2. **Para analizar N semanas hacen falta N+1 fotos.** La más vieja es la base: no se analiza, es el
   sustraendo de la primera semana.
3. **La resta agrupa sin la columna de estado.** Las dimensiones no cambian después del alta, así que la
   resta cuenta hechos nuevos; si incluyera el estado daría el neto de cada bucket (negativo cuando algo
   pasa de ASIGNADO a CERRADO), que no es un alta.

También por diseño se **ignora la tabla mutable** de gold (la que se pisa todos los días): solo entran los
snapshots semanales, que son inmutables.

## Los módulos

| Módulo | Responsabilidad |
|---|---|
| `function_app.py` | Timer trigger; recorre los dominios con `try/except` por dominio |
| `analisis_semanal/config.py` | `Settings` inmutable leído de App Settings |
| `analisis_semanal/casos.py` | **Registro declarativo de los 5 dominios**: prefijo, métrica, dimensiones, estados, glosario |
| `analisis_semanal/datos.py` | Reconoce y fecha los snapshots, normaliza tipos, arma la ventana |
| `analisis_semanal/metricas.py` | Las cuentas: altas por resta, promedios ponderados, stock por estado |
| `analisis_semanal/prompts.py` | System prompt por dominio + mensaje con las tablas en CSV |
| `analisis_semanal/esquema.py` | `ResumenEjecutivo`: párrafo, destacados, riesgos, recomendaciones |
| `analisis_semanal/llm_azure_openai.py` · `llm.py` | Los dos proveedores, con la misma firma |
| `analisis_semanal/pipeline.py` | Orquesta: ventana → tablas → LLM → entrada del historial |
| `analisis_semanal/blob_io.py` | Lectura de gold y escritura del historial con ETag |

**El código es genérico y los dominios son data.** Agregar un dominio es agregar un `CasoDeUso` al
diccionario `CASOS` de `casos.py`: no se toca ningún otro módulo.

## Lo que recibe y devuelve el modelo

**Recibe** 3 o 4 tablas en CSV, ya calculadas:

- `totales` — una fila por semana: altas, acumulado, stock por estado y promedios.
- `altas` — altas por semana abiertas de a una dimensión por vez (marginales, para no gastar tokens en
  combinaciones que valen 1).
- `altas_detalle` — el cruce completo, solo de la semana analizada y solo las combinaciones más grandes.
- `estado` — stock por estado y prioridad (solo dominios con columna de estado).

Más el system prompt del dominio (glosario + reglas de lectura: el acumulado siempre sube, los promedios
son un nivel, `SIN_DATO` es un faltante, toda cifra sale de las tablas).

**Devuelve** un objeto validado por Pydantic con cuatro campos: `parrafo_ejecutivo`, `puntos_destacados`,
`riesgos`, `recomendaciones`. Si el modelo rechaza el pedido, se corta por longitud o no se puede parsear,
es un error explícito: ese dominio queda sin análisis esa semana en vez de escribir un resumen a medias.

## Robustez

| Mecanismo | Para qué |
|---|---|
| `try/except` por dominio | Un dominio sin datos no frena a los otros cuatro |
| Escritura condicionada por **ETag** | Dos corridas en paralelo no se pisan |
| `acumular()` idempotente por semana | Reintentar o rehacer una semana reemplaza, no duplica |
| `metadata.avisos` | Snapshots faltantes y altas negativas se informan (al log y al modelo) |
| `metadata` completa | Trazabilidad: qué semanas, qué archivos y qué cifras originaron el resumen |
| `USAR_LLM=false` | Hace todo el recorrido sin llamar al modelo; guarda el mensaje que enviaría |

## Configuración mínima

| Variable | Valor típico |
|---|---|
| `SCHEDULE` | `0 0 10 * * 1` (lunes 07:00 ART) |
| `STORAGE_CONNECTION_STRING` *o* `STORAGE_ACCOUNT_URL` | Storage de datos (el segundo usa Managed Identity) |
| `CASOS` | `todos` |
| `LLM_PROVIDER` + `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` | `azure_openai` y el recurso |
| `SEMANAS_HISTORIA` | `8` |
| `USAR_LLM` | `true` (`false` para probar sin gastar tokens) |

## Correr y probar

```bash
# Local
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
func start        # con el venv activado

# Tests: sin Azure, sin credenciales y sin llamar al LLM
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest --cov=analisis_semanal --cov=function_app
```

**109 tests, 99% de cobertura.** Las fotos de gold se arman en memoria, `BlobServiceClient` se reemplaza
por un doble y los proveedores de LLM se inyectan como cliente falso. GitHub Actions los corre con cada
push y cada PR a `main`, exigiendo 60% de cobertura mínima.

## Costo y escala

Con 8 semanas de historia y ~470 registros, una corrida de un dominio usa ~9.000 tokens de entrada y
~2.600 de salida: centavos de dólar por dominio por semana. La Function App con una ejecución semanal
entra en el nivel gratuito de Flex Consumption. El consumo real de cada corrida queda registrado en
`metadata.llm`.
