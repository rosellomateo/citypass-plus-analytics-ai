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
class TablaComplementaria:
    """Otra tabla gold del mismo dominio, archivada cada domingo igual que la
    principal (<base>_<WW>_<YYYY>.parquet en la misma carpeta)."""
    base_archivo: str
    metrica: str
    etiqueta: str
    criterios_casos: dict[int, tuple[str, tuple[str, ...] | None]]

    @property
    def columnas_criterio(self) -> list[str]:
        return list(dict.fromkeys(c for c, _ in self.criterios_casos.values()))


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
    # numero de caso transversal -> (columna, valores) cuando el dominio lo
    # reconoce por otra columna y no por columna_causa. valores=None = todas
    # las filas. Las columnas son opcionales: si un snapshot viejo no las trae
    # quedan en SIN_DATO (el caso da 0 esa semana).
    criterios_casos: dict[int, tuple[str, tuple[str, ...] | None]] = field(default_factory=dict)
    # contadores que solo se pueden sumar dentro de un caso (por ejemplo
    # estaciones distintas por causa): van en casos_de_uso, nunca en totales.
    contadores_por_caso: list[str] = field(default_factory=list)
    # otras tablas gold del dominio con su propia foto semanal, que aportan
    # cifras a casos_de_uso (no a las altas)
    complementarias: tuple["TablaComplementaria", ...] = ()
    glosario: str = ""
    # columna como la publica gold -> nombre que usa este caso (gold renombra
    # columnas y los snapshots viejos traen el nombre anterior).
    renombres: dict[str, str] = field(default_factory=dict)

    @property
    def columnas_criterio(self) -> list[str]:
        columnas = [c for c, _ in self.criterios_casos.values()]
        if self.columna_causa:
            columnas.insert(0, self.columna_causa)
        return [c for c in dict.fromkeys(columnas) if c not in self.dimensiones_todas]

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
    # Caso 2: reclamos que generaron trabajo en otro modulo (la cuenta inversa
    # de causaTipo = RECLAMO). Caso 5: reclamos vinculados a una emergencia en bici.
    criterios_casos={2: ("afectaOtrosModulos", ("True",)),
                     5: ("vinculadoEmergenciaBici", ("True",))},
    glosario="""\
- Cada fila es una combinacion de barrio, categoria, prioridad, origen de clasificacion y estado actual.
- estado_actual: RECIBIDO, EN_REVISION, ASIGNADO y EN_PROCESO son reclamos abiertos; RESUELTO y CERRADO son \
reclamos resueltos; RECHAZADO es un cierre sin resolucion.
- origenClasificacion: quien asigno la categoria. MODELO = el clasificador automatico; CIUDADANO = el \
vecino al cargar el reclamo; OPERADOR = una persona del organismo.
- tiempo_prom_hasta_estado_actual son horas desde el ingreso hasta el estado en el que esta cada reclamo.
- Los rechazos de reclamos clasificados por MODELO pueden indicar errores de clasificacion automatica.
- causaTipo dice si el reclamo nacio de un hecho de otro dominio (EVENTO_CLIMATICO, EVENTO_PUBLICO, \
INCIDENTE_VIAL, RESERVA): de ahi salen los casos 1, 3, 4 y 6. Llego con el esquema v2 de ReclamoCreado: \
los reclamos anteriores lo tienen en SIN_DATO.
- Caso 2 (reclamo ciudadano): afectaOtrosModulos = reclamos que generaron trabajo en otro modulo (residuos, \
movilidad, espacios o emergencias los citan como causa). Es lo que el caso pide: reclamos que afectan a los \
demas modulos.
- Caso 5 (emergencia en bicicleta): vinculadoEmergenciaBici = reclamos de la via vinculados a una emergencia \
durante un viaje en bici. Comparalo contra el resto de los reclamos de via (categorias BACHES y TRANSITO).
- Si en una semana esas dos columnas no existian todavia en gold, el caso da 0 por falta de dato, no porque \
no haya pasado: aclaralo.""",
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
    # Afectaciones de estaciones por causa (antes movilidad_resumen).
    base_archivo="viajes_resumen",
    metrica="cantidadAfectaciones",
    etiqueta_metrica="afectaciones de estaciones",
    dimensiones=["causaTipo"],
    # estacionesAfectadasDistintas no va: son estaciones unicas por causa y
    # sumarlas entre causas contaria dos veces la misma estacion.
    contadores=["cantidadBloqueadas", "cantidadPreventivas", "cantidadRestauradas",
                "cantidadViajesInterrumpidos"],
    # Por caso si: cada caso es un unico causaTipo, una sola fila.
    contadores_por_caso=["estacionesAfectadasDistintas", "estacionesBloqueadasDistintas"],
    glosario="""\
- Cada fila es un causaTipo: el motivo por el que se afecto una estacion urbana (EVENTO_CLIMATICO, \
RECLAMO, EVENTO_PUBLICO, INCIDENTE_VIAL, EMERGENCIA, RESERVA = evento de ciudadanos).
- cantidadAfectaciones cuenta afectaciones de estaciones (una estacion puede afectarse varias veces).
- cantidadBloqueadas son afectaciones que bloquearon la estacion; cantidadPreventivas, las anunciadas antes \
de que empiece la afectacion (tipico de EVENTO_PUBLICO); cantidadRestauradas, las que ya se levantaron.
- estacionesAfectadasDistintas y estacionesBloqueadasDistintas son estaciones unicas dentro de cada causa \
(una estacion bloqueada dos veces cuenta una): solo aparecen en casos_de_uso. Para el caso 1 la cifra que \
pide el caso son las estaciones bloqueadas distintas por evento climatico.
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
    complementarias=(
        TablaComplementaria(
            base_archivo="espacios_afectados_resumen",
            metrica="cantidadAfectaciones",
            etiqueta="espacios_afectados",
            criterios_casos={1: ("causaTipo", ("EVENTO_CLIMATICO",)),
                             2: ("causaTipo", ("RECLAMO",)),
                             4: ("causaTipo", ("INCIDENTE_VIAL",))},
        ),
        TablaComplementaria(
            base_archivo="reservas_resumen",
            metrica="cantidadReservas",
            etiqueta="reservas",
            criterios_casos={5: ("afectada", ("True",)),
                             6: ("tipoReserva", None)},
        ),
    ),
    glosario="""\
- Cada fila es una combinacion de estado actual, categoria, causa de la ultima modificacion, tipo de \
organizador y barrio de las actividades (eventos publicos) de la ciudad.
- organizadorTipo CIUDAD son actividades del gobierno; CIUDADANO, las organizadas por vecinos.
- causaTipo es por que se modifico la actividad: EVENTO_CLIMATICO, RECLAMO, INCIDENTE_VIAL o \
ACCIDENTE_VIAL (son causas distintas, no un error). Vacio = actividad sin modificaciones. Es la causa de \
la ultima modificacion y cambia despues del alta, asi que solo aparece en la tabla casos_de_uso (stock).
- Caso 3 (evento masivo): espacios es el origen, no la causa, asi que en casos_de_uso sale en 0. Se lee en \
cantidadMasivas de la tabla totales.
- casos_de_uso trae filas de tres tablas (columna `tabla`): actividades (la principal), espacios_afectados \
(afectaciones de espacios publicos por causa: casos 1, 2 y 4, la metrica que piden los casos 2 y 4) y \
reservas (caso 5 = reservas afectadas, caso 6 = todas las reservas ciudadanas).
- Caso 5 (emergencia en bicicleta): la cifra son las reservas afectadas; ACCIDENTE_VIAL en actividades es \
un dato de apoyo.
- Caso 6 (reserva de espacio publico): compara las reservas contra el total de actividades (`acumulado_total`).
- Si una semana no tiene foto de espacios_afectados o reservas (tablas nuevas), esas filas no aparecen: \
decilo como falta de dato.
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
    # Gold renombro causaTipo (causa de la programacion) a causaProgramacion.
    renombres={"causaProgramacion": "causaTipo", "causaProgramada": "causaTipo"},
    metrica="cantidadIntervenciones",
    etiqueta_metrica="intervenciones",
    dimensiones=["causaTipo"],
    columna_estado="estado_actual",
    estados_abiertos=["PROGRAMADA"],
    estados_cerrados=["COMPLETADA"],
    estados_descartados=["AFECTADA", "CANCELADA"],
    contadores=["cantidadAfectadas", "cantidadCanceladas", "cantidadCompletadas"],
    # camionesDistintos no va: es por fila y no se puede sumar.
    criterios_casos={1: ("causaTipoAfectacion", ("EVENTO_CLIMATICO",)),
                     4: ("causaTipoAfectacion", ("INCIDENTE_VIAL",)),
                     5: ("origenProgramacion", ("EMERGENCIA",))},
    glosario="""\
- Cada fila es una combinacion de estado actual y causa. Una intervencion es una parada de una cuadrilla \
de recoleccion; varias intervenciones pueden responder al mismo caso.
- causaTipo es por que se programo la intervencion: RECLAMO (reclamos de residuos), EVENTO_PUBLICO \
(limpieza despues de un evento), RESERVA (contenedores cerca de un espacio reservado) o EMERGENCIA.
- PROGRAMADA es una intervencion planificada que todavia no se hizo. AFECTADA es una intervencion que no \
se pudo hacer como estaba planificada (por ejemplo por una tormenta o un corte de calle); COMPLETADA y \
CANCELADA cierran la intervencion. cantidadAfectadas, cantidadCanceladas y cantidadCompletadas cuentan las \
que alguna vez quedaron en ese estado.
- causaTipo es la causa de la PROGRAMACION (casos 2, 3 y 6) y causaTipoAfectacion la de la AFECTACION o \
cancelacion: el caso 1 son las cuadrillas afectadas por clima (causaTipoAfectacion = EVENTO_CLIMATICO) y el \
caso 4 las afectadas por incidentes viales (causaTipoAfectacion = INCIDENTE_VIAL).
- Caso 5 (emergencia en bicicleta): intervenciones programadas por una emergencia (origenProgramacion = \
EMERGENCIA), para comparar contra las programadas por alertas propias de residuos.
- Si en una semana causaTipoAfectacion u origenProgramacion no existian todavia en gold, esos casos dan 0 \
por falta de dato: aclaralo.""",
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
    CasoTransversal(1, "Evento climático", ("EVENTO_CLIMATICO",)),
    CasoTransversal(2, "Reclamo ciudadano", ("RECLAMO",)),
    CasoTransversal(3, "Evento masivo", ("EVENTO_PUBLICO",)),
    CasoTransversal(4, "Incidente vial", ("INCIDENTE_VIAL",)),
    CasoTransversal(5, "Emergencia en bicicleta", ("MOVILIDAD_BICICLETA", "ACCIDENTE_VIAL")),
    CasoTransversal(6, "Reserva de espacio público", ("RESERVA",)),
)


def obtener(nombre: str) -> CasoDeUso:
    try:
        return CASOS[nombre.strip().lower()]
    except KeyError:
        raise ValueError(f"Caso de uso desconocido: {nombre!r}. Conocidos: {', '.join(CASOS)}") from None
