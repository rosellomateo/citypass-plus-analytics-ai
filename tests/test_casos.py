"""Registro de casos de uso: lo unico que distingue un dominio de otro."""
from __future__ import annotations

import pytest

from analisis_semanal import casos


def test_estan_los_cinco_dominios():
    assert set(casos.CASOS) == {"reclamos", "emergencias", "movilidad", "espacios", "residuos"}


def test_obtener_normaliza_mayusculas_y_espacios():
    assert casos.obtener("  Reclamos ") is casos.RECLAMOS


def test_obtener_de_un_caso_inexistente_avisa_cuales_hay():
    with pytest.raises(ValueError) as error:
        casos.obtener("transporte")
    assert "transporte" in str(error.value)
    assert "reclamos" in str(error.value)


def test_dimensiones_todas_suma_el_estado_cuando_el_dominio_lo_tiene():
    assert casos.RECLAMOS.dimensiones_todas == [*casos.RECLAMOS.dimensiones, "estado_actual"]


def test_dimensiones_todas_sin_estado_son_solo_las_dimensiones():
    # Movilidad no tiene columna de estado: un viaje no cambia de estado.
    assert casos.MOVILIDAD.columna_estado is None
    assert casos.MOVILIDAD.dimensiones_todas == casos.MOVILIDAD.dimensiones


def test_cada_promedio_se_pondera_con_una_columna_que_existe():
    """Un promedio ponderado por una columna que no se lee de gold daria siempre nulo."""
    for caso in casos.CASOS.values():
        columnas = {caso.metrica, *caso.contadores}
        for promedio, peso in caso.promedios.items():
            assert peso in columnas, f"{caso.nombre}: {promedio} se pondera por {peso}, que no se lee"


def test_hay_seis_casos_de_uso_transversales_con_causas_sin_repetir():
    causas = [c for t in casos.CASOS_TRANSVERSALES for c in t.causas]

    assert [t.numero for t in casos.CASOS_TRANSVERSALES] == [1, 2, 3, 4, 5, 6]
    assert len(causas) == len(set(causas))


def test_espacios_no_resta_por_una_causa_que_cambia_despues_del_alta():
    assert "causaTipo" not in casos.ESPACIOS.dimensiones
    assert casos.ESPACIOS.columna_causa == "causaTipo"
