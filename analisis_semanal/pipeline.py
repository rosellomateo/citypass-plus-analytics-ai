"""Orquestacion: snapshots de gold -> tablas -> LLM -> historial acumulado por caso de uso."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from . import datos, metricas, prompts
from .casos import CasoDeUso
from .config import Settings

VERSION_ESQUEMA = "3.0"


def _avisos(ventana: datos.Ventana) -> list[str]:
    """Cosas raras de los datos que el LLM tiene que saber para no leerlas mal."""
    avisos = []
    for desde, hasta in ventana.saltos():
        avisos.append(
            f"Entre {desde} y {hasta} falta al menos un snapshot, así que las altas de {hasta} "
            f"acumulan más de una semana."
        )
    negativas = metricas.altas_negativas(metricas.altas_detalladas(ventana))
    if negativas:
        avisos.append(
            f"Hay {negativas} combinación(es) con altas negativas (una foto tiene menos registros que la "
            f"anterior, probablemente por un reproceso); tomalas con pinzas."
        )
    return avisos


def ejecutar(caso: CasoDeUso, snapshots: list[datos.Snapshot], settings: Settings,
             usar_llm: bool = True) -> dict:
    """Devuelve la entrada del historial correspondiente a una semana."""
    ventana = datos.seleccionar_ventana(snapshots, settings.semana_objetivo, settings.semanas_historia)
    tablas = metricas.resumen_tablas(ventana)
    avisos = _avisos(ventana)

    mensaje = prompts.mensaje_usuario(
        {nombre: metricas.a_csv(tabla) for nombre, tabla in tablas.items()},
        ventana.actual.etiqueta,
        [s.etiqueta for s in ventana.serie[1:-1]],
        avisos,
    )

    fila_actual = tablas["totales"].iloc[-1]
    cifras = {
        "altas_semana": None if pd.isna(fila_actual["altas_semana"]) else int(fila_actual["altas_semana"]),
        "acumulado_total": int(fila_actual["acumulado_total"]),
    }
    for columna in ("abiertos", "cerrados", "descartados", *caso.contadores):
        if columna in fila_actual:
            cifras[columna] = int(fila_actual[columna])

    entrada = {
        "semana": ventana.actual.etiqueta,
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "resumen": None,
        "metadata": {
            "version_esquema": VERSION_ESQUEMA,
            "caso_de_uso": caso.nombre,
            "semana_actual": ventana.actual.etiqueta,
            "semanas_comparadas": ventana.semanas,
            "snapshot_base": ventana.base.etiqueta,
            "fuentes": [s.ruta for s in ventana.serie],
            "corte": ventana.actual.corte.isoformat() if ventana.actual.corte else None,
            "avisos": avisos,
            "cifras": cifras,
            "filas_enviadas": int(sum(len(t) for t in tablas.values())),
        },
    }

    if not usar_llm:
        # Modo prueba: se guarda lo que se le enviaria al modelo.
        entrada["entrada_llm"] = mensaje
        return entrada

    if settings.llm_provider == "azure_openai":
        from .llm_azure_openai import generar_resumen
    elif settings.llm_provider == "anthropic":
        from .llm import generar_resumen
    else:
        raise ValueError(f"LLM_PROVIDER desconocido: {settings.llm_provider!r}")

    resumen, uso = generar_resumen(mensaje, settings, prompts.system_prompt(caso))
    entrada["resumen"] = resumen.model_dump()
    entrada["metadata"]["llm"] = uso
    return entrada


def ruta_salida(caso: CasoDeUso, settings: Settings) -> str:
    """Un unico archivo por caso de uso, que va acumulando las semanas."""
    return f"{settings.output_prefix}{caso.nombre}.json"


def acumular(historial: dict | None, entrada: dict, caso: CasoDeUso) -> dict:
    """Agrega la semana al historial del caso de uso.

    Si la semana ya estaba (se volvio a correr la misma), se reemplaza en vez
    de duplicarse: el tablero siempre ve una entrada por semana.
    """
    documento = dict(historial or {})
    anteriores = [a for a in documento.get("analisis", []) if a.get("semana") != entrada["semana"]]
    analisis = sorted([*anteriores, entrada], key=lambda a: a["semana"])

    documento.update({
        "caso_de_uso": caso.nombre,
        "version_esquema": VERSION_ESQUEMA,
        "actualizado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ultima_semana": analisis[-1]["semana"],
        "semanas": [a["semana"] for a in analisis],
        "analisis": analisis,
    })
    return documento
