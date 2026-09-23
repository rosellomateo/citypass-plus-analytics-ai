"""Descubrimiento, normalizacion y seleccion de los snapshots semanales de gold."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from analisis_semanal import casos, datos
from conftest import FILAS_W37, FILAS_W38, df_reclamos, snapshot


def test_reconoce_el_snapshot_semanal(caso_reclamos):
    ruta = "gold/Reclamos/reclamos_resumen_38_2026.parquet"
    assert datos.es_snapshot(caso_reclamos, ruta)
    assert datos.semana_de_nombre(caso_reclamos, ruta) == (2026, 38)


def test_ignora_la_foto_mutable_del_dia(caso_reclamos):
    """La tabla sin semana en el nombre se pisa todos los dias: si entrara,
    duplicaria la ultima semana o metaria una semana a medio terminar."""
    assert not datos.es_snapshot(caso_reclamos, "gold/Reclamos/reclamos_resumen.parquet")


def test_ignora_los_snapshots_de_otro_dominio(caso_reclamos):
    assert not datos.es_snapshot(caso_reclamos, "gold/Reclamos/viajes_resumen_38_2026.parquet")


@pytest.mark.parametrize("valor,esperado", [("2026-W38", (2026, 38)), (" 2026-w05 ", (2026, 5))])
def test_parsear_etiqueta(valor, esperado):
    assert datos.parsear_etiqueta(valor) == esperado


def test_parsear_etiqueta_invalida_explica_el_formato():
    with pytest.raises(ValueError, match="2026-W38"):
        datos.parsear_etiqueta("semana 38")


def test_normalizar_conserva_las_filas_con_dimension_nula(caso_reclamos):
    """Un nulo es un dato real (algo sin clasificar todavia), no una fila a tirar:
    si quedara como NaN el groupby la descartaria y las restas no cerrarian."""
    filas = [*FILAS_W37, (None, "BACHES", "ALTA", "MODELO", "RECIBIDO", 7, 4.0)]

    normalizado = datos.normalizar(caso_reclamos, df_reclamos(filas))

    assert len(normalizado) == 4
    assert datos.SIN_DATO in set(normalizado["barrio"])
    assert normalizado["row_count"].sum() == 26


def test_normalizar_avisa_que_columnas_faltan(caso_reclamos):
    df = df_reclamos(FILAS_W37).drop(columns=["prioridad", "row_count"])
    with pytest.raises(ValueError) as error:
        datos.normalizar(caso_reclamos, df)
    assert "prioridad" in str(error.value) and "row_count" in str(error.value)


def test_normalizar_tolera_que_falte_una_columna_de_promedio(caso_reclamos):
    """El promedio es opcional: sin el la foto se lee igual, con el promedio nulo."""
    df = df_reclamos(FILAS_W37).drop(columns=["tiempo_prom_hasta_estado_actual"])

    normalizado = datos.normalizar(caso_reclamos, df)

    assert normalizado["tiempo_prom_hasta_estado_actual"].isna().all()


def test_el_snapshot_se_fecha_por_el_nombre_del_blob(caso_reclamos):
    snap = snapshot(caso_reclamos, 38, df_reclamos(FILAS_W38))

    assert snap.etiqueta == "2026-W38"
    assert snap.orden == (2026, 38)
    assert snap.total == 26


def test_sin_semana_en_el_nombre_se_usa_fecha_snapshot(caso_reclamos):
    df = df_reclamos(FILAS_W38).assign(fecha_snapshot=pd.Timestamp("2026-09-20"))

    snap = datos.construir_snapshot(caso_reclamos, "gold/Reclamos/reclamos_resumen.parquet", df)

    assert snap.corte == date(2026, 9, 20)
    assert snap.etiqueta == "2026-W38"


def test_sin_semana_ni_fecha_el_snapshot_no_se_puede_fechar(caso_reclamos):
    with pytest.raises(ValueError, match="fecha_snapshot"):
        datos.construir_snapshot(caso_reclamos, "gold/Reclamos/reclamos_resumen.parquet",
                                 df_reclamos(FILAS_W38))


def test_la_ventana_se_recorta_a_las_semanas_de_historia(caso_reclamos):
    serie = [snapshot(caso_reclamos, semana, df_reclamos(FILAS_W37)) for semana in range(33, 39)]

    ventana = datos.seleccionar_ventana(serie, None, semanas_historia=2)

    # 2 semanas analizadas + la foto base contra la que se resta la primera.
    assert [s.etiqueta for s in ventana.serie] == ["2026-W36", "2026-W37", "2026-W38"]
    assert ventana.semanas == ["2026-W37", "2026-W38"]
    assert ventana.actual.etiqueta == "2026-W38"
    assert ventana.base.etiqueta == "2026-W36"
    assert [s.etiqueta for s in ventana.previos] == ["2026-W37"]


def test_semana_objetivo_descarta_las_posteriores(caso_reclamos):
    serie = [snapshot(caso_reclamos, semana, df_reclamos(FILAS_W37)) for semana in (36, 37, 38)]

    ventana = datos.seleccionar_ventana(serie, "2026-W37", semanas_historia=8)

    assert ventana.actual.etiqueta == "2026-W37"


def test_semana_objetivo_inexistente_lista_las_disponibles(caso_reclamos, snapshots_reclamos):
    with pytest.raises(ValueError) as error:
        datos.seleccionar_ventana(snapshots_reclamos, "2026-W40", semanas_historia=8)
    assert "2026-W37" in str(error.value) and "2026-W38" in str(error.value)


def test_un_solo_snapshot_no_alcanza_para_comparar(caso_reclamos):
    serie = [snapshot(caso_reclamos, 38, df_reclamos(FILAS_W38))]

    with pytest.raises(ValueError, match="al menos 2"):
        datos.seleccionar_ventana(serie, None, semanas_historia=8)


def test_dos_snapshots_de_la_misma_semana_son_un_error(caso_reclamos):
    serie = [snapshot(caso_reclamos, 38, df_reclamos(FILAS_W37)),
             snapshot(caso_reclamos, 38, df_reclamos(FILAS_W38))]

    with pytest.raises(ValueError, match="2026-W38"):
        datos.seleccionar_ventana(serie, None, semanas_historia=8)


def test_sin_snapshots_falla_como_archivo_faltante():
    with pytest.raises(FileNotFoundError):
        datos.seleccionar_ventana([], None, semanas_historia=8)


def test_saltos_detecta_la_semana_que_no_se_archivo(caso_reclamos):
    """Si falta un domingo, las altas de la semana siguiente acumulan dos semanas."""
    serie = [snapshot(caso_reclamos, 36, df_reclamos(FILAS_W37)),
             snapshot(caso_reclamos, 38, df_reclamos(FILAS_W38))]

    assert datos.Ventana(serie).saltos() == [("2026-W36", "2026-W38")]


def test_saltos_no_marca_semanas_consecutivas(ventana_reclamos):
    assert ventana_reclamos.saltos() == []


def test_saltos_usa_la_fecha_de_corte_cuando_el_parquet_la_trae(caso_reclamos):
    """Con fecha_snapshot se mide en dias: mas de 8 entre fotos es un domingo perdido."""
    def con_corte(semana, fecha):
        return snapshot(caso_reclamos, semana,
                        df_reclamos(FILAS_W37).assign(fecha_snapshot=pd.Timestamp(fecha)))

    seguidas = datos.Ventana([con_corte(37, "2026-09-13"), con_corte(38, "2026-09-20")])
    salteadas = datos.Ventana([con_corte(36, "2026-09-06"), con_corte(38, "2026-09-20")])

    assert seguidas.saltos() == []
    assert salteadas.saltos() == [("2026-W36", "2026-W38")]
