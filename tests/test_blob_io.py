"""Lectura de gold y escritura del historial, contra un Blob Storage falso en memoria."""
from __future__ import annotations

import json

import pytest

from analisis_semanal import blob_io, casos
from conftest import FILAS_W38, df_reclamos, settings


# --------------------------------------------------------------------------
# Cliente
# --------------------------------------------------------------------------

def test_sin_storage_configurado_avisa_que_falta(monkeypatch):
    with pytest.raises(ValueError, match="STORAGE_CONNECTION_STRING"):
        blob_io.crear_cliente(settings(storage_connection_string=None, storage_account_url=None))


def test_con_connection_string_se_usa_esa(monkeypatch):
    llamadas = []
    monkeypatch.setattr(blob_io.BlobServiceClient, "from_connection_string",
                        classmethod(lambda cls, cadena: llamadas.append(cadena) or "cliente"))

    assert blob_io.crear_cliente(settings()) == "cliente"
    assert llamadas == ["UseDevelopmentStorage=true"]


def test_sin_connection_string_se_usa_managed_identity(monkeypatch):
    """En Azure la Function se autentica con su identidad administrada, sin claves."""
    import azure.identity

    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: "credencial")
    monkeypatch.setattr(blob_io, "BlobServiceClient", lambda url, credential: (url, credential))

    cliente = blob_io.crear_cliente(settings(storage_connection_string=None,
                                             storage_account_url="https://cuenta.blob.core.windows.net"))

    assert cliente == ("https://cuenta.blob.core.windows.net", "credencial")


# --------------------------------------------------------------------------
# Snapshots de gold
# --------------------------------------------------------------------------

def test_lee_los_snapshots_semanales_ordenados(gold_con_reclamos, caso_reclamos):
    snapshots = blob_io.leer_snapshots(gold_con_reclamos, "gold", caso_reclamos)

    assert [s.etiqueta for s in snapshots] == ["2026-W37", "2026-W38"]
    assert snapshots[-1].total == 26
    assert snapshots[-1].ruta == "gold/Reclamos/reclamos_resumen_38_2026.parquet"


def test_la_foto_mutable_del_dia_no_entra(gold_con_reclamos, caso_reclamos):
    """En el container tambien esta reclamos_resumen.parquet, que se pisa todos
    los dias: si se leyera, duplicaria la ultima semana."""
    snapshots = blob_io.leer_snapshots(gold_con_reclamos, "gold", caso_reclamos)

    assert len(snapshots) == 2


def test_se_puede_apuntar_a_una_carpeta_de_prueba(cliente_falso, caso_reclamos):
    gold = cliente_falso.contenedor("gold", existe=True)
    gold.cargar_parquet("pruebas/reclamos_resumen_38_2026.parquet", df_reclamos(FILAS_W38))
    gold.cargar_parquet("Reclamos/reclamos_resumen_37_2026.parquet", df_reclamos(FILAS_W38))

    snapshots = blob_io.leer_snapshots(cliente_falso, "gold", caso_reclamos, prefijo="pruebas/")

    assert [s.ruta for s in snapshots] == ["gold/pruebas/reclamos_resumen_38_2026.parquet"]


def test_un_dominio_sin_snapshots_falla_con_el_nombre_esperado(cliente_falso, caso_reclamos):
    cliente_falso.contenedor("gold", existe=True)

    with pytest.raises(FileNotFoundError) as error:
        blob_io.leer_snapshots(cliente_falso, "gold", caso_reclamos)

    assert "reclamos_resumen" in str(error.value)


def _df_movilidad(afectaciones: int) -> "pd.DataFrame":
    import pandas as pd
    return pd.DataFrame({"causaTipo": ["EVENTO_CLIMATICO", "NORMAL"],
                         "cantidadAfectaciones": [afectaciones, 0],
                         "cantidadViajesInterrumpidos": [1, 30]})


def test_movilidad_lee_solo_viajes_resumen(cliente_falso):
    """La tabla de Movilidad en gold es viajes_resumen; movilidad_resumen
    (el nombre viejo) y la foto diaria no se leen."""
    gold = cliente_falso.contenedor("gold", existe=True)
    gold.cargar_parquet("Movilidad Urbana/movilidad_resumen_45_2026.parquet", _df_movilidad(3))
    gold.cargar_parquet("Movilidad Urbana/viajes_resumen_46_2026.parquet", _df_movilidad(5))
    gold.cargar_parquet("Movilidad Urbana/viajes_resumen.parquet", _df_movilidad(9))

    snapshots = blob_io.leer_snapshots(cliente_falso, "gold", casos.MOVILIDAD)

    assert [(s.etiqueta, s.total) for s in snapshots] == [("2026-W46", 5)]
    assert snapshots[0].ruta.endswith("viajes_resumen_46_2026.parquet")


def test_residuos_acepta_la_causa_renombrada_en_gold(cliente_falso):
    import pandas as pd
    gold = cliente_falso.contenedor("gold", existe=True)
    viejo = pd.DataFrame({"causaTipo": ["RECLAMO"], "estado_actual": ["PROGRAMADA"],
                          "cantidadIntervenciones": [2]})
    nuevo = pd.DataFrame({"causaProgramacion": ["RECLAMO", "EVENTO_PUBLICO"],
                          "estado_actual": ["PROGRAMADA", "PROGRAMADA"],
                          "cantidadIntervenciones": [3, 4]})
    gold.cargar_parquet("Gestion de Residuos Inteligente/intervenciones_resumen_46_2026.parquet", viejo)
    gold.cargar_parquet("Gestion de Residuos Inteligente/intervenciones_resumen_47_2026.parquet", nuevo)

    snapshots = blob_io.leer_snapshots(cliente_falso, "gold", casos.RESIDUOS)

    causas = snapshots[-1].datos.groupby("causaTipo")["cantidadIntervenciones"].sum().to_dict()
    assert causas == {"EVENTO_PUBLICO": 4, "RECLAMO": 3}


# --------------------------------------------------------------------------
# Historial
# --------------------------------------------------------------------------

def test_leer_un_historial_que_todavia_no_existe(cliente_falso):
    assert blob_io.leer_json(cliente_falso, "analisis", "reclamos.json") == (None, None)


def test_leer_un_historial_devuelve_el_contenido_y_su_etag(cliente_falso):
    contenedor = cliente_falso.contenedor("analisis", existe=True)
    etag = contenedor.cargar_json("reclamos.json", {"semanas": ["2026-W38"]})

    documento, leido = blob_io.leer_json(cliente_falso, "analisis", "reclamos.json")

    assert documento == {"semanas": ["2026-W38"]}
    assert leido == etag


def test_escribir_crea_el_container_y_guarda_json_legible(cliente_falso):
    blob_io.escribir_json(cliente_falso, "analisis", "reclamos.json",
                          {"resumen": "la semana fue más tranquila"})

    contenedor = cliente_falso.contenedor("analisis")
    assert contenedor.existe
    crudo = contenedor.blobs["reclamos.json"].decode("utf-8")
    assert "más tranquila" in crudo          # sin escapar los acentos
    assert json.loads(crudo)["resumen"]
    assert "application/json" in contenedor.content_settings.content_type


def test_escribir_sobre_un_container_que_ya_existe(cliente_falso):
    cliente_falso.contenedor("analisis", existe=True)

    blob_io.escribir_json(cliente_falso, "analisis", "reclamos.json", {"a": 1})

    assert cliente_falso.contenedor("analisis").json("reclamos.json") == {"a": 1}


def test_con_el_etag_correcto_se_sobrescribe(cliente_falso):
    contenedor = cliente_falso.contenedor("analisis", existe=True)
    etag = contenedor.cargar_json("reclamos.json", {"semanas": []})

    blob_io.escribir_json(cliente_falso, "analisis", "reclamos.json",
                          {"semanas": ["2026-W38"]}, etag=etag)

    assert contenedor.json("reclamos.json")["semanas"] == ["2026-W38"]


def test_si_otra_corrida_escribio_en_el_medio_no_se_pisa(cliente_falso):
    """El ETag es lo que evita perder el analisis de una corrida en paralelo."""
    contenedor = cliente_falso.contenedor("analisis", existe=True)
    etag_viejo = contenedor.cargar_json("reclamos.json", {"semanas": []})
    contenedor.cargar_json("reclamos.json", {"semanas": ["2026-W37"]})  # otra corrida

    with pytest.raises(RuntimeError, match="reintentar"):
        blob_io.escribir_json(cliente_falso, "analisis", "reclamos.json",
                              {"semanas": ["2026-W38"]}, etag=etag_viejo)

    assert contenedor.json("reclamos.json")["semanas"] == ["2026-W37"]


def test_lee_las_fotos_complementarias_de_la_misma_semana(cliente_falso):
    """Espacios archiva afectados y reservas al lado de actividades; una semana
    sin esa foto (antes de que existiera la tabla) queda en None."""
    import pandas as pd
    from analisis_semanal import casos as casos_mod

    caso = casos_mod.ESPACIOS
    gold = cliente_falso.contenedor("gold", existe=True)
    actividades = pd.DataFrame([("PROGRAMADA", "CULTURAL", None, "CIUDAD", "Centro", 3)],
                               columns=["estado_actual", "categoria", "causaTipo", "organizadorTipo", "barrio",
                                        "cantidadActividades"])
    reservas = pd.DataFrame([("ESPACIO", True, 4)], columns=["tipoReserva", "afectada", "cantidadReservas"])
    gold.cargar_parquet(f"{caso.prefijo}actividades_resumen_37_2026.parquet", actividades)
    gold.cargar_parquet(f"{caso.prefijo}actividades_resumen_38_2026.parquet", actividades)
    gold.cargar_parquet(f"{caso.prefijo}reservas_resumen_38_2026.parquet", reservas)

    w37, w38 = blob_io.leer_snapshots(cliente_falso, "gold", caso)

    assert w37.complementarias == {"espacios_afectados": None, "reservas": None}
    assert w38.complementarias["espacios_afectados"] is None
    assert int(w38.complementarias["reservas"]["cantidadReservas"].sum()) == 4
    assert w38.complementarias["reservas"]["afectada"].tolist() == ["True"]
