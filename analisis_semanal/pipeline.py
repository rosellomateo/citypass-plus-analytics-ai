"""Orquestacion: snapshots de gold -> tablas -> LLM -> historial acumulado por caso de uso."""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from . import datos, metricas, prompts
from .casos import CasoDeUso
from .config import Settings

VERSION_ESQUEMA = "3.1"


def aviso_sin_comparacion(ventana: datos.Ventana) -> str:
    return (
        f"No hay snapshots semanales anteriores a {ventana.actual.etiqueta} en la capa gold, así que "
        f"no se puede comparar contra la semana previa ni calcular las altas de la semana: el análisis "
        f"describe el stock acumulado al cierre de {ventana.actual.etiqueta}."
    )


def _avisos(ventana: datos.Ventana) -> list[str]:
    """Cosas raras de los datos que el LLM tiene que saber para no leerlas mal."""
    if ventana.sin_comparacion:
        return [aviso_sin_comparacion(ventana)]
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
        sin_comparacion=ventana.sin_comparacion,
    )

    fila_actual = tablas["totales"].iloc[-1]
    cifras = {
        "altas_semana": None if pd.isna(fila_actual["altas_semana"]) else int(fila_actual["altas_semana"]),
        "acumulado_total": int(fila_actual["acumulado_total"]),
    }
    for columna in ("abiertos", "cerrados", "descartados", *caso.contadores):
        if columna in fila_actual:
            cifras[columna] = int(fila_actual[columna])
    if "casos_de_uso" in tablas:
        por_caso = tablas["casos_de_uso"]
        por_caso = por_caso[por_caso["semana"] == ventana.actual.etiqueta]
        # caso -> tabla -> cantidad (un caso puede salir de mas de una tabla del dominio)
        cifras["casos_de_uso"] = {}
        for fila in por_caso.itertuples():
            cifras["casos_de_uso"].setdefault(fila.caso_de_uso, {})[fila.tabla] = int(fila.cantidad)

    entrada = {
        "semana": ventana.actual.etiqueta,
        "generado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "resumen": None,
        "metadata": {
            "version_esquema": VERSION_ESQUEMA,
            "caso_de_uso": caso.nombre,
            "semana_actual": ventana.actual.etiqueta,
            "semanas_comparadas": ventana.semanas,
            "snapshot_base": None if ventana.sin_comparacion else ventana.base.etiqueta,
            "sin_comparacion": ventana.sin_comparacion,
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
    if ventana.sin_comparacion:
        # Queda escrito siempre, aunque el modelo no lo diga: el tablero
        # muestra los puntos destacados tal cual.
        destacados = [aviso_sin_comparacion(ventana), *resumen.puntos_destacados]
        resumen = resumen.model_copy(update={"puntos_destacados": destacados})
    entrada["resumen"] = resumen.model_dump()
    entrada["metadata"]["llm"] = uso
    if caso.columna_causa:
        # Queda registrado si el modelo se salteo la regla de nombrar los seis
        # casos de uso; el tablero o quien audite lo puede ver sin leer el texto.
        entrada["metadata"]["casos_sin_mencion"] = prompts.casos_sin_mencion(resumen.parrafo_ejecutivo)
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
