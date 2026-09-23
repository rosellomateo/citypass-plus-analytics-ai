"""Las tablas que recibe el LLM. Es la parte con cuentas: los numeros estan verificados a mano."""
from __future__ import annotations

import pandas as pd
import pytest

from analisis_semanal import casos, datos, metricas
from conftest import FILAS_W37, FILAS_W38, df_reclamos, snapshot

COLUMNAS_MOV = ["fechaInicio", "estacionInicio", "duracionViaje",
                "cantidadViajes", "promDuracion", "duracionTotalViajes"]
FILAS_MOV_W37 = [("2026-09-07", "Estacion Centro", "<15min", 10, 10.0, 100.0)]
FILAS_MOV_W38 = [("2026-09-07", "Estacion Centro", "<15min", 10, 10.0, 100.0),
                 ("2026-09-15", "Estacion Norte", "15-30min", 4, 20.0, 80.0)]

COLUMNAS_RES = ["zona", "tipoAlerta", "prioridad", "rangoNivelLlenado",
                "cantidadAlertas", "cantidadResueltas", "tiempoPromResolucion"]
FILAS_RES_W37 = [("Norte", "LLENO", "ALTA", "80-100", 10, 4, 6.0),
                 ("Sur", "FALLA_SENSOR", "BAJA", None, 5, 0, None)]
FILAS_RES_W38 = [("Norte", "LLENO", "ALTA", "80-100", 14, 6, 8.0),
                 ("Sur", "FALLA_SENSOR", "BAJA", None, 5, 0, None)]


def df_movilidad(filas) -> pd.DataFrame:
    return pd.DataFrame(filas, columns=COLUMNAS_MOV)


def df_residuos(filas) -> pd.DataFrame:
    return pd.DataFrame(filas, columns=COLUMNAS_RES)


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
    assert set(metricas.resumen_tablas(ventana_reclamos)) == {"totales", "altas", "altas_detalle", "estado"}


# --------------------------------------------------------------------------
# Otros dominios: contadores y promedios sin dato
# --------------------------------------------------------------------------

def test_movilidad_lee_las_altas_con_la_fecha_en_el_grano():
    movilidad = ventana(casos.MOVILIDAD, [(37, df_movilidad(FILAS_MOV_W37)),
                                          (38, df_movilidad(FILAS_MOV_W38))])

    altas = metricas.altas_detalladas(movilidad)

    assert altas["altas"].sum() == 4
    assert altas.iloc[0]["fechaInicio"] == "2026-09-15"


def test_los_contadores_se_suman_y_se_informan_como_nivel():
    residuos = ventana(casos.RESIDUOS, [(37, df_residuos(FILAS_RES_W37)),
                                        (38, df_residuos(FILAS_RES_W38))])

    fila = metricas.totales(residuos).iloc[-1]

    assert fila["acumulado_total"] == 19   # 14 + 5 alertas
    assert fila["altas_semana"] == 4       # solo crecio la zona Norte
    assert fila["cantidadResueltas"] == 6


def test_las_filas_sin_promedio_no_cuentan_como_cero():
    """Las alertas de FALLA_SENSOR no tienen tiempo de resolucion: promediarlas
    como 0 hundiria el indicador. 8.0 es el promedio de las que si lo tienen."""
    residuos = ventana(casos.RESIDUOS, [(37, df_residuos(FILAS_RES_W37)),
                                        (38, df_residuos(FILAS_RES_W38))])

    assert metricas.totales(residuos).iloc[-1]["tiempoPromResolucion"] == pytest.approx(8.0)


def test_un_snapshot_sin_ningun_promedio_informa_nulo():
    sin_dato = [("Norte", "LLENO", "ALTA", "80-100", 10, 0, None)]
    residuos = ventana(casos.RESIDUOS, [(37, df_residuos(sin_dato)), (38, df_residuos(sin_dato))])

    assert metricas.totales(residuos).iloc[-1]["tiempoPromResolucion"] is None


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
