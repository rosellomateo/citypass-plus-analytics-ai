"""Proveedor Azure OpenAI (deployment propio, ej. gpt-5-mini): resumen semanal -> resumen ejecutivo estructurado."""
from __future__ import annotations

import logging

from openai import AzureOpenAI

from .config import Settings
from .esquema import ResumenEjecutivo

log = logging.getLogger(__name__)


def generar_resumen(mensaje: str, settings: Settings, system_prompt: str,
                    client: AzureOpenAI | None = None) -> tuple[ResumenEjecutivo, dict]:
    if not (settings.azure_openai_endpoint and settings.azure_openai_api_key):
        raise ValueError("Configurar AZURE_OPENAI_ENDPOINT y AZURE_OPENAI_API_KEY")
    client = client or AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        timeout=300.0,
        max_retries=3,
    )

    respuesta = client.chat.completions.parse(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": mensaje},
        ],
        response_format=ResumenEjecutivo,
        max_completion_tokens=16000,
        reasoning_effort="medium",
    )

    choice = respuesta.choices[0]
    uso = {
        "proveedor": "azure_openai",
        "deployment": settings.azure_openai_deployment,
        "modelo_respuesta": respuesta.model,
        "request_id": respuesta.id,
        "finish_reason": choice.finish_reason,
        "input_tokens": respuesta.usage.prompt_tokens if respuesta.usage else None,
        "output_tokens": respuesta.usage.completion_tokens if respuesta.usage else None,
    }
    log.info("Respuesta de Azure OpenAI: %s", uso)

    if choice.message.refusal:
        raise RuntimeError(f"El modelo rechazó la solicitud: {choice.message.refusal}")
    if choice.finish_reason == "length":
        raise RuntimeError("La respuesta se cortó por longitud; subir max_completion_tokens o achicar el histórico")
    if choice.message.parsed is None:
        raise RuntimeError(f"No se pudo parsear la salida estructurada (finish_reason={choice.finish_reason})")
    return choice.message.parsed, uso
