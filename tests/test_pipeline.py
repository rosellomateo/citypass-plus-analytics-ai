"""Orquestacion: de las fotos de gold a la entrada del historial. El LLM va mockeado."""
from __future__ import annotations

import pytest

from analisis_semanal import casos, datos, llm, llm_azure_openai, pipeline
from analisis_semanal.esquema import ResumenEjecutivo
from conftest import FILAS_W37, FILAS_W38, df_reclamos, settings, snapshot

RESUMEN_FALSO = ResumenEjecutivo(
    parrafo_ejecutivo="La semana cerro con 7 reclamos nuevos.",
    puntos_destacados=["Sur aporto 3 altas."],
    riesgos=["El backlog de ALTA no baja."],
    recomendaciones=["Reforzar cuadrillas en Sur."],
)
USO_FALSO = {"proveedor": "falso", "input_tokens": 10, "output_tokens": 20}


@pytest.fixture
def llm_falso(monkeypatch):
    """Reemplaza a los dos proveedores y guarda lo que se les mando."""
    llamadas = []

    def generar_resumen(mensaje, settings_, system_prompt, client=None):
        llamadas.append({"mensaje": mensaje, "system_prompt": system_prompt})
        return RESUMEN_FALSO, USO_FALSO

    monkeypatch.setattr(llm_azure_openai, "generar_resumen", generar_resumen)
    monkeypatch.setattr(llm, "generar_resumen", generar_resumen)
    return llamadas


# --------------------------------------------------------------------------
# ejecutar
# --------------------------------------------------------------------------

def test_modo_sin_llm_devuelve_las_cifras_y_lo_que_se_le_enviaria_al_modelo(
        caso_reclamos, snapshots_reclamos):
    """USAR_LLM=false sirve para probar la infraestructura sin credenciales."""
    entrada = pipeline.ejecutar(caso_reclamos, snapshots_reclamos, settings(), usar_llm=False)

    assert entrada["semana"] == "2026-W38"
    assert entrada["resumen"] is None
    assert "Tabla `totales`" in entrada["entrada_llm"]

    metadata = entrada["metadata"]
    assert metadata["caso_de_uso"] == "reclamos"
    assert metadata["version_esquema"] == pipeline.VERSION_ESQUEMA
    assert metadata["semanas_comparadas"] == ["2026-W38"]
    assert metadata["snapshot_base"] == "2026-W37"
    assert metadata["avisos"] == []
    assert metadata["cifras"] == {"altas_semana": 7, "acumulado_total": 26,
                                  "abiertos": 17, "cerrados": 9, "descartados": 0}
    assert metadata["fuentes"] == [s.ruta for s in snapshots_reclamos]
    assert metadata["filas_enviadas"] == 24  # 2 totales + 12 altas + 3 detalle + 7 estado


def test_con_el_llm_prendido_se_guarda_el_resumen_y_el_uso(caso_reclamos, snapshots_reclamos, llm_falso):
    entrada = pipeline.ejecutar(caso_reclamos, snapshots_reclamos, settings(usar_llm=True))

    assert entrada["resumen"]["parrafo_ejecutivo"] == RESUMEN_FALSO.parrafo_ejecutivo
    assert entrada["resumen"]["recomendaciones"] == RESUMEN_FALSO.recomendaciones
    assert entrada["metadata"]["llm"] == USO_FALSO
    assert "entrada_llm" not in entrada  # el mensaje solo se guarda en modo prueba

    assert len(llm_falso) == 1
    assert "Glosario de reclamos" in llm_falso[0]["system_prompt"]
    assert "Semana a analizar: 2026-W38" in llm_falso[0]["mensaje"]


def test_se_puede_elegir_el_proveedor_anthropic(caso_reclamos, snapshots_reclamos, llm_falso):
    entrada = pipeline.ejecutar(caso_reclamos, snapshots_reclamos,
                                settings(usar_llm=True, llm_provider="anthropic"))

    assert entrada["resumen"] is not None
    assert len(llm_falso) == 1


def test_un_proveedor_desconocido_falla_antes_de_llamar_a_nadie(caso_reclamos, snapshots_reclamos):
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        pipeline.ejecutar(caso_reclamos, snapshots_reclamos,
                          settings(usar_llm=True, llm_provider="gemini"))


def test_semana_objetivo_analiza_una_semana_vieja(caso_reclamos):
    serie = [snapshot(caso_reclamos, 36, df_reclamos(FILAS_W37)),
             snapshot(caso_reclamos, 37, df_reclamos(FILAS_W37)),
             snapshot(caso_reclamos, 38, df_reclamos(FILAS_W38))]

    entrada = pipeline.ejecutar(caso_reclamos, serie, settings(semana_objetivo="2026-W37"),
                                usar_llm=False)

    assert entrada["semana"] == "2026-W37"
    assert entrada["metadata"]["cifras"]["altas_semana"] == 0


# --------------------------------------------------------------------------
# Avisos sobre los datos
# --------------------------------------------------------------------------

def test_avisa_cuando_falta_un_snapshot_en_el_medio(caso_reclamos):
    """Sin la foto de W37, las altas de W38 acumulan dos semanas y el LLM tiene que saberlo."""
    serie = [snapshot(caso_reclamos, 36, df_reclamos(FILAS_W37)),
             snapshot(caso_reclamos, 38, df_reclamos(FILAS_W38))]

    avisos = pipeline.ejecutar(caso_reclamos, serie, settings(), usar_llm=False)["metadata"]["avisos"]

    assert len(avisos) == 1
    assert "falta al menos un snapshot" in avisos[0]


def test_avisa_cuando_una_foto_tiene_menos_registros_que_la_anterior(caso_reclamos):
    serie = [snapshot(caso_reclamos, 37, df_reclamos(FILAS_W38)),
             snapshot(caso_reclamos, 38, df_reclamos(FILAS_W37))]

    avisos = pipeline.ejecutar(caso_reclamos, serie, settings(), usar_llm=False)["metadata"]["avisos"]

    assert any("altas negativas" in aviso for aviso in avisos)


# --------------------------------------------------------------------------
# Historial acumulado
# --------------------------------------------------------------------------

def entrada(semana: str) -> dict:
    return {"semana": semana, "resumen": None, "metadata": {}}


def test_la_primera_corrida_crea_el_historial(caso_reclamos):
    documento = pipeline.acumular(None, entrada("2026-W38"), caso_reclamos)

    assert documento["caso_de_uso"] == "reclamos"
    assert documento["semanas"] == ["2026-W38"]
    assert documento["ultima_semana"] == "2026-W38"
    assert len(documento["analisis"]) == 1


def test_las_semanas_quedan_ordenadas_aunque_lleguen_salteadas(caso_reclamos):
    documento = pipeline.acumular(None, entrada("2026-W38"), caso_reclamos)
    documento = pipeline.acumular(documento, entrada("2026-W36"), caso_reclamos)
    documento = pipeline.acumular(documento, entrada("2026-W37"), caso_reclamos)

    assert documento["semanas"] == ["2026-W36", "2026-W37", "2026-W38"]
    assert documento["ultima_semana"] == "2026-W38"


def test_volver_a_correr_la_misma_semana_la_reemplaza_en_vez_de_duplicarla(caso_reclamos):
    """El tablero siempre tiene que ver una entrada por semana."""
    documento = pipeline.acumular(None, entrada("2026-W38"), caso_reclamos)
    rehecha = {**entrada("2026-W38"), "resumen": {"parrafo_ejecutivo": "version corregida"}}

    documento = pipeline.acumular(documento, rehecha, caso_reclamos)

    assert documento["semanas"] == ["2026-W38"]
    assert documento["analisis"][0]["resumen"]["parrafo_ejecutivo"] == "version corregida"


def test_acumular_conserva_las_claves_extra_del_historial(caso_reclamos):
    historial = {"comentario": "cargado a mano", "analisis": [entrada("2026-W37")]}

    documento = pipeline.acumular(historial, entrada("2026-W38"), caso_reclamos)

    assert documento["comentario"] == "cargado a mano"
    assert documento["semanas"] == ["2026-W37", "2026-W38"]


def test_cada_caso_escribe_su_propio_archivo(caso_reclamos):
    assert pipeline.ruta_salida(caso_reclamos, settings()) == "reclamos.json"
    assert pipeline.ruta_salida(casos.MOVILIDAD, settings(output_prefix="v2/")) == "v2/movilidad.json"
