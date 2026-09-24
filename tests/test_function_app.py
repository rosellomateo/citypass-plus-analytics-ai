"""La Function completa: timer -> gold -> (LLM) -> analisis/<caso>.json.

Corre de punta a punta contra el Blob Storage falso y con USAR_LLM apagado, asi
que no toca Azure ni gasta tokens.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

import function_app
from analisis_semanal import blob_io
from analisis_semanal.config import Settings
from conftest import FILAS_W38, df_reclamos, settings


def correr_timer(past_due: bool = False) -> None:
    """Invoca la funcion de usuario que registro el decorador del timer."""
    funcion = function_app.analisis_semanal._function.get_user_function()
    funcion(SimpleNamespace(past_due=past_due))


# --------------------------------------------------------------------------
# Un caso de uso
# --------------------------------------------------------------------------

def test_analizar_un_caso_escribe_el_historial(gold_con_reclamos):
    mensaje = function_app.analizar_caso(gold_con_reclamos, "reclamos", settings())

    documento = gold_con_reclamos.contenedor("analisis").json("reclamos.json")
    assert documento["caso_de_uso"] == "reclamos"
    assert documento["semanas"] == ["2026-W38"]
    assert documento["analisis"][0]["metadata"]["cifras"]["altas_semana"] == 7
    assert "analisis/reclamos.json" in mensaje


def test_correr_dos_veces_la_misma_semana_no_duplica(gold_con_reclamos):
    function_app.analizar_caso(gold_con_reclamos, "reclamos", settings())
    function_app.analizar_caso(gold_con_reclamos, "reclamos", settings())

    documento = gold_con_reclamos.contenedor("analisis").json("reclamos.json")
    assert documento["semanas"] == ["2026-W38"]
    assert len(documento["analisis"]) == 1


def test_una_semana_nueva_se_suma_al_historial(gold_con_reclamos, caso_reclamos):
    function_app.analizar_caso(gold_con_reclamos, "reclamos", settings(semana_objetivo="2026-W38"))

    # Llega el snapshot del domingo siguiente.
    nuevas = [*FILAS_W38, ("Oeste", "ARBOLADO", "BAJA", "MODELO", "RECIBIDO", 5, 2.0)]
    gold_con_reclamos.contenedor("gold").cargar_parquet(
        f"{caso_reclamos.prefijo}{caso_reclamos.base_archivo}_39_2026.parquet", df_reclamos(nuevas))

    function_app.analizar_caso(gold_con_reclamos, "reclamos", settings())

    documento = gold_con_reclamos.contenedor("analisis").json("reclamos.json")
    assert documento["semanas"] == ["2026-W38", "2026-W39"]
    assert documento["ultima_semana"] == "2026-W39"
    assert documento["analisis"][-1]["metadata"]["cifras"]["altas_semana"] == 5


def test_el_prefijo_de_prueba_solo_aplica_con_un_caso(cliente_falso, caso_reclamos):
    """INPUT_PREFIX es para apuntar a una carpeta de prueba analizando un caso
    solo; con varios casos cada uno tiene que leer su propia carpeta."""
    gold = cliente_falso.contenedor("gold", existe=True)
    base = caso_reclamos.base_archivo
    gold.cargar_parquet(f"{caso_reclamos.prefijo}{base}_37_2026.parquet", df_reclamos(FILAS_W38))
    gold.cargar_parquet(f"{caso_reclamos.prefijo}{base}_38_2026.parquet", df_reclamos(FILAS_W38))

    varios = settings(casos=["reclamos", "movilidad"], input_prefix="carpeta-inexistente/")
    function_app.analizar_caso(cliente_falso, "reclamos", varios)

    assert cliente_falso.contenedor("analisis").json("reclamos.json")["semanas"] == ["2026-W38"]

    with pytest.raises(FileNotFoundError):
        function_app.analizar_caso(cliente_falso, "reclamos",
                                   settings(input_prefix="carpeta-inexistente/"))


def test_un_caso_desconocido_no_se_analiza(cliente_falso):
    with pytest.raises(ValueError, match="Caso de uso desconocido"):
        function_app.analizar_caso(cliente_falso, "transporte", settings())


# --------------------------------------------------------------------------
# El timer
# --------------------------------------------------------------------------

@pytest.fixture
def timer_con(monkeypatch, gold_con_reclamos):
    """Deja el timer listo para correr contra el storage falso."""
    def preparar(**cambios):
        monkeypatch.setattr(Settings, "desde_entorno", staticmethod(lambda: settings(**cambios)))
        monkeypatch.setattr(blob_io, "crear_cliente", lambda _: gold_con_reclamos)
        return gold_con_reclamos
    return preparar


def test_el_timer_analiza_los_casos_configurados(timer_con):
    cliente = timer_con(casos=["reclamos"])

    correr_timer()

    assert cliente.contenedor("analisis").json("reclamos.json")["semanas"] == ["2026-W38"]


def test_un_caso_sin_datos_no_frena_a_los_demas(timer_con, caplog):
    """Emergencias todavia no tiene snapshots en gold: se loguea y sigue."""
    cliente = timer_con(casos=["emergencias", "reclamos"])

    with caplog.at_level(logging.ERROR):
        correr_timer()

    analisis = cliente.contenedor("analisis")
    assert analisis.json("reclamos.json")["semanas"] == ["2026-W38"]
    assert "emergencias.json" not in analisis.blobs
    assert "emergencias" in caplog.text and "no se pudo analizar" in caplog.text


def test_una_corrida_atrasada_queda_registrada(timer_con, caplog):
    timer_con(casos=["reclamos"])

    with caplog.at_level(logging.WARNING):
        correr_timer(past_due=True)

    assert "atrasada" in caplog.text
