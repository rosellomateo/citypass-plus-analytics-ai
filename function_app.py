"""Azure Function App (Python, modelo v2): analisis ejecutivo semanal de CityPass+.

Timer -> por cada caso de uso configurado en CASOS, lee los snapshots semanales de su capa gold ->
el LLM compara la ultima semana terminada contra las anteriores -> agrega el resultado al historial
del caso en analisis/<caso>.json.

Si un caso falla (por ejemplo, porque todavia no tiene dos snapshots para comparar) se loguea y se
sigue con el resto: un dominio sin historia no deberia frenar a los demas.
"""
import logging

import azure.functions as func

from analisis_semanal import blob_io, casos, pipeline
from analisis_semanal.config import Settings

app = func.FunctionApp()

# El SDK de Storage loguea cada request HTTP en INFO; alcanza con warnings.
logging.getLogger("azure").setLevel(logging.WARNING)


def analizar_caso(cliente, nombre: str, settings: Settings) -> str:
    caso = casos.obtener(nombre)
    prefijo = settings.input_prefix if len(settings.casos) == 1 else None
    snapshots = blob_io.leer_snapshots(cliente, settings.input_container, caso, prefijo)
    logging.info("[%s] %d snapshots semanales", caso.nombre, len(snapshots))

    entrada = pipeline.ejecutar(caso, snapshots, settings, usar_llm=settings.usar_llm)

    # Lectura y escritura del historial en la misma corrida: el ETag evita pisar
    # otra ejecucion que haya escrito el archivo en el medio.
    ruta = pipeline.ruta_salida(caso, settings)
    historial, etag = blob_io.leer_json(cliente, settings.output_container, ruta)
    documento = pipeline.acumular(historial, entrada, caso)
    blob_io.escribir_json(cliente, settings.output_container, ruta, documento, etag)

    return (f"[{caso.nombre}] semana {entrada['semana']} -> {settings.output_container}/{ruta} "
            f"({len(documento['semanas'])} semanas en el historial)")


# SCHEDULE es un App Setting (CRON de 6 campos, en UTC). Default sugerido: lunes 10:00 UTC = 07:00 ART.
@app.timer_trigger(schedule="%SCHEDULE%", arg_name="timer", run_on_startup=False, use_monitor=True)
def analisis_semanal(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.warning("La ejecucion programada viene atrasada")

    settings = Settings.desde_entorno()
    cliente = blob_io.crear_cliente(settings)
    logging.info("Casos a analizar: %s", ", ".join(settings.casos))

    fallados = []
    for nombre in settings.casos:
        try:
            logging.info(analizar_caso(cliente, nombre, settings))
        except Exception as error:  # noqa: BLE001 - un caso roto no frena a los demas
            fallados.append(nombre)
            logging.error("[%s] no se pudo analizar: %s", nombre, error)

    if fallados:
        logging.warning("Casos sin analisis en esta corrida: %s", ", ".join(fallados))
