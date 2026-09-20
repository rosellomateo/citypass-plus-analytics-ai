"""Registro de los casos de uso que analiza el modulo.

Los cinco dominios de CityPass+ guardan su capa gold igual: una foto
ACUMULADA por dominio, sobreescrita todos los dias, mas una copia archivada
cada domingo con la semana ISO en el nombre. Lo que cambia entre ellos son las
dimensiones, el nombre de la metrica y si tienen o no una columna de estado.

Este modulo describe esas diferencias; el resto del codigo es generico.

Para sumar un dominio nuevo alcanza con agregar un CasoDeUso al diccionario
CASOS: no hay que tocar datos.py, metricas.py ni pipeline.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CasoDeUso:
    nombre: str
    prefijo: str                 # carpeta dentro del container gold
    base_archivo: str            # <base>_<semana>_<anio>.parquet
    metrica: str                 # columna con la cantidad acumulada
    etiqueta_metrica: str        # como se llama esa cantidad en el resumen
    dimensiones: list[str]       # dimensiones estables (no cambian despues del alta)
    columna_estado: str | None = None
    estados_abiertos: list[str] = field(default_factory=list)
    estados_cerrados: list[str] = field(default_factory=list)
    estados_descartados: list[str] = field(default_factory=list)
    # columna de promedio -> columna que la pondera (los promedios de gold son
    # por combinacion, no se pueden promediar sin peso)
    promedios: dict[str, str] = field(default_factory=dict)
    # contadores acumulados que se informan como nivel, no como alta
    contadores: list[str] = field(default_factory=list)
    glosario: str = ""

    @property
    def dimensiones_todas(self) -> list[str]:
        return [*self.dimensiones, self.columna_estado] if self.columna_estado else list(self.dimensiones)


RECLAMOS = CasoDeUso(
    nombre="reclamos",
    prefijo="Reclamos/",
    base_archivo="reclamos_resumen",
    metrica="row_count",
    etiqueta_metrica="reclamos",
    dimensiones=["barrio", "categoria", "prioridad", "origenClasificacion"],
    columna_estado="estado_actual",
    estados_abiertos=["RECIBIDO", "EN_REVISION", "ASIGNADO", "EN_PROCESO"],
    estados_cerrados=["RESUELTO", "CERRADO"],
    estados_descartados=["RECHAZADO"],
    promedios={"tiempo_prom_hasta_estado_actual": "row_count"},
    glosario="""\
- Cada fila es una combinacion de barrio, categoria, prioridad, origen de clasificacion y estado actual.
- estado_actual: RECIBIDO, EN_REVISION, ASIGNADO y EN_PROCESO son reclamos abiertos; RESUELTO y CERRADO son \
reclamos resueltos; RECHAZADO es un cierre sin resolucion.
- origenClasificacion: quien asigno la categoria. MODELO = el clasificador automatico; CIUDADANO = el \
vecino al cargar el reclamo; OPERADOR = una persona del organismo.
- tiempo_prom_hasta_estado_actual son horas desde el ingreso hasta el estado en el que esta cada reclamo.
- Los rechazos de reclamos clasificados por MODELO pueden indicar errores de clasificacion automatica.""",
)

EMERGENCIAS = CasoDeUso(
    nombre="emergencias",
    prefijo="Emergencias y Seguridad/",
    base_archivo="emergencias_resumen",
    metrica="cantidadEmergencias",
    etiqueta_metrica="emergencias",
    dimensiones=["prioridad"],
    columna_estado="estado_actual",
    estados_abiertos=["PENDIENTE", "VALIDADA", "DESPACHADA", "EN_CAMINO", "EN_LUGAR"],
    estados_cerrados=["RESUELTA", "CERRADA"],
    estados_descartados=["DESCARTADA"],
    promedios={"tiempoPromRespuestaDespacho": "cantidadEmergencias",
               "tiempoPromRespuestaLugar": "cantidadEmergencias"},
    glosario="""\
- Cada fila es una combinacion de estado actual y prioridad.
- El ciclo es PENDIENTE -> VALIDADA -> DESPACHADA -> EN_CAMINO -> EN_LUGAR -> RESUELTA -> CERRADA, con la \
rama DESCARTADA para los avisos que no se confirman.
- tiempoPromRespuestaDespacho son los minutos hasta despachar el movil; tiempoPromRespuestaLugar, hasta \
llegar al lugar. En emergencias el tiempo de respuesta es el indicador que importa.
- La prioridad de emergencias es ALTA, MEDIA o BAJA (no tiene CRITICA).""",
)

MOVILIDAD = CasoDeUso(
    nombre="movilidad",
    prefijo="Movilidad Urbana/",
    base_archivo="viajes_resumen",
    metrica="cantidadViajes",
    etiqueta_metrica="viajes",
    dimensiones=["fechaInicio", "estacionInicio", "duracionViaje"],
    promedios={"promDuracion": "cantidadViajes"},
    contadores=["duracionTotalViajes"],
    glosario="""\
- Cada fila es una combinacion de fecha de inicio, estacion de origen y franja de duracion del viaje.
- duracionViaje son franjas: <15min, 15-30min, 30-60min y >60min.
- Los viajes en curso (todavia sin ViajeTerminado) no entran en la tabla hasta que terminan, asi que \
aparecen recien en la foto siguiente.
- A diferencia de los otros dominios, aca la fecha del viaje esta en el grano: se puede leer la actividad \
dia por dia.""",
)

ESPACIOS = CasoDeUso(
    nombre="espacios",
    prefijo="Espacios Publicos y Cultura/",
    base_archivo="reservas_resumen",
    metrica="cantidadTotal",
    etiqueta_metrica="reservas",
    dimensiones=["recursoId", "tipoReserva", "categoria", "zona"],
    promedios={"pctOcupacion": "cantidadTotal"},
    contadores=["cantidadConfirmadas", "cantidadCanceladas", "inscriptos"],
    glosario="""\
- Cada fila es un recurso (espacio fisico o evento) con su tipo, categoria y zona.
- tipoReserva ESPACIO es una reserva de un lugar fisico; EVENTO es una inscripcion a una actividad.
- cantidadConfirmadas y cantidadCanceladas son acumulados sobre el total de reservas de ese recurso: la \
diferencia entre el total y la suma de ambas son las que siguen pendientes.
- pctOcupacion solo aplica a los recursos con cupo maximo definido.""",
)

RESIDUOS = CasoDeUso(
    nombre="residuos",
    prefijo="Gestion de Residuos Inteligente/",
    base_archivo="alertas_resumen",
    metrica="cantidadAlertas",
    etiqueta_metrica="alertas",
    dimensiones=["zona", "tipoAlerta", "prioridad", "rangoNivelLlenado"],
    promedios={"tiempoPromResolucion": "cantidadResueltas"},
    contadores=["cantidadResueltas"],
    glosario="""\
- Cada fila es una combinacion de zona, tipo de alerta, prioridad y rango de nivel de llenado del contenedor.
- tipoAlerta: LLENO, FALLA_SENSOR, VOLCADO e INCENDIO.
- Una alerta se considera resuelta cuando llega la RecoleccionCompletada correspondiente; \
cantidadResueltas es el acumulado de esas, y tiempoPromResolucion son las horas hasta la recoleccion.
- rangoNivelLlenado viene vacio en las alertas de FALLA_SENSOR, porque no hay lectura del sensor.""",
)

CASOS = {c.nombre: c for c in (RECLAMOS, EMERGENCIAS, MOVILIDAD, ESPACIOS, RESIDUOS)}


def obtener(nombre: str) -> CasoDeUso:
    try:
        return CASOS[nombre.strip().lower()]
    except KeyError:
        raise ValueError(f"Caso de uso desconocido: {nombre!r}. Conocidos: {', '.join(CASOS)}") from None
