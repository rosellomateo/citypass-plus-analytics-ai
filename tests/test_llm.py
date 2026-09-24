"""Los dos proveedores de LLM, con el cliente reemplazado por un doble.

Ningun test sale a internet ni necesita credenciales: se inyecta un cliente falso
por el parametro `client`, y lo que se verifica es como se arma el pedido y como
se manejan las respuestas que no sirven (rechazo, corte por longitud, sin parsear).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from analisis_semanal import llm, llm_azure_openai
from analisis_semanal.esquema import ResumenEjecutivo
from conftest import settings

RESUMEN = ResumenEjecutivo(
    parrafo_ejecutivo="Resumen de prueba.",
    puntos_destacados=["Un punto."],
    riesgos=["Un riesgo."],
    recomendaciones=["Una recomendacion."],
)


# --------------------------------------------------------------------------
# Anthropic (Claude)
# --------------------------------------------------------------------------

class MessagesFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.respuesta


class ClienteAnthropicFalso:
    def __init__(self, parsed_output=RESUMEN, stop_reason="end_turn"):
        respuesta = SimpleNamespace(
            parsed_output=parsed_output,
            model="claude-opus-5-20260101",
            stop_reason=stop_reason,
            stop_details="politica de seguridad",
            usage=SimpleNamespace(input_tokens=1200, output_tokens=800),
            _request_id="req_abc123",
        )
        self.messages = MessagesFalso(respuesta)
        self.beta = SimpleNamespace(messages=self.messages)


def test_anthropic_devuelve_el_resumen_y_registra_el_uso():
    cliente = ClienteAnthropicFalso()

    resumen, uso = llm.generar_resumen("mensaje", settings(), "system", client=cliente)

    assert resumen is RESUMEN
    assert uso["proveedor"] == "anthropic"
    assert uso["modelo_solicitado"] == "claude-opus-5"
    assert uso["modelo_respuesta"] == "claude-opus-5-20260101"
    assert uso["request_id"] == "req_abc123"
    assert (uso["input_tokens"], uso["output_tokens"]) == (1200, 800)


def test_anthropic_pide_salida_estructurada_con_el_system_prompt():
    cliente = ClienteAnthropicFalso()

    llm.generar_resumen("las tablas van aca", settings(), "sos analista", client=cliente)

    kwargs = cliente.messages.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["output_format"] is ResumenEjecutivo
    assert kwargs["system"] == "sos analista"
    assert kwargs["messages"] == [{"role": "user", "content": "las tablas van aca"}]


def test_anthropic_activa_el_fallback_solo_en_los_modelos_que_lo_admiten():
    cliente = ClienteAnthropicFalso()
    llm.generar_resumen("mensaje", settings(), "system", client=cliente)
    assert cliente.messages.kwargs["fallbacks"] == "default"

    otro = ClienteAnthropicFalso()
    llm.generar_resumen("mensaje", settings(anthropic_model="claude-haiku-4-5-20251001"),
                        "system", client=otro)
    assert "fallbacks" not in otro.messages.kwargs


def test_anthropic_convierte_un_rechazo_en_error_explicito():
    cliente = ClienteAnthropicFalso(stop_reason="refusal")

    with pytest.raises(RuntimeError, match="rechaz"):
        llm.generar_resumen("mensaje", settings(), "system", client=cliente)


def test_anthropic_avisa_cuando_la_respuesta_se_corto():
    cliente = ClienteAnthropicFalso(stop_reason="max_tokens")

    with pytest.raises(RuntimeError, match="max_tokens"):
        llm.generar_resumen("mensaje", settings(), "system", client=cliente)


def test_anthropic_avisa_cuando_no_se_pudo_parsear():
    cliente = ClienteAnthropicFalso(parsed_output=None)

    with pytest.raises(RuntimeError, match="estructurada"):
        llm.generar_resumen("mensaje", settings(), "system", client=cliente)


# --------------------------------------------------------------------------
# Azure OpenAI
# --------------------------------------------------------------------------

class CompletionsFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.respuesta


class ClienteAzureFalso:
    def __init__(self, parsed=RESUMEN, finish_reason="stop", refusal=None, usage=True):
        choice = SimpleNamespace(
            message=SimpleNamespace(parsed=parsed, refusal=refusal),
            finish_reason=finish_reason,
        )
        respuesta = SimpleNamespace(
            choices=[choice],
            model="gpt-5-mini-2025",
            id="chatcmpl-123",
            usage=SimpleNamespace(prompt_tokens=900, completion_tokens=300) if usage else None,
        )
        self.completions = CompletionsFalso(respuesta)
        self.chat = SimpleNamespace(completions=self.completions)


def test_azure_openai_devuelve_el_resumen_y_registra_el_uso():
    cliente = ClienteAzureFalso()

    resumen, uso = llm_azure_openai.generar_resumen("mensaje", settings(), "system", client=cliente)

    assert resumen is RESUMEN
    assert uso["proveedor"] == "azure_openai"
    assert uso["deployment"] == "gpt-5-mini"
    assert uso["modelo_respuesta"] == "gpt-5-mini-2025"
    assert (uso["input_tokens"], uso["output_tokens"]) == (900, 300)


def test_azure_openai_manda_el_system_prompt_y_el_esquema():
    cliente = ClienteAzureFalso()

    llm_azure_openai.generar_resumen("las tablas", settings(), "sos analista", client=cliente)

    kwargs = cliente.completions.kwargs
    assert kwargs["model"] == "gpt-5-mini"
    assert kwargs["response_format"] is ResumenEjecutivo
    assert kwargs["messages"][0] == {"role": "system", "content": "sos analista"}
    assert kwargs["messages"][1] == {"role": "user", "content": "las tablas"}


def test_azure_openai_sin_credenciales_falla_antes_de_llamar():
    with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
        llm_azure_openai.generar_resumen("mensaje", settings(azure_openai_api_key=None), "system")


def test_azure_openai_sin_uso_informado_no_rompe():
    cliente = ClienteAzureFalso(usage=False)

    _, uso = llm_azure_openai.generar_resumen("mensaje", settings(), "system", client=cliente)

    assert uso["input_tokens"] is None and uso["output_tokens"] is None


def test_azure_openai_convierte_un_rechazo_en_error_explicito():
    cliente = ClienteAzureFalso(parsed=None, refusal="no puedo ayudar con eso")

    with pytest.raises(RuntimeError, match="rechaz"):
        llm_azure_openai.generar_resumen("mensaje", settings(), "system", client=cliente)


def test_azure_openai_avisa_cuando_la_respuesta_se_corto():
    cliente = ClienteAzureFalso(parsed=None, finish_reason="length")

    with pytest.raises(RuntimeError, match="longitud"):
        llm_azure_openai.generar_resumen("mensaje", settings(), "system", client=cliente)


def test_azure_openai_avisa_cuando_no_se_pudo_parsear():
    cliente = ClienteAzureFalso(parsed=None)

    with pytest.raises(RuntimeError, match="estructurada"):
        llm_azure_openai.generar_resumen("mensaje", settings(), "system", client=cliente)
