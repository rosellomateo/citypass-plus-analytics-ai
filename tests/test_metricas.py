"""Las tablas que recibe el LLM. Es la parte con cuentas: los numeros estan verificados a mano."""
from __future__ import annotations

import pandas as pd
import pytest

from analisis_semanal import casos, datos, metricas
from conftest import FILAS_W37, FILAS_W38, df_reclamos, snapshot

COLUMNAS_MOV = ["causaTipo", "cantidadAfectaciones", "estacionesAfectadasDistintas",
                "cantidadBloqueadas", "cantidadPreventivas", "cantidadRestauradas",
                "cantidadViajesInterrumpidos"]
FILAS_MOV_W37 = [("EVENTO_CLIMATICO", 5, 4, 3, 0, 1, 1),
                 ("NORMAL", 0, 0, 0, 0, 0, 20)]
FILAS_MOV_W38 = [("EVENTO_CLIMATICO", 7, 6, 5, 0, 2, 1),
                 ("INCIDENTE_VIAL", 4, 4, 0, 0, 1, 3),
                 ("NORMAL", 0, 0, 0, 0, 0, 26)]

COLUMNAS_EME = ["estado_actual", "prioridad", "categoria", "causaTipo", "afectaCirculacion",
                "cantidadEmergencias", "criticidadAfectada",
                "tiempoPromRespuestaDespacho", "tiempoPromRespuestaLugar"]
FILAS_EME_W37 = [("RESUELTA", "ALTA", "INCENDIO", None, True, 10, 1, 6.0, 12.0),
                 ("DESCARTADA", "BAJA", "OTRO", None, False, 5, 0, None, None)]
FILAS_EME_W38 = [("RESUELTA", "ALTA", "INCENDIO", None, True, 14, 2, 8.0, 15.0),
                 ("DESCARTADA", "BAJA", "OTRO", None, False, 5, 0, None, None)]


def df_movilidad(filas) -> pd.DataFrame:
    return pd.DataFrame(filas, columns=COLUMNAS_MOV)


def df_emergencias(filas) -> pd.DataFrame:
    return pd.DataFrame(filas, columns=COLUMNAS_EME)


def ventana(caso, fotos) -> datos.Ventana:
    return datos.Ventana([snapshot(caso, semana, df) for semana, df in fotos])


# --------------------------------------------------------------------------
# Altas = foto de la semana - foto anterior
# --------------------------------------------------------------------------

def test_las_altas_son_la_resta_entre_fotos_consecutivas(ventana_reclamos):
    """W37 tiene 19 reclamos y W38 tiene 26: 7 altas, repartidas 2 Centro, 2 Norte y 3 Sur."""
    altas = metricas.altas_detalladas(ventana_reclamos)

    assert altas["altas"].sum() == 7
    assert set(altas["semana"]) == {"2026-W38"}
    assert altas.groupby("barrio")["altas"].sum().to_dict() == {"Centro": 2, "Norte": 2, "Sur": 3}


def test_un_cambio_de_estado_no_genera_altas(ventana_reclamos):
    """En Centro 2 reclamos pasaron de RECIBIDO a RESUELTO. Si la resta incluyera
    el estado darian -2 y +2; agrupando sin estado quedan las 2 altas reales."""
    altas = metricas.altas_detalladas(ventana_reclamos)

    assert "estado_actual" not in altas.columns
    assert (altas["altas"] > 0).all()


def test_una_combinacion_nueva_aparece_completa(ventana_reclamos):
    altas = metricas.altas_detalladas(ventana_reclamos)
    sur = altas[altas["barrio"] == "Sur"].iloc[0]

    assert sur["categoria"] == "RESIDUOS"
    assert sur["origenClasificacion"] == "OPERADOR"
    assert sur["altas"] == 3


def test_sin_movimiento_entre_fotos_no_hay_altas(caso_reclamos):
    quieta = ventana(caso_reclamos, [(37, df_reclamos(FILAS_W37)), (38, df_reclamos(FILAS_W37))])

    altas = metricas.altas_detalladas(quieta)

    assert altas.empty
    assert list(altas.columns) == ["semana", *caso_reclamos.dimensiones, "altas"]


def test_altas_por_dimension_abre_una_dimension_por_vez(ventana_reclamos):
    largo = metricas.altas_por_dimension(ventana_reclamos)

    assert list(largo.columns) == ["semana", "dimension", "valor", "altas"]
    assert set(largo["dimension"]) == set(casos.RECLAMOS.dimensiones)
    # Cada dimension reparte las mismas 7 altas de la semana.
    assert largo.groupby("dimension")["altas"].sum().unique().tolist() == [7]


def test_altas_por_dimension_vacia_cuando_no_hubo_movimiento(caso_reclamos):
    quieta = ventana(caso_reclamos, [(37, df_reclamos(FILAS_W37)), (38, df_reclamos(FILAS_W37))])

    assert metricas.altas_por_dimension(quieta).empty


def test_el_detalle_es_solo_de_la_semana_analizada_y_recorta_la_cola(caso_reclamos):
    nueva = ("Oeste", "ARBOLADO", "BAJA", "MODELO", "RECIBIDO", 9, 1.0)
    tres = ventana(caso_reclamos, [(36, df_reclamos(FILAS_W37)),
                                   (37, df_reclamos(FILAS_W38)),
                                   (38, df_reclamos([*FILAS_W38, nueva]))])

    detalle = metricas.altas_detalle_semana(tres, top=1)

    assert set(detalle["semana"]) == {"2026-W38"}
    assert len(detalle) == 1
    assert detalle.iloc[0]["barrio"] == "Oeste"  # la combinacion mas grande primero


# --------------------------------------------------------------------------
# Totales: una fila por semana
# --------------------------------------------------------------------------

def test_totales_de_la_semana_analizada(ventana_reclamos):
    fila = metricas.totales(ventana_reclamos).iloc[-1]

    assert fila["semana"] == "2026-W38"
    assert fila["altas_semana"] == 7
    assert fila["acumulado_total"] == 26
    assert fila["abiertos"] == 17      # 8 + 6 + 3 en RECIBIDO
    assert fila["cerrados"] == 9       # RESUELTO
    assert fila["descartados"] == 0    # no hay RECHAZADO


def test_la_foto_base_no_tiene_altas(ventana_reclamos):
    """Es el punto de partida de la resta, no una semana sin actividad."""
    fila = metricas.totales(ventana_reclamos).iloc[0]

    assert fila["semana"] == "2026-W37"
    assert pd.isna(fila["altas_semana"])
    assert fila["acumulado_total"] == 19


def test_el_promedio_se_pondera_por_la_cantidad_de_cada_fila(ventana_reclamos):
    """(6*8 + 22*9 + 3*6 + 1*3) / 26 = 10.3 horas. El promedio simple daria 8.0."""
    fila = metricas.totales(ventana_reclamos).iloc[-1]

    assert fila["tiempo_prom_hasta_estado_actual"] == pytest.approx(10.3)


# --------------------------------------------------------------------------
# Stock por estado
# --------------------------------------------------------------------------

def test_estado_cruza_con_prioridad_cuando_el_dominio_la_tiene(ventana_reclamos):
    tabla = metricas.estado(ventana_reclamos)
    actual = tabla[tabla["semana"] == "2026-W38"]

    assert list(tabla.columns)[:4] == ["semana", "estado_actual", "prioridad", "cantidad"]
    recibidos_alta = actual[(actual["estado_actual"] == "RECIBIDO") & (actual["prioridad"] == "ALTA")]
    assert recibidos_alta.iloc[0]["cantidad"] == 8
    assert actual["cantidad"].sum() == 26


def test_un_dominio_sin_estado_no_tiene_tabla_de_estado():
    movilidad = ventana(casos.MOVILIDAD, [(37, df_movilidad(FILAS_MOV_W37)),
                                          (38, df_movilidad(FILAS_MOV_W38))])

    assert metricas.estado(movilidad) is None
    assert "estado" not in metricas.resumen_tablas(movilidad)


def test_resumen_tablas_incluye_el_estado_cuando_corresponde(ventana_reclamos):
    assert set(metricas.resumen_tablas(ventana_reclamos)) == {"totales", "altas", "altas_detalle", "estado",
                                                              "casos_de_uso"}


# --------------------------------------------------------------------------
# Otros dominios: contadores y promedios sin dato
# --------------------------------------------------------------------------

def test_movilidad_lee_las_altas_por_causa():
    movilidad = ventana(casos.MOVILIDAD, [(37, df_movilidad(FILAS_MOV_W37)),
                                          (38, df_movilidad(FILAS_MOV_W38))])

    altas = metricas.altas_detalladas(movilidad)

    assert altas["altas"].sum() == 6       # +2 climaticas, +4 incidentes viales
    por_causa = altas.set_index("causaTipo")["altas"]
    assert por_causa["INCIDENTE_VIAL"] == 4
    assert por_causa["EVENTO_CLIMATICO"] == 2


def test_los_contadores_se_suman_y_se_informan_como_nivel():
    movilidad = ventana(casos.MOVILIDAD, [(37, df_movilidad(FILAS_MOV_W37)),
                                          (38, df_movilidad(FILAS_MOV_W38))])

    fila = metricas.totales(movilidad).iloc[-1]

    assert fila["acumulado_total"] == 11   # 7 + 4 afectaciones (NORMAL no es una afectacion)
    assert fila["altas_semana"] == 6
    assert fila["cantidadBloqueadas"] == 5
    assert fila["cantidadViajesInterrumpidos"] == 30


def test_las_estaciones_distintas_no_se_suman_entre_causas():
    """Son estaciones unicas por causa: sumarlas contaria dos veces la misma estacion."""
    movilidad = ventana(casos.MOVILIDAD, [(37, df_movilidad(FILAS_MOV_W37)),
                                          (38, df_movilidad(FILAS_MOV_W38))])

    assert "estacionesAfectadasDistintas" not in metricas.totales(movilidad).columns


def test_las_filas_sin_promedio_no_cuentan_como_cero():
    """Las emergencias descartadas no tienen tiempo de despacho: promediarlas
    como 0 hundiria el indicador. 8.0 es el promedio de las que si lo tienen."""
    emergencias = ventana(casos.EMERGENCIAS, [(37, df_emergencias(FILAS_EME_W37)),
                                              (38, df_emergencias(FILAS_EME_W38))])

    fila = metricas.totales(emergencias).iloc[-1]

    assert fila["tiempoPromRespuestaDespacho"] == pytest.approx(8.0)
    assert fila["criticidadAfectada"] == 2
    assert fila["cerrados"] == 14
    assert fila["descartados"] == 5


def test_un_promedio_que_gold_todavia_no_publica_informa_nulo():
    """tiempoPromResolucion se sumo a gold despues: los snapshots viejos no lo traen."""
    emergencias = ventana(casos.EMERGENCIAS, [(37, df_emergencias(FILAS_EME_W37)),
                                              (38, df_emergencias(FILAS_EME_W38))])

    assert metricas.totales(emergencias).iloc[-1]["tiempoPromResolucion"] is None


def test_un_snapshot_sin_ningun_promedio_informa_nulo():
    sin_dato = [("PENDIENTE", "ALTA", "INCENDIO", None, True, 10, 0, None, None)]
    emergencias = ventana(casos.EMERGENCIAS, [(37, df_emergencias(sin_dato)),
                                              (38, df_emergencias(sin_dato))])

    assert metricas.totales(emergencias).iloc[-1]["tiempoPromRespuestaDespacho"] is None


# --------------------------------------------------------------------------
# Controles de calidad
# --------------------------------------------------------------------------

def test_altas_negativas_se_cuentan_en_vez_de_taparse(caso_reclamos):
    """Una foto con menos registros que la anterior (reproceso o borrado) deja
    altas negativas: el pipeline las informa en la metadata."""
    encogida = ventana(caso_reclamos, [(37, df_reclamos(FILAS_W38)), (38, df_reclamos(FILAS_W37))])

    assert metricas.altas_negativas(metricas.altas_detalladas(encogida)) == 3


def test_sin_altas_no_hay_negativas():
    assert metricas.altas_negativas(pd.DataFrame(columns=["altas"])) == 0


def test_a_csv_no_escribe_el_indice_y_redondea(ventana_reclamos):
    csv = metricas.a_csv(metricas.totales(ventana_reclamos))

    assert csv.splitlines()[0].startswith("semana,altas_semana,acumulado_total")
    assert "10.3" in csv


def test_un_dominio_todavia_sin_datos_no_rompe(caso_reclamos):
    """Un dominio recien conectado archiva fotos vacias hasta que llegan los primeros eventos."""
    vacia = ventana(caso_reclamos, [(37, df_reclamos([])), (38, df_reclamos([]))])

    fila = metricas.totales(vacia).iloc[-1]

    assert fila["acumulado_total"] == 0
    assert fila["altas_semana"] == 0
    assert fila["tiempo_prom_hasta_estado_actual"] is None
    assert metricas.altas_detalladas(vacia).empty


# --------------------------------------------------------------------------
# Casos de uso transversales (stock por causaTipo)
# --------------------------------------------------------------------------

COLUMNAS_ESP = ["estado_actual", "categoria", "causaTipo", "organizadorTipo", "barrio",
                "cantidadActividades", "cantidadMasivas"]
# Semana 37: 3 actividades programadas sin modificar.
FILAS_ESP_W37 = [("PROGRAMADA", "CULTURAL", None, "CIUDAD", "Centro", 3, 1)]
# Semana 38: una de esas 3 se cancelo por clima (cambia su causaTipo) y entro una nueva.
FILAS_ESP_W38 = [("PROGRAMADA", "CULTURAL", None, "CIUDAD", "Centro", 2, 1),
                 ("CANCELADA", "CULTURAL", "EVENTO_CLIMATICO", "CIUDAD", "Centro", 1, 0),
                 ("PROGRAMADA", "CULTURAL", None, "CIUDADANO", "Norte", 1, 0)]


def df_espacios(filas) -> pd.DataFrame:
    return pd.DataFrame(filas, columns=COLUMNAS_ESP)


@pytest.fixture
def ventana_espacios():
    return ventana(casos.ESPACIOS, [(37, df_espacios(FILAS_ESP_W37)), (38, df_espacios(FILAS_ESP_W38))])


def test_un_cambio_de_causa_en_espacios_no_genera_altas_negativas(ventana_espacios):
    """causaTipo de espacios es la causa de la ultima modificacion: si fuera
    dimension, la actividad cancelada por clima restaria 1 del bucket sin causa."""
    altas = metricas.altas_detalladas(ventana_espacios)

    assert metricas.altas_negativas(altas) == 0
    assert altas["altas"].sum() == 1


def test_casos_de_uso_trae_las_seis_filas_por_semana_aunque_valgan_cero(ventana_espacios):
    tabla = metricas.casos_de_uso(ventana_espacios)

    assert len(tabla) == 12
    assert set(tabla["caso_de_uso"]) == {t.etiqueta for t in casos.CASOS_TRANSVERSALES}


def test_casos_de_uso_lee_el_stock_por_causa_y_su_variacion(ventana_espacios):
    tabla = metricas.casos_de_uso(ventana_espacios).set_index(["semana", "caso_de_uso"])
    clima = tabla.loc[("2026-W38", "Caso 1 - Evento climático")]

    assert clima["cantidad"] == 1
    assert clima["variacion_semana"] == 1
    assert pd.isna(tabla.loc[("2026-W37", "Caso 1 - Evento climático"), "variacion_semana"])  # foto base


def test_casos_de_uso_agrupa_las_causas_del_caso_5():
    df = df_espacios([("CANCELADA", "CULTURAL", "ACCIDENTE_VIAL", "CIUDAD", "Centro", 2, 0)])
    v = ventana(casos.ESPACIOS, [(37, df), (38, df)])

    tabla = metricas.casos_de_uso(v).set_index(["semana", "caso_de_uso"])

    assert tabla.loc[("2026-W38", "Caso 5 - Emergencia en bicicleta"), "cantidad"] == 2


def test_una_foto_sin_columna_de_causa_queda_en_sin_dato():
    """Las fotos anteriores a que gold publicara causaTipo no tiran la corrida."""
    viejo = df_espacios(FILAS_ESP_W37).drop(columns=["causaTipo"])
    v = ventana(casos.ESPACIOS, [(37, viejo), (38, df_espacios(FILAS_ESP_W38))])

    tabla = metricas.casos_de_uso(v)

    assert tabla[tabla["semana"] == "2026-W37"]["cantidad"].sum() == 0


# --------------------------------------------------------------------------
# Casos medidos con otras columnas y tablas complementarias (gold ee1c2a8)
# --------------------------------------------------------------------------

def _fila_caso(tabla, semana, numero, origen):
    etiqueta = next(t.etiqueta for t in casos.CASOS_TRANSVERSALES if t.numero == numero)
    fila = tabla[(tabla["semana"] == semana) & (tabla["caso_de_uso"] == etiqueta) & (tabla["tabla"] == origen)]
    assert len(fila) == 1, fila
    return fila.iloc[0]


def test_reclamos_mide_los_casos_2_y_5_con_sus_columnas_y_tolera_fotos_viejas():
    """La W37 es anterior a afectaOtrosModulos/vinculadoEmergenciaBici: da 0 sin romper."""
    viejo = df_reclamos(FILAS_W37)
    nuevo = df_reclamos(FILAS_W38).assign(
        causaTipo=["EVENTO_CLIMATICO", None, None, None],
        afectaOtrosModulos=[True, False, True, False],
        vinculadoEmergenciaBici=[False, False, False, True],
    )
    v = ventana(casos.RECLAMOS, [(37, viejo), (38, nuevo)])

    tabla = metricas.casos_de_uso(v)

    assert _fila_caso(tabla, "2026-W38", 2, "reclamos")["cantidad"] == 8 + 6
    assert _fila_caso(tabla, "2026-W38", 2, "reclamos")["criterio"] == "afectaOtrosModulos=True"
    assert _fila_caso(tabla, "2026-W38", 5, "reclamos")["cantidad"] == 3
    assert _fila_caso(tabla, "2026-W38", 1, "reclamos")["cantidad"] == 8
    assert _fila_caso(tabla, "2026-W37", 2, "reclamos")["cantidad"] == 0


COLUMNAS_RES = ["estado_actual", "causaTipo", "causaTipoAfectacion", "barrio", "origenProgramacion",
                "cantidadIntervenciones", "cantidadAfectadas", "cantidadCanceladas", "cantidadCompletadas",
                "camionesDistintos"]
FILAS_RES = [("AFECTADA", "RECLAMO", "EVENTO_CLIMATICO", "Centro", "NINGUNO", 4, 4, 0, 0, 2),
             ("CANCELADA", "EVENTO_PUBLICO", "INCIDENTE_VIAL", "Norte", "ALERTA", 3, 3, 3, 0, 1),
             ("COMPLETADA", "RESERVA", None, "Sur", "EMERGENCIA", 2, 0, 0, 2, 1)]


def test_residuos_lee_la_causa_de_la_afectacion_y_el_origen_de_la_programacion():
    df = pd.DataFrame(FILAS_RES, columns=COLUMNAS_RES)
    v = ventana(casos.RESIDUOS, [(37, df), (38, df)])

    tabla = metricas.casos_de_uso(v)

    assert _fila_caso(tabla, "2026-W38", 1, "intervenciones")["cantidad"] == 4   # clima en la afectacion
    assert _fila_caso(tabla, "2026-W38", 2, "intervenciones")["cantidad"] == 4   # reclamo en la programacion
    assert _fila_caso(tabla, "2026-W38", 4, "intervenciones")["cantidad"] == 3
    assert _fila_caso(tabla, "2026-W38", 5, "intervenciones")["cantidad"] == 2
    assert _fila_caso(tabla, "2026-W38", 4, "intervenciones")["cantidadCanceladas"] == 3
    assert "camionesDistintos" not in metricas.totales(v).columns


def test_las_estaciones_distintas_van_por_caso_y_nunca_en_totales():
    movilidad = ventana(casos.MOVILIDAD, [(37, df_movilidad(FILAS_MOV_W37)),
                                          (38, df_movilidad(FILAS_MOV_W38))])

    tabla = metricas.casos_de_uso(movilidad)

    assert _fila_caso(tabla, "2026-W38", 1, "viajes")["estacionesAfectadasDistintas"] == 6
    assert "estacionesAfectadasDistintas" not in metricas.totales(movilidad).columns


AFECTADOS = pd.DataFrame([("RECLAMO", "CIERRE", "PLAZA", "Centro", 5, 3),
                          ("EVENTO_CLIMATICO", "CIERRE", "PLAZA", "Norte", 2, 2)],
                         columns=["causaTipo", "tipoAfectacion", "categoria", "barrio",
                                  "cantidadAfectaciones", "espaciosDistintos"])
RESERVAS = pd.DataFrame([("ESPACIO", "CONFIRMADA", False, None, "Centro", 6, 120),
                         ("ESPACIO", "CANCELADA", True, "CANCELAR", "Sur", 2, 40)],
                        columns=["tipoReserva", "estado_actual", "afectada", "accionAfectacion", "barrio",
                                 "cantidadReservas", "cantidadPersonas"])


def _snap_espacios(semana, df, extras):
    ruta = f"gold/{casos.ESPACIOS.prefijo}{casos.ESPACIOS.base_archivo}_{semana}_2026.parquet"
    return datos.construir_snapshot(casos.ESPACIOS, ruta, df, extras)


def test_espacios_suma_filas_de_las_tablas_complementarias():
    base = df_espacios(FILAS_ESP_W37)
    v = datos.Ventana([
        _snap_espacios(37, base, {"espacios_afectados": None, "reservas": None}),
        _snap_espacios(38, df_espacios(FILAS_ESP_W38), {"espacios_afectados": AFECTADOS, "reservas": RESERVAS}),
    ])

    tabla = metricas.casos_de_uso(v)

    assert _fila_caso(tabla, "2026-W38", 2, "espacios_afectados")["cantidad"] == 5
    assert _fila_caso(tabla, "2026-W38", 1, "espacios_afectados")["cantidad"] == 2
    assert _fila_caso(tabla, "2026-W38", 6, "reservas")["cantidad"] == 8
    assert _fila_caso(tabla, "2026-W38", 5, "reservas")["cantidad"] == 2
    # Sin foto la semana anterior no hay contra que restar.
    assert pd.isna(_fila_caso(tabla, "2026-W38", 6, "reservas")["variacion_semana"])
    # La semana sin foto de las complementarias no inventa filas.
    assert set(tabla[tabla["semana"] == "2026-W37"]["tabla"]) == {"actividades"}


def test_la_variacion_no_resta_contra_una_semana_salteada():
    extras = {"espacios_afectados": AFECTADOS, "reservas": RESERVAS}
    df = df_espacios(FILAS_ESP_W38)
    v = datos.Ventana([
        _snap_espacios(36, df, extras),
        _snap_espacios(37, df, {"espacios_afectados": None, "reservas": None}),
        _snap_espacios(38, df, extras),
    ])

    tabla = metricas.casos_de_uso(v)

    assert pd.isna(_fila_caso(tabla, "2026-W38", 6, "reservas")["variacion_semana"])
    assert _fila_caso(tabla, "2026-W38", 1, "actividades")["variacion_semana"] == 0
