"""Proveedor Claude (API de Anthropic): resumen semanal -> resumen ejecutivo estructurado."""
from __future__ import annotations

import logging

import anthropic

from .config import Settings
from .esquema import ResumenEjecutivo

log = logging.getLogger(__name__)

# Modelos que admiten el fallback server-side ante un rechazo de los clasificadores de seguridad.
MODELOS_CON_FALLBACK = {"claude-opus-5", "claude-fable-5-1"}


def generar_resumen(mensaje: str, settings: Settings, system_prompt: str,
                    client: anthropic.Anthropic | None = None) -> tuple[ResumenEjecutivo, dict]:
    client = client or anthropic.Anthropic(timeout=300.0, max_retries=3)
    modelo = settings.anthropic_model

    extra = {}
    if modelo in MODELOS_CON_FALLBACK:
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

    respuesta = client.beta.messages.parse(
        model=modelo,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=system_prompt,
        messages=[{"role": "user", "content": mensaje}],
        output_format=ResumenEjecutivo,
        **extra,
    )

    uso = {
        "proveedor": "anthropic",
        "modelo_solicitado": modelo,
        "modelo_respuesta": respuesta.model,
        "request_id": respuesta._request_id,
        "stop_reason": respuesta.stop_reason,
        "input_tokens": respuesta.usage.input_tokens,
        "output_tokens": respuesta.usage.output_tokens,
    }
    log.info("Respuesta de Claude: %s", uso)

    if respuesta.stop_reason == "refusal":
        raise RuntimeError(f"Claude rechazó la solicitud: {respuesta.stop_details}")
    if respuesta.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta se cortó por max_tokens; subir el límite o achicar el histórico")
    if respuesta.parsed_output is None:
        raise RuntimeError(f"No se pudo parsear la salida estructurada (stop_reason={respuesta.stop_reason})")
    return respuesta.parsed_output, uso
