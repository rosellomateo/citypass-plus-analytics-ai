"""Configuración leída de variables de entorno.

En Azure son App Settings de la Function App; en local salen de local.settings.json.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _lista(valor: str | None) -> list[str]:
    """CASOS="reclamos,movilidad" -> ["reclamos", "movilidad"]. "todos" = los cinco."""
    from .casos import CASOS

    if valor is None or valor.strip().lower() in ("todos", "*"):
        return list(CASOS)
    return [parte.strip().lower() for parte in valor.split(",") if parte.strip()]


def _env(nombre: str, default: str | None = None) -> str | None:
    valor = os.environ.get(nombre)
    if valor is None or not valor.strip():
        return default
    return valor.strip()


@dataclass(frozen=True)
class Settings:
    # Storage: connection string (Azurite / PoC) o URL de la cuenta + Managed Identity (producción).
    storage_connection_string: str | None
    storage_account_url: str | None
    input_container: str
    # Override del prefijo dentro de gold. Vacío = el que declara cada caso de uso en casos.py.
    # Solo tiene sentido cuando se analiza un caso a la vez (pruebas).
    input_prefix: str | None
    output_container: str
    output_prefix: str
    # Casos de uso a analizar. Cada uno escribe su propio <caso>.json.
    casos: list[str]
    anthropic_model: str
    # Semana a analizar ("2026-W38"). Vacío = última semana terminada con snapshot en gold.
    semana_objetivo: str | None
    # Semanas con flujo que recibe el LLM (la analizada + las previas). Se lee una foto más que esto,
    # porque las altas de la primera semana salen de restarle la foto anterior.
    semanas_historia: int
    # False = solo métricas, sin llamar al LLM (para probar la infraestructura sin credenciales).
    usar_llm: bool
    # Proveedor del LLM: "azure_openai" (deployment propio en Azure) o "anthropic" (API de Claude).
    llm_provider: str
    azure_openai_endpoint: str | None
    azure_openai_api_key: str | None
    azure_openai_deployment: str
    azure_openai_api_version: str

    @classmethod
    def desde_entorno(cls) -> "Settings":
        return cls(
            storage_connection_string=_env("STORAGE_CONNECTION_STRING"),
            storage_account_url=_env("STORAGE_ACCOUNT_URL"),
            input_container=_env("INPUT_CONTAINER", "gold"),
            input_prefix=_env("INPUT_PREFIX"),
            output_container=_env("OUTPUT_CONTAINER", "analisis"),
            output_prefix=_env("OUTPUT_PREFIX", ""),
            casos=_lista(_env("CASOS", "reclamos")),
            anthropic_model=_env("ANTHROPIC_MODEL", "claude-opus-5"),
            semana_objetivo=_env("SEMANA_OBJETIVO"),
            semanas_historia=int(_env("SEMANAS_HISTORIA", "8")),
            usar_llm=_env("USAR_LLM", "true").lower() not in ("false", "0", "no"),
            llm_provider=_env("LLM_PROVIDER", "azure_openai").lower(),
            azure_openai_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
            azure_openai_api_key=_env("AZURE_OPENAI_API_KEY"),
            azure_openai_deployment=_env("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"),
            azure_openai_api_version=_env("AZURE_OPENAI_API_VERSION", "2025-04-01-preview"),
        )
