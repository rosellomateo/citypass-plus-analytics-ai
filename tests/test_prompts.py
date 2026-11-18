"""El prompt: la parte comun y la que aporta cada caso de uso."""
from __future__ import annotations

import dataclasses

from analisis_semanal import casos, prompts


def test_el_system_prompt_arma_el_encuadre_del_dominio():
    texto = prompts.system_prompt(casos.RECLAMOS)

    assert "reclamos" in texto
    assert casos.RECLAMOS.glosario in texto
    # Las reglas de lectura que evitan los errores tipicos del modelo.
    assert "acumulado_total" in texto
    assert "SIN_DATO" in texto


def test_un_dominio_con_estado_y_causa_recibe_cinco_tablas():
    texto = prompts.system_prompt(casos.RECLAMOS)

    assert "cinco tablas" in texto
    assert "4. estado:" in texto
    assert "5. casos_de_uso:" in texto


def test_un_dominio_sin_estado_recibe_cuatro_tablas():
    texto = prompts.system_prompt(casos.MOVILIDAD)

    assert "cuatro tablas" in texto
    assert "estado:" not in texto
    assert "4. casos_de_uso:" in texto


def test_sin_columna_de_causa_no_hay_tabla_ni_regla_de_casos():
    texto = prompts.system_prompt(dataclasses.replace(casos.MOVILIDAD, columna_causa=None))

    assert "tres tablas" in texto
    assert "4. casos_de_uso:" not in texto
    assert "Regla obligatoria" not in texto


def test_el_prompt_exige_nombrar_los_seis_casos_de_uso():
    for caso in casos.CASOS.values():
        texto = prompts.system_prompt(caso)

        assert "Regla obligatoria del párrafo ejecutivo" in texto
        for transversal in casos.CASOS_TRANSVERSALES:
            assert transversal.etiqueta in texto


def test_casos_sin_mencion_reconoce_nombres_y_variantes():
    parrafo = ("Hubo 7 reclamos por el temporal climático y 3 por eventos masivos. Los incidentes viales "
               "sumaron 2, y no hubo registros de emergencias en bici ni de reservas.")

    assert prompts.casos_sin_mencion(parrafo) == []


def test_casos_sin_mencion_lista_los_que_faltan():
    faltan = prompts.casos_sin_mencion("La semana cerró con 7 altas en Centro, por un evento climático.")

    assert faltan == [t.etiqueta for t in casos.CASOS_TRANSVERSALES if t.numero != 1]


def test_el_mensaje_lleva_las_tablas_en_csv_y_la_ventana():
    mensaje = prompts.mensaje_usuario(
        {"totales": "semana,altas\n2026-W38,7\n"}, "2026-W38", ["2026-W37"], avisos=[]
    )

    assert "Semana a analizar: 2026-W38" in mensaje
    assert "Semanas previas para comparar: 2026-W37" in mensaje
    assert "Tabla `totales`" in mensaje
    assert "2026-W38,7" in mensaje
    assert mensaje.rstrip().endswith("Escribí el resumen ejecutivo.")


def test_sin_semanas_previas_se_dice_explicitamente():
    mensaje = prompts.mensaje_usuario({"totales": "a,b\n"}, "2026-W38", [])

    assert "Semanas previas para comparar: no hay." in mensaje
    assert "Avisos sobre los datos" not in mensaje


def test_los_avisos_sobre_los_datos_llegan_al_modelo():
    mensaje = prompts.mensaje_usuario({"totales": "a,b\n"}, "2026-W38", ["2026-W37"],
                                      avisos=["Falta el snapshot de 2026-W36."])

    assert "Avisos sobre los datos: Falta el snapshot de 2026-W36." in mensaje
