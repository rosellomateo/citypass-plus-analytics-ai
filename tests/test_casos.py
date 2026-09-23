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
