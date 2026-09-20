"""Lectura de la capa gold: snapshots semanales acumulados, para cualquier caso de uso.

Los cinco dominios guardan lo mismo: una foto ACUMULADA (todo lo que existe
desde el dia cero, agrupado por las dimensiones del dominio) que se archiva
cada domingo como `<base>_<WW>_<YYYY>.parquet`. La tabla sin semana en el
nombre es esa misma foto pero mutable: se pisa todos los dias, asi que este
modulo la ignora y lee solo los snapshots, que son inmutables.

Ninguna capa gold guarda la fecha de alta del hecho (salvo movilidad, que
tiene fechaInicio en el grano), asi que el flujo de cada semana sale de
restar fotos consecutivas. Eso se hace en metricas.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import pandas as pd

from .casos import CasoDeUso

COL_FECHA_SNAPSHOT = "fecha_snapshot"
PATRON_ETIQUETA = re.compile(r"^(\d{4})-W(\d{1,2})$", re.IGNORECASE)
SIN_DATO = "SIN_DATO"


def patron(caso: CasoDeUso) -> re.Pattern:
    """<base>_<semana>_<anio>.parquet, ej. reclamos_resumen_38_2026.parquet."""
    return re.compile(rf"{re.escape(caso.base_archivo)}_(\d{{1,2}})_(\d{{4}})\.parquet$", re.IGNORECASE)


def etiqueta_semana(anio: int, semana: int) -> str:
    return f"{anio}-W{semana:02d}"


def semana_de_nombre(caso: CasoDeUso, ruta: str) -> tuple[int, int] | None:
    """(anio, semana) segun el nombre del blob, o None si no es un snapshot."""
    nombre = ruta.replace("\\", "/").rsplit("/", 1)[-1]
    match = patron(caso).search(nombre)
    if match is None:
        return None
    return int(match.group(2)), int(match.group(1))


def es_snapshot(caso: CasoDeUso, ruta: str) -> bool:
    return semana_de_nombre(caso, ruta) is not None


def parsear_etiqueta(valor: str) -> tuple[int, int]:
    """'2026-W38' -> (2026, 38). Formato de SEMANA_OBJETIVO."""
    match = PATRON_ETIQUETA.match(valor.strip())
    if match is None:
        raise ValueError(f"Semana invalida: {valor!r}. Se espera el formato 2026-W38")
    return int(match.group(1)), int(match.group(2))


@dataclass(frozen=True)
class Snapshot:
    """Foto acumulada de un dominio al cierre de una semana ISO."""
    caso: CasoDeUso
    anio: int
    semana: int
    corte: date | None
    ruta: str
    datos: pd.DataFrame

    @property
    def etiqueta(self) -> str:
        return etiqueta_semana(self.anio, self.semana)

    @property
    def orden(self) -> tuple[int, int]:
        return (self.anio, self.semana)

    @property
    def total(self) -> int:
        return int(self.datos[self.caso.metrica].sum())


def normalizar(caso: CasoDeUso, df: pd.DataFrame) -> pd.DataFrame:
    """Tipos consistentes entre snapshots y nulos explicitos.

    Un nulo en una dimension es un dato real (algo todavia sin clasificar), no
    una fila a descartar: si quedara como NaN, el groupby lo tiraria y las
    restas entre fotos no cerrarian.
    """
    requeridas = [*caso.dimensiones_todas, caso.metrica]
    faltan = [c for c in requeridas if c not in df.columns]
    if faltan:
        raise ValueError(f"El snapshot de {caso.nombre} no tiene las columnas {faltan}")

    df = df.copy()
    for columna in caso.dimensiones_todas:
        df[columna] = df[columna].astype("string").fillna(SIN_DATO).astype(str)
    df[caso.metrica] = pd.to_numeric(df[caso.metrica]).fillna(0).astype("int64")

    opcionales = [*caso.promedios, *caso.contadores]
    for columna in opcionales:
        df[columna] = pd.to_numeric(df.get(columna), errors="coerce")
    for columna in caso.promedios.values():
        if columna not in df.columns:
            df[columna] = pd.NA

    return df[[*caso.dimensiones_todas, caso.metrica, *dict.fromkeys(opcionales)]]


def construir_snapshot(caso: CasoDeUso, ruta: str, df: pd.DataFrame) -> Snapshot:
    """Arma el Snapshot tomando la semana del nombre del blob y, si falta, de
    la columna fecha_snapshot (las dos salen del mismo datetime en gold)."""
    corte = None
    if COL_FECHA_SNAPSHOT in df.columns and df[COL_FECHA_SNAPSHOT].notna().any():
        corte = pd.to_datetime(df[COL_FECHA_SNAPSHOT].dropna().iloc[0]).date()

    semana = semana_de_nombre(caso, ruta)
    if semana is None:
        if corte is None:
            raise ValueError(
                f"No se puede fechar el snapshot {ruta!r}: el nombre no tiene semana "
                f"y el parquet no trae {COL_FECHA_SNAPSHOT}"
            )
        iso = corte.isocalendar()
        semana = (iso.year, iso.week)

    return Snapshot(caso=caso, anio=semana[0], semana=semana[1], corte=corte,
                    ruta=ruta, datos=normalizar(caso, df))


@dataclass(frozen=True)
class Ventana:
    """Serie de snapshots consecutivos: [base, ..., actual].

    La base no se analiza: es el punto de partida contra el que se resta la
    primera semana. Por eso siempre hay una foto mas que semanas analizadas.
    """
    serie: list[Snapshot]

    @property
    def caso(self) -> CasoDeUso:
        return self.serie[0].caso

    @property
    def base(self) -> Snapshot:
        return self.serie[0]

    @property
    def actual(self) -> Snapshot:
        return self.serie[-1]

    @property
    def previos(self) -> list[Snapshot]:
        return self.serie[1:-1]

    @property
    def semanas(self) -> list[str]:
        return [s.etiqueta for s in self.serie[1:]]

    def saltos(self) -> list[tuple[str, str]]:
        """Pares consecutivos separados por mas de una semana: una corrida que
        no se ejecuto hace que esa 'semana' acumule dos o mas."""
        huecos = []
        for previo, actual in zip(self.serie, self.serie[1:]):
            if previo.corte and actual.corte:
                if (actual.corte - previo.corte).days > 8:
                    huecos.append((previo.etiqueta, actual.etiqueta))
            elif actual.semana - previo.semana != 1 and actual.anio == previo.anio:
                huecos.append((previo.etiqueta, actual.etiqueta))
        return huecos


def seleccionar_ventana(
    snapshots: list[Snapshot], semana_objetivo: str | None, semanas_historia: int
) -> Ventana:
    """Ultima semana terminada (o SEMANA_OBJETIVO) + hasta `semanas_historia - 1`
    semanas previas, mas la foto base necesaria para restar la primera."""
    if not snapshots:
        raise FileNotFoundError("No se encontro ningun snapshot semanal en la capa gold")

    ordenados = sorted(snapshots, key=lambda s: s.orden)
    etiquetas = [s.etiqueta for s in ordenados]
    repetidas = {e for e in etiquetas if etiquetas.count(e) > 1}
    if repetidas:
        raise ValueError(f"Hay mas de un snapshot para {sorted(repetidas)}")

    if semana_objetivo:
        objetivo = parsear_etiqueta(semana_objetivo)
        if objetivo not in [s.orden for s in ordenados]:
            raise ValueError(
                f"No hay snapshot de la semana {semana_objetivo}. Disponibles: {', '.join(etiquetas)}"
            )
        hasta = [s.orden for s in ordenados].index(objetivo) + 1
    else:
        hasta = len(ordenados)

    serie = ordenados[:hasta][-(max(semanas_historia, 1) + 1):]
    if len(serie) < 2:
        raise ValueError(
            "Se necesitan al menos 2 snapshots para comparar una semana contra la anterior "
            f"(hay {len(serie)} hasta {serie[-1].etiqueta}). La capa gold archiva uno por domingo."
        )
    return Ventana(serie)
