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
    # columna que vincula cada fila con un caso de uso transversal. Puede no
    # estar en `dimensiones`: si cambia despues del alta (espacios guarda la
    # causa de la ultima modificacion) no sirve para restar fotos, pero si
    # para leer el stock por caso.
    columna_causa: str | None = "causaTipo"
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
- Los rechazos de reclamos clasificados por MODELO pueden indicar errores de clasificacion automatica.
- causaTipo dice si el reclamo nacio de un hecho de otro dominio (EVENTO_CLIMATICO, EVENTO_PUBLICO, \
INCIDENTE_VIAL, RESERVA). Llego con el esquema v2 de ReclamoCreado: los reclamos anteriores lo tienen en \
SIN_DATO. Los reclamos que a su vez generaron trabajo en otros modulos (caso 2) no estan en gold.""",
)

EMERGENCIAS = CasoDeUso(
    nombre="emergencias",
    prefijo="Emergencias y Seguridad/",
    base_archivo="emergencias_resumen",
    metrica="cantidadEmergencias",
    etiqueta_metrica="emergencias",
    dimensiones=["prioridad", "categoria", "causaTipo", "afectaCirculacion"],
    columna_estado="estado_actual",
    estados_abiertos=["PENDIENTE", "VALIDADA", "DESPACHADA", "EN_CAMINO", "EN_LUGAR"],
    estados_cerrados=["RESUELTA", "CERRADA"],
    estados_descartados=["DESCARTADA", "CANCELADA"],
    promedios={"tiempoPromRespuestaDespacho": "cantidadEmergencias",
               "tiempoPromRespuestaLugar": "cantidadEmergencias",
               "tiempoPromResolucion": "cantidadEmergencias"},
    contadores=["criticidadAfectada"],
    glosario="""\
- Cada fila es una combinacion de estado actual, prioridad, categoria, causa y si afecta la circulacion.
- El ciclo es PENDIENTE -> VALIDADA -> DESPACHADA -> EN_CAMINO -> EN_LUGAR -> RESUELTA -> CERRADA, con las \
ramas DESCARTADA (avisos que no se confirman) y CANCELADA, alcanzables solo desde PENDIENTE o VALIDADA.
- causaTipo dice que origino la emergencia en otro dominio: RECLAMO, EVENTO_CLIMATICO, INCIDENTE_VIAL, \
EVENTO_PUBLICO o RESERVA (un evento de ciudadanos). MOVILIDAD_BICICLETA son emergencias durante un viaje \
en bici (caso 5). Vacio = emergencia sin causa externa.
- categoria PREVENTIVA son servicios enviados de forma preventiva, sin una emergencia confirmada.
- afectaCirculacion marca las emergencias que cortan o afectan el transito.
- criticidadAfectada cuenta las emergencias cuya prioridad cambio respecto de la original (por ejemplo, \
escalada por un evento climatico).
- tiempoPromRespuestaDespacho son los minutos hasta despachar el movil y tiempoPromRespuestaLugar hasta \
llegar al lugar; se calculan por prioridad. tiempoPromResolucion son los minutos hasta resolverla y se \
calcula por causaTipo. En emergencias el tiempo de respuesta es el indicador que importa.
- La prioridad es CRITICA, ALTA, MEDIA o BAJA. Valores fuera de esos enums (por ejemplo "Medio" o \
"Ambulancia") son errores de carga del productor: mencionarlos como problema de calidad de datos, no como \
una categoria real.""",
)

MOVILIDAD = CasoDeUso(
    nombre="movilidad",
    prefijo="Movilidad Urbana/",
    base_archivo="movilidad_resumen",
    metrica="cantidadAfectaciones",
    etiqueta_metrica="afectaciones de estaciones",
    dimensiones=["causaTipo"],
    # estacionesAfectadasDistintas no va: son estaciones unicas por causa y
    # sumarlas entre causas contaria dos veces la misma estacion.
    contadores=["cantidadBloqueadas", "cantidadPreventivas", "cantidadRestauradas",
                "cantidadViajesInterrumpidos"],
    glosario="""\
- Cada fila es un causaTipo: el motivo por el que se afecto una estacion urbana (EVENTO_CLIMATICO, \
RECLAMO, EVENTO_PUBLICO, INCIDENTE_VIAL, EMERGENCIA, RESERVA = evento de ciudadanos).
- cantidadAfectaciones cuenta afectaciones de estaciones (una estacion puede afectarse varias veces).
- cantidadBloqueadas son afectaciones que bloquearon la estacion; cantidadPreventivas, las anunciadas antes \
de que empiece la afectacion (tipico de EVENTO_PUBLICO); cantidadRestauradas, las que ya se levantaron.
- cantidadViajesInterrumpidos son viajes que terminaron por esa causa (sobre todo INCIDENTE_VIAL). La fila \
NORMAL es distinta: no es una afectacion, son los viajes finalizados sin incidente (el resto de sus columnas \
vale 0) y sirve de base para comparar contra los interrumpidos.
- Caso 5 (emergencia en bicicleta): en la tabla casos_de_uso sale en 0 porque movilidad no tiene una causa \
propia para eso. Se lee en totales/altas: cantidadViajesInterrumpidos (sobre todo INCIDENTE_VIAL) contra los \
viajes de la fila NORMAL. Las afectaciones con causaTipo EMERGENCIA son emergencias en general, no solo de \
bicicleta.""",
)

ESPACIOS = CasoDeUso(
    nombre="espacios",
    prefijo="Espacios Publicos y Cultura/",
    base_archivo="actividades_resumen",
    metrica="cantidadActividades",
    etiqueta_metrica="actividades",
    # causaTipo no va en las dimensiones: es la causa de la ultima
    # modificacion y cambia despues del alta, asi que restarla entre fotos
    # daria altas negativas. Se lee como stock en la tabla casos_de_uso.
    dimensiones=["categoria", "organizadorTipo", "barrio"],
    columna_estado="estado_actual",
    estados_abiertos=["PROGRAMADA", "PROGRAMADO", "ACTIVE", "EN_CURSO", "SUSPENDIDA"],
    estados_cerrados=["FINALIZADA", "FINALIZADO"],
    estados_descartados=["CANCELADA", "CANCELADO"],
    contadores=["cantidadMasivas", "cantidadAfectadasPorClima", "totalVecesEventoClimatico",
                "totalVecesReclamo", "totalVecesIncidenteVial", "totalVecesAccidenteVial"],
    glosario="""\
- Cada fila es una combinacion de estado actual, categoria, causa de la ultima modificacion, tipo de \
organizador y barrio de las actividades (eventos publicos) de la ciudad.
- organizadorTipo CIUDAD son actividades del gobierno; CIUDADANO, las organizadas por vecinos.
- causaTipo es por que se modifico la actividad: EVENTO_CLIMATICO, RECLAMO, INCIDENTE_VIAL o \
ACCIDENTE_VIAL (son causas distintas, no un error). Vacio = actividad sin modificaciones. Es la causa de \
la ultima modificacion y cambia despues del alta, asi que solo aparece en la tabla casos_de_uso (stock).
- Caso 3 (evento masivo): espacios es el origen, no la causa, asi que en casos_de_uso sale en 0. Se lee en \
cantidadMasivas de la tabla totales.
- Caso 5 (emergencia en bicicleta): se aproxima con ACCIDENTE_VIAL, porque las reservas afectadas por el \
accidente todavia no llegan a gold.
- Caso 6 (reserva de espacio publico): las reservas no llegan a gold; se aproxima con las actividades de \
organizadorTipo CIUDADANO sobre el total.
- SUSPENDIDA no es definitivo: una actividad puede volver a PROGRAMADA. CANCELADA si lo es.
- cantidadMasivas son actividades con capacidad de 500 personas o mas.
- cantidadAfectadasPorClima son actividades canceladas o suspendidas por un evento climatico.
- totalVeces<Causa> cuenta modificaciones (una misma actividad puede modificarse varias veces por la misma \
causa); cantidadActividades cuenta actividades distintas.
- El barrio se deriva de la ubicacion del evento. Categorias con otro formato (por ejemplo "Cultura" o \
"Musica" en vez de CULTURAL) son errores de carga del productor: tratarlos como calidad de datos.""",
)

RESIDUOS = CasoDeUso(
    nombre="residuos",
    prefijo="Gestion de Residuos Inteligente/",
    base_archivo="intervenciones_resumen",
    metrica="cantidadIntervenciones",
    etiqueta_metrica="intervenciones",
    dimensiones=["causaTipo"],
    columna_estado="estado_actual",
    estados_abiertos=["PROGRAMADA"],
    estados_cerrados=["COMPLETADA"],
    estados_descartados=["AFECTADA", "CANCELADA"],
    contadores=["cantidadAfectadas"],
    glosario="""\
- Cada fila es una combinacion de estado actual y causa. Una intervencion es una parada de una cuadrilla \
de recoleccion; varias intervenciones pueden responder al mismo caso.
- causaTipo es por que se programo la intervencion: RECLAMO (reclamos de residuos), EVENTO_PUBLICO \
(limpieza despues de un evento), RESERVA (contenedores cerca de un espacio reservado) o EMERGENCIA.
- PROGRAMADA es una intervencion planificada que todavia no se hizo. AFECTADA es una intervencion que no \
se pudo hacer como estaba planificada (por ejemplo por una tormenta o un corte de calle); COMPLETADA y \
CANCELADA cierran la intervencion. cantidadAfectadas cuenta las que alguna vez fueron afectadas.
- La causa de la afectacion (EVENTO_CLIMATICO, INCIDENTE_VIAL) todavia no llega a gold: la tabla solo trae \
la causa de la programacion. Por eso los casos 1 y 4 aparecen sin registros en este dominio; decilo asi, \
no como que no hubo intervenciones afectadas.""",
)

CASOS = {c.nombre: c for c in (RECLAMOS, EMERGENCIAS, MOVILIDAD, ESPACIOS, RESIDUOS)}


@dataclass(frozen=True)
class CasoTransversal:
    """Uno de los seis casos de uso de la Parte 2: un hecho que se origina en un
    dominio y repercute en los demas. Se reconoce por el causaTipo de cada fila."""
    numero: int
    nombre: str
    causas: tuple[str, ...]

    @property
    def etiqueta(self) -> str:
        return f"Caso {self.numero} - {self.nombre}"


# El caso 5 no tiene un causaTipo propio en el contrato: emergencias lo manda
# como MOVILIDAD_BICICLETA, espacios como ACCIDENTE_VIAL y movilidad lo lee en
# los viajes interrumpidos (ver el glosario de cada dominio). EMERGENCIA no va:
# en movilidad y residuos son emergencias en general, no las de bicicleta.
CASOS_TRANSVERSALES = (
    CasoTransversal(1, "Evento climatico", ("EVENTO_CLIMATICO",)),
    CasoTransversal(2, "Reclamo ciudadano", ("RECLAMO",)),
    CasoTransversal(3, "Evento masivo", ("EVENTO_PUBLICO",)),
    CasoTransversal(4, "Incidente vial", ("INCIDENTE_VIAL",)),
    CasoTransversal(5, "Emergencia en bicicleta", ("MOVILIDAD_BICICLETA", "ACCIDENTE_VIAL")),
    CasoTransversal(6, "Reserva de espacio publico", ("RESERVA",)),
)


def obtener(nombre: str) -> CasoDeUso:
    try:
        return CASOS[nombre.strip().lower()]
    except KeyError:
        raise ValueError(f"Caso de uso desconocido: {nombre!r}. Conocidos: {', '.join(CASOS)}") from None
