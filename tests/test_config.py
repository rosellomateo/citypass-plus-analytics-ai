"""Lectura de App Settings: los defaults son los que corren en Azure."""
from __future__ import annotations

import pytest

from analisis_semanal.config import Settings

VARIABLES = [
    "STORAGE_CONNECTION_STRING", "STORAGE_ACCOUNT_URL", "INPUT_CONTAINER", "INPUT_PREFIX",
    "OUTPUT_CONTAINER", "OUTPUT_PREFIX", "CASOS", "ANTHROPIC_MODEL", "SEMANA_OBJETIVO",
    "SEMANAS_HISTORIA", "USAR_LLM", "LLM_PROVIDER", "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_VERSION",
]


@pytest.fixture
def entorno(monkeypatch):
    for variable in VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    return monkeypatch


def test_defaults_sin_ninguna_variable(entorno):
    settings = Settings.desde_entorno()

    assert settings.input_container == "gold"
    assert settings.output_container == "analisis"
    assert settings.output_prefix == ""
    assert settings.casos == ["reclamos"]
    assert settings.semanas_historia == 8
    assert settings.usar_llm is True
    assert settings.llm_provider == "azure_openai"
    assert settings.semana_objetivo is None


def test_casos_todos_analiza_los_cinco_dominios(entorno):
    entorno.setenv("CASOS", "todos")
    assert len(Settings.desde_entorno().casos) == 5


def test_casos_acepta_lista_con_espacios_y_mayusculas(entorno):
    entorno.setenv("CASOS", " Reclamos , MOVILIDAD ,")
    assert Settings.desde_entorno().casos == ["reclamos", "movilidad"]


@pytest.mark.parametrize("valor", ["false", "FALSE", "0", "no"])
def test_usar_llm_se_puede_apagar(entorno, valor):
    entorno.setenv("USAR_LLM", valor)
    assert Settings.desde_entorno().usar_llm is False


def test_una_variable_en_blanco_vale_como_ausente(entorno):
    """Un App Setting vacio es lo mismo que no configurarlo: se usa el default."""
    entorno.setenv("INPUT_CONTAINER", "   ")
    assert Settings.desde_entorno().input_container == "gold"


def test_variables_de_azure_openai_se_leen_y_el_proveedor_se_normaliza(entorno):
    entorno.setenv("LLM_PROVIDER", "Anthropic")
    entorno.setenv("AZURE_OPENAI_ENDPOINT", "https://ejemplo.openai.azure.com")
    entorno.setenv("SEMANA_OBJETIVO", "2026-W38")
    entorno.setenv("SEMANAS_HISTORIA", "3")

    settings = Settings.desde_entorno()

    assert settings.llm_provider == "anthropic"
    assert settings.azure_openai_endpoint == "https://ejemplo.openai.azure.com"
    assert settings.semana_objetivo == "2026-W38"
    assert settings.semanas_historia == 3
