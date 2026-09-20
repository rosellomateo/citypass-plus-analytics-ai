"""Las tablas que recibe el LLM, derivadas de fotos acumuladas. Sirven para cualquier caso de uso.

La capa gold entrega stock (cuanto hay hoy y como esta repartido), no flujo
(cuanto entro esta semana). El flujo se obtiene restando fotos consecutivas.
Esa resta la hace este modulo y no el LLM: restar decenas de filas a ojo es
justo lo que un modelo hace mal, y son las cifras que despues aparecen en el
resumen ejecutivo.

- totales:       una fila por semana, el hilo conductor del resumen.
- altas:         altas de cada semana abiertas de a una dimension por vez.
- altas_detalle: el cruce completo, solo de la semana analizada y acotado a las mas grandes.
- estado:        como quedo el stock por estado al cierre (solo si el dominio tiene estado).

Las marginales en vez del cruce completo son a proposito: con decenas de altas
repartidas en varias dimensiones casi todas las combinaciones valen 1, y esas
filas ocupan tokens sin decir nada.
"""
from __future__ import annotations

import pandas as pd

from .casos import CasoDeUso
from .datos import Snapshot, Ventana


def _agregar(caso: CasoDeUso, df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    """Suma la metrica y los contadores, y promedia ponderando por su peso (los
    promedios de gold son por combinacion, no se pueden promediar sin peso)."""
    tmp = df.copy()
    for columna, peso in caso.promedios.items():
        tmp[f"_num_{columna}"] = (tmp[columna] * tmp[peso]).fillna(0)
        tmp[f"_den_{columna}"] = tmp[peso].where(tmp[columna].notna(), 0)

    agregaciones = {"cantidad": (caso.metrica, "sum")}
    for contador in caso.contadores:
        agregaciones[contador] = (contador, "sum")
    for columna in caso.promedios:
        agregaciones[f"_num_{columna}"] = (f"_num_{columna}", "sum")
        agregaciones[f"_den_{columna}"] = (f"_den_{columna}", "sum")

    g = tmp.groupby(columnas, dropna=False, as_index=False).agg(**agregaciones)
    for columna in caso.promedios:
        g[columna] = (g[f"_num_{columna}"] / g[f"_den_{columna}"]).where(g[f"_den_{columna}"] > 0).round(1)
    return g.drop(columns=[c for c in g.columns if c.startswith(("_num_", "_den_"))])


def _cuenta(snapshot: Snapshot, estados: list[str]) -> int:
    caso = snapshot.caso
    if not caso.columna_estado:
        return 0
    datos = snapshot.datos
    return int(datos.loc[datos[caso.columna_estado].isin(estados), caso.metrica].sum())


def _promedios_de(caso: CasoDeUso, df: pd.DataFrame) -> dict:
    if df.empty:
        return {c: None for c in caso.promedios}
    fila = _agregar(caso, df.assign(_todo=1), ["_todo"]).iloc[0]
    return {c: (None if pd.isna(fila[c]) else float(fila[c])) for c in caso.promedios}


def _acumulado_por_dimension(snapshot: Snapshot) -> pd.Series:
    """Cantidad acumulada por dimension estable (sin la columna de estado)."""
    caso = snapshot.caso
    return snapshot.datos.groupby(caso.dimensiones, dropna=False)[caso.metrica].sum()


def altas_detalladas(ventana: Ventana) -> pd.DataFrame:
    """Altas de cada semana = foto de la semana - foto de la anterior.

    Se agrupa sin la columna de estado a proposito: las dimensiones del
    dominio no cambian despues del alta, asi que la resta cuenta hechos
    nuevos. Restar incluyendo el estado daria el neto de un bucket (negativo
    cuando algo pasa de ASIGNADO a CERRADO), que no es un alta.
    """
    caso = ventana.caso
    partes = []
    for previo, actual in zip(ventana.serie, ventana.serie[1:]):
        delta = _acumulado_por_dimension(actual).subtract(_acumulado_por_dimension(previo), fill_value=0)
        delta = delta[delta != 0].astype("int64")
        if delta.empty:
            continue
        parte = delta.reset_index(name="altas")
        parte.insert(0, "semana", actual.etiqueta)
        partes.append(parte)

    if not partes:
        return pd.DataFrame(columns=["semana", *caso.dimensiones, "altas"])
    return pd.concat(partes, ignore_index=True)


def altas_por_dimension(ventana: Ventana) -> pd.DataFrame:
    """Altas por semana abiertas de a una dimension por vez (formato largo)."""
    caso = ventana.caso
    detalle = altas_detalladas(ventana)
    if detalle.empty:
        return pd.DataFrame(columns=["semana", "dimension", "valor", "altas"])

    partes = []
    for dimension in caso.dimensiones:
        parte = detalle.groupby(["semana", dimension], as_index=False)["altas"].sum()
        parte = parte.rename(columns={dimension: "valor"})
        parte.insert(1, "dimension", dimension)
        partes.append(parte)

    return (
        pd.concat(partes, ignore_index=True)
        .sort_values(["semana", "dimension", "altas", "valor"], ascending=[True, True, False, True])
        .reset_index(drop=True)
    )


def altas_detalle_semana(ventana: Ventana, top: int = 20) -> pd.DataFrame:
    """Cruce completo de las altas, solo de la semana analizada y quedandose con
    las combinaciones mas grandes (el resto son colas de un hecho suelto)."""
    caso = ventana.caso
    detalle = altas_detalladas(ventana)
    if detalle.empty:
        return detalle
    actual = detalle[detalle["semana"] == ventana.actual.etiqueta]
    return (
        actual.sort_values(["altas", *caso.dimensiones],
                           ascending=[False, *[True] * len(caso.dimensiones)])
        .head(top)
        .reset_index(drop=True)
    )


def estado(ventana: Ventana):
    """Stock por estado al cierre de cada semana. None si el dominio no tiene
    columna de estado (ahi el estado vive en contadores, que van en totales)."""
    caso = ventana.caso
    if not caso.columna_estado:
        return None

    # Se cruza con prioridad cuando existe: es la dimension que mas dice sobre
    # un backlog, y mantiene la tabla chica.
    columnas = [caso.columna_estado]
    if "prioridad" in caso.dimensiones:
        columnas.append("prioridad")

    partes = []
    for snapshot in ventana.serie:
        parte = _agregar(caso, snapshot.datos, columnas)
        parte.insert(0, "semana", snapshot.etiqueta)
        partes.append(parte)
    return (
        pd.concat(partes, ignore_index=True)
        .sort_values(["semana", "cantidad"], ascending=[True, False])
        .reset_index(drop=True)
    )


def totales(ventana: Ventana) -> pd.DataFrame:
    """Una fila por semana: altas, acumulado y el reparto del stock."""
    caso = ventana.caso
    altas_por_semana = altas_detalladas(ventana).groupby("semana")["altas"].sum()

    filas = []
    for snapshot in ventana.serie:
        es_base = snapshot is ventana.base
        fila = {
            "semana": snapshot.etiqueta,
            "altas_semana": pd.NA if es_base else int(altas_por_semana.get(snapshot.etiqueta, 0)),
            "acumulado_total": snapshot.total,
        }
        if caso.columna_estado:
            fila["abiertos"] = _cuenta(snapshot, caso.estados_abiertos)
            fila["cerrados"] = _cuenta(snapshot, caso.estados_cerrados)
            fila["descartados"] = _cuenta(snapshot, caso.estados_descartados)
        for contador in caso.contadores:
            fila[contador] = int(snapshot.datos[contador].fillna(0).sum())
        fila.update(_promedios_de(caso, snapshot.datos))
        filas.append(fila)
    return pd.DataFrame(filas)


def a_csv(df: pd.DataFrame) -> str:
    return df.to_csv(index=False, float_format="%.1f")


def resumen_tablas(ventana: Ventana) -> dict:
    tablas = {
        "totales": totales(ventana),
        "altas": altas_por_dimension(ventana),
        "altas_detalle": altas_detalle_semana(ventana),
    }
    stock = estado(ventana)
    if stock is not None:
        tablas["estado"] = stock
    return tablas


def altas_negativas(tabla_altas: pd.DataFrame) -> int:
    """Filas con altas < 0. No deberia haberlas: significa que una foto tiene
    menos hechos que la anterior (reproceso, borrado o snapshot incompleto).
    Se informa en la metadata en vez de taparlo."""
    return int((tabla_altas["altas"] < 0).sum()) if not tabla_altas.empty else 0
