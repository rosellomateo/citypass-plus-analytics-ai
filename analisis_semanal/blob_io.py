"""Lectura de snapshots de gold y escritura del historial de analisis en Blob Storage."""
from __future__ import annotations

import io
import json
import logging

import pandas as pd
from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

from . import datos
from .casos import CasoDeUso
from .config import Settings

log = logging.getLogger(__name__)


def crear_cliente(settings: Settings) -> BlobServiceClient:
    if settings.storage_connection_string:
        return BlobServiceClient.from_connection_string(settings.storage_connection_string)
    if settings.storage_account_url:
        # Managed Identity en Azure; en local usa az login / VS Code / variables de entorno.
        from azure.identity import DefaultAzureCredential

        return BlobServiceClient(settings.storage_account_url, credential=DefaultAzureCredential())
    raise ValueError("Configurar STORAGE_CONNECTION_STRING o STORAGE_ACCOUNT_URL")


def leer_snapshots(cliente: BlobServiceClient, contenedor: str, caso: CasoDeUso,
                   prefijo: str | None = None) -> list[datos.Snapshot]:
    """Lee los snapshots semanales del caso de uso bajo su prefijo en gold.

    Se ignoran los blobs que no matchean <base>_<WW>_<YYYY>.parquet: la tabla
    sin semana es la foto mutable del dia, que duplicaria la ultima semana (o
    peor, metaria una semana a medio terminar).
    """
    prefijo = prefijo or caso.prefijo
    container = cliente.get_container_client(contenedor)
    nombres = sorted(
        b.name for b in container.list_blobs(name_starts_with=prefijo) if datos.es_snapshot(caso, b.name)
    )
    if not nombres:
        raise FileNotFoundError(
            f"No hay snapshots semanales en {contenedor}/{prefijo} "
            f"(se esperan archivos {caso.base_archivo}_<semana>_<anio>.parquet)"
        )

    snapshots = []
    for nombre in nombres:
        contenido = container.download_blob(nombre).readall()
        snapshot = datos.construir_snapshot(caso, f"{contenedor}/{nombre}",
                                            pd.read_parquet(io.BytesIO(contenido)))
        log.info("Leido %s -> %s (%d filas, %d %s)", snapshot.ruta, snapshot.etiqueta,
                 len(snapshot.datos), snapshot.total, caso.etiqueta_metrica)
        snapshots.append(snapshot)
    return snapshots


def leer_json(cliente: BlobServiceClient, contenedor: str, ruta: str) -> tuple[dict | None, str | None]:
    """Documento actual y su ETag (None si todavia no existe).

    El ETag se usa al escribir para no pisar una corrida en paralelo.
    """
    container = cliente.get_container_client(contenedor)
    try:
        descarga = container.download_blob(ruta)
        return json.loads(descarga.readall()), descarga.properties.etag
    except ResourceNotFoundError:
        return None, None


def escribir_json(cliente: BlobServiceClient, contenedor: str, ruta: str,
                  contenido: dict, etag: str | None = None) -> None:
    container = cliente.get_container_client(contenedor)
    try:
        container.create_container()
    except ResourceExistsError:
        pass

    condiciones = {}
    if etag:
        condiciones = {"etag": etag, "match_condition": MatchConditions.IfNotModified}

    try:
        container.upload_blob(
            ruta,
            json.dumps(contenido, ensure_ascii=False, indent=2).encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json; charset=utf-8"),
            **condiciones,
        )
    except ResourceModifiedError as error:
        raise RuntimeError(
            f"{contenedor}/{ruta} cambio mientras se generaba el analisis; reintentar la corrida"
        ) from error
    log.info("Escrito %s/%s", contenedor, ruta)
