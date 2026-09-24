"""Datos y dobles de prueba compartidos por toda la suite.

Ningun test toca Azure ni llama a un LLM: las fotos de gold se arman a mano en
memoria y el Blob Storage se reemplaza por el cliente falso de este archivo.
"""
from __future__ import annotations

import dataclasses
import io
import json
from types import SimpleNamespace

import pandas as pd
import pytest
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError

from analisis_semanal import casos, datos
from analisis_semanal.config import Settings

# --------------------------------------------------------------------------
# Configuracion
# --------------------------------------------------------------------------

SETTINGS_BASE = Settings(
    storage_connection_string="UseDevelopmentStorage=true",
    storage_account_url=None,
    input_container="gold",
    input_prefix=None,
    output_container="analisis",
    output_prefix="",
    casos=["reclamos"],
    anthropic_model="claude-opus-5",
    semana_objetivo=None,
    semanas_historia=8,
    usar_llm=False,
    llm_provider="azure_openai",
    azure_openai_endpoint="https://ejemplo.openai.azure.com",
    azure_openai_api_key="clave-falsa",
    azure_openai_deployment="gpt-5-mini",
    azure_openai_api_version="2025-04-01-preview",
)


def settings(**cambios) -> Settings:
    """SETTINGS_BASE con los campos que pida el test."""
    return dataclasses.replace(SETTINGS_BASE, **cambios)


# --------------------------------------------------------------------------
# Fotos acumuladas de gold (inventadas)
# --------------------------------------------------------------------------

COLUMNAS_RECLAMOS = ["barrio", "categoria", "prioridad", "origenClasificacion",
                     "estado_actual", "row_count", "tiempo_prom_hasta_estado_actual"]

# Semana 37: foto base. 19 reclamos.
FILAS_W37 = [
    ("Centro", "BACHES", "ALTA", "MODELO", "RECIBIDO", 10, 5.0),
    ("Centro", "BACHES", "ALTA", "MODELO", "RESUELTO", 5, 20.0),
    ("Norte", "LUMINARIA", "BAJA", "CIUDADANO", "RECIBIDO", 4, 2.0),
]

# Semana 38: 26 reclamos. Hay 7 altas y ademas 2 reclamos de Centro pasaron de
# RECIBIDO a RESUELTO (movimiento interno que no tiene que contarse como alta).
FILAS_W38 = [
    ("Centro", "BACHES", "ALTA", "MODELO", "RECIBIDO", 8, 6.0),
    ("Centro", "BACHES", "ALTA", "MODELO", "RESUELTO", 9, 22.0),
    ("Norte", "LUMINARIA", "BAJA", "CIUDADANO", "RECIBIDO", 6, 3.0),
    ("Sur", "RESIDUOS", "MEDIA", "OPERADOR", "RECIBIDO", 3, 1.0),
]


def df_reclamos(filas) -> pd.DataFrame:
    return pd.DataFrame(filas, columns=COLUMNAS_RECLAMOS)


def ruta_snapshot(caso, semana: int, anio: int = 2026, contenedor: str = "gold") -> str:
    return f"{contenedor}/{caso.prefijo}{caso.base_archivo}_{semana:02d}_{anio}.parquet"


def snapshot(caso, semana: int, df: pd.DataFrame, anio: int = 2026) -> datos.Snapshot:
    """Snapshot ya normalizado, fechado por el nombre del blob."""
    return datos.construir_snapshot(caso, ruta_snapshot(caso, semana, anio), df)


@pytest.fixture
def caso_reclamos():
    return casos.RECLAMOS


@pytest.fixture
def snapshots_reclamos(caso_reclamos):
    """Las dos fotos de reclamos: W37 (base) y W38 (la semana a analizar)."""
    return [snapshot(caso_reclamos, 37, df_reclamos(FILAS_W37)),
            snapshot(caso_reclamos, 38, df_reclamos(FILAS_W38))]


@pytest.fixture
def ventana_reclamos(snapshots_reclamos):
    return datos.Ventana(snapshots_reclamos)


# --------------------------------------------------------------------------
# Blob Storage falso (en memoria)
# --------------------------------------------------------------------------

class _Descarga:
    def __init__(self, contenido: bytes, etag: str):
        self._contenido = contenido
        self.properties = SimpleNamespace(etag=etag)

    def readall(self) -> bytes:
        return self._contenido


class ContenedorFalso:
    def __init__(self, nombre: str, existe: bool = False):
        self.nombre = nombre
        self.existe = existe
        self.blobs: dict[str, bytes] = {}
        self.etags: dict[str, str] = {}
        self._version = 0

    # -- helpers para los tests ---------------------------------------
    def cargar(self, ruta: str, contenido: bytes) -> str:
        self._version += 1
        self.blobs[ruta] = contenido
        self.etags[ruta] = f'"{self._version}"'
        return self.etags[ruta]

    def cargar_parquet(self, ruta: str, df: pd.DataFrame) -> str:
        buffer = io.BytesIO()
        df.to_parquet(buffer, index=False)
        return self.cargar(ruta, buffer.getvalue())

    def cargar_json(self, ruta: str, contenido: dict) -> str:
        return self.cargar(ruta, json.dumps(contenido, ensure_ascii=False).encode("utf-8"))

    def json(self, ruta: str) -> dict:
        return json.loads(self.blobs[ruta].decode("utf-8"))

    # -- API que usa blob_io ------------------------------------------
    def list_blobs(self, name_starts_with: str = ""):
        return [SimpleNamespace(name=n) for n in sorted(self.blobs) if n.startswith(name_starts_with or "")]

    def download_blob(self, ruta: str) -> _Descarga:
        if ruta not in self.blobs:
            raise ResourceNotFoundError(f"No existe {ruta}")
        return _Descarga(self.blobs[ruta], self.etags[ruta])

    def create_container(self):
        if self.existe:
            raise ResourceExistsError(f"El contenedor {self.nombre} ya existe")
        self.existe = True

    def upload_blob(self, ruta: str, contenido: bytes, overwrite: bool = False,
                    content_settings=None, etag: str | None = None, match_condition=None):
        if etag is not None and self.etags.get(ruta) != etag:
            raise ResourceModifiedError(f"{ruta} cambio (etag {etag})")
        if ruta in self.blobs and not overwrite:
            raise ResourceExistsError(f"{ruta} ya existe")
        self.content_settings = content_settings
        self.cargar(ruta, contenido)


class ClienteFalso:
    """Reemplazo de BlobServiceClient: guarda los contenedores en un diccionario."""

    def __init__(self):
        self.contenedores: dict[str, ContenedorFalso] = {}

    def contenedor(self, nombre: str, existe: bool = False) -> ContenedorFalso:
        if nombre not in self.contenedores:
            self.contenedores[nombre] = ContenedorFalso(nombre, existe)
        return self.contenedores[nombre]

    def get_container_client(self, nombre: str) -> ContenedorFalso:
        return self.contenedor(nombre)


@pytest.fixture
def cliente_falso():
    return ClienteFalso()


@pytest.fixture
def gold_con_reclamos(cliente_falso, caso_reclamos):
    """Container gold con las dos fotos semanales y la tabla mutable del dia."""
    gold = cliente_falso.contenedor("gold", existe=True)
    gold.cargar_parquet(f"{caso_reclamos.prefijo}{caso_reclamos.base_archivo}_37_2026.parquet",
                        df_reclamos(FILAS_W37))
    gold.cargar_parquet(f"{caso_reclamos.prefijo}{caso_reclamos.base_archivo}_38_2026.parquet",
                        df_reclamos(FILAS_W38))
    # Foto mutable del dia: se pisa todos los dias y el modulo tiene que ignorarla.
    gold.cargar_parquet(f"{caso_reclamos.prefijo}{caso_reclamos.base_archivo}.parquet",
                        df_reclamos(FILAS_W38))
    return cliente_falso
