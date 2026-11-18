"""Prompt compartido por todos los proveedores de LLM y todos los casos de uso.

La parte invariante es como leer fotos acumuladas; la parte que cambia por
dominio (que es cada fila, que significan los estados) sale del glosario del
CasoDeUso.
"""
from __future__ import annotations

import unicodedata

from .casos import CASOS_TRANSVERSALES, CasoDeUso

ENCABEZADO = """\
Sos analista de gestión del gobierno de la ciudad. Cada semana escribís el resumen ejecutivo del tablero \
de {nombre} de la app CityPass+, para autoridades que lo leen en un minuto.

De dónde salen los datos: la capa gold archiva todos los domingos una foto ACUMULADA de {metrica} (todo lo \
que existe desde el día cero, repartido por las dimensiones del dominio). Esa foto es un stock: no dice \
cuántos/as {metrica} entraron en la semana. Las altas semanales ya fueron calculadas restando cada foto \
contra la anterior, así que no tenés que restar nada, usá las cifras como vienen."""

TABLAS = """\
1. totales: una fila por semana. `altas_semana` son las altas de {metrica} de esa semana; `acumulado_total` y \
el resto de las columnas son el stock al cierre del domingo.
2. altas: las altas de cada semana abiertas de a una dimensión por vez (formato largo: semana, dimensión, \
valor, altas). Las filas de una misma semana y dimensión suman el total de altas de esa semana.
3. altas_detalle: el cruce completo de dimensiones, solo de la semana analizada y solo las combinaciones \
más grandes."""

TABLA_ESTADO = """\
{n}. estado: el stock al cierre de cada semana por estado (y prioridad cuando aplica)."""

TABLA_CASOS = """\
{n}. casos_de_uso: el stock de cada uno de los seis casos de uso transversales de CityPass+ al cierre de \
cada semana, según el causaTipo de las filas. Siempre vienen las seis filas por semana, aunque valgan 0. \
`variacion_semana` es el neto contra la foto anterior (no son altas: puede incluir cambios de causa)."""

CASOS_EN_EL_PARRAFO = """\
Los seis casos de uso transversales (un hecho que nace en un dominio y repercute en los demás):
{lista}

Regla obligatoria del párrafo ejecutivo: tiene que nombrar los seis casos de uso al menos una vez, por su \
nombre. Para cada uno, la cifra de la tabla casos_de_uso que corresponda a {nombre}; si un caso no tiene \
registros en este dominio, decilo en pocas palabras (podés agrupar en una sola oración los que están en \
cero). Si el glosario dice que un caso se aproxima con otro dato o que el dato no llega a gold, aclaralo en \
vez de presentarlo como que no pasó nada."""

CIERRE = """\
Cómo comparar:
- El eje del resumen son las altas: compará las de la última semana contra la anterior y contra el \
promedio de las semanas que tenés.
- Los acumulados SIEMPRE suben; que `acumulado_total` crezca no es una noticia. Lo que importa es a qué \
ritmo entran (altas) y cómo se reparte el stock.
- Los promedios son del acumulado entero, no de la semana: se mueven despacio y están arrastrados por \
casos viejos. Tratalos como un nivel, no como el resultado de la semana.
- La primera semana de la tabla `totales` no tiene `altas_semana`: es la foto base contra la que se \
restaron las demás. No la presentes como una semana sin actividad.
- Con volúmenes chicos (menos de ~20 en un grupo) las variaciones porcentuales exageran: usá valores \
absolutos y aclaralo cuando la muestra sea chica.
- Toda cifra que cites tiene que salir de las tablas; no inventes datos. Si proponés una causa, \
presentala como hipótesis a validar.
- SIN_DATO en cualquier columna es un dato faltante, no una categoría.
- Las semanas son ISO: 2026-W38 es la semana que cierra ese domingo.

Estilo: español rioplatense neutro, directo, sin jerga técnica, con cifras concretas."""


CANTIDADES = {3: "tres", 4: "cuatro", 5: "cinco"}


def system_prompt(caso: CasoDeUso) -> str:
    tablas = [TABLAS.format(metrica=caso.etiqueta_metrica)]
    if caso.columna_estado:
        tablas.append(TABLA_ESTADO.format(n=len(tablas) + 3))
    if caso.columna_causa:
        tablas.append(TABLA_CASOS.format(n=len(tablas) + 3))
    cantidad = len(tablas) + 2

    partes = [
        ENCABEZADO.format(nombre=caso.nombre, metrica=caso.etiqueta_metrica),
        f"Recibís {CANTIDADES[cantidad]} tablas en CSV:\n" + "\n".join(tablas),
        f"Glosario de {caso.nombre}:\n{caso.glosario}",
    ]
    if caso.columna_causa:
        lista = "\n".join(f"- {t.etiqueta} (causaTipo {', '.join(t.causas)})" for t in CASOS_TRANSVERSALES)
        partes.append(CASOS_EN_EL_PARRAFO.format(lista=lista, nombre=caso.nombre))
    partes.append(CIERRE)
    return "\n\n".join(partes)


def casos_sin_mencion(parrafo: str) -> list[str]:
    """Casos de uso transversales que el parrafo no nombra. Es un control
    grueso (busca el nombre del caso o su numero), para dejar registro si el
    modelo se salteo la regla; no reemplaza leer el resumen."""
    texto = _sin_acentos(parrafo.lower())
    faltan = []
    for transversal in CASOS_TRANSVERSALES:
        claves = [_sin_acentos(transversal.nombre.lower()), f"caso {transversal.numero}",
                  *PALABRAS_CLAVE.get(transversal.numero, ())]
        if not any(clave in texto for clave in claves):
            faltan.append(transversal.etiqueta)
    return faltan


# Formas habituales de nombrar cada caso en un texto corrido.
PALABRAS_CLAVE = {
    1: ("climatic", "clima"),
    2: ("reclamo",),
    3: ("evento masivo", "eventos masivos", "evento publico", "eventos publicos"),
    4: ("incidente vial", "incidentes viales"),
    5: ("bicicleta", "bici"),
    6: ("reserva",),
}


def _sin_acentos(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def mensaje_usuario(tablas: dict, semana_actual: str, historico: list,
                    avisos: list | None = None) -> str:
    """Arma el mensaje con las tablas en CSV y el encuadre de la ventana."""
    partes = [
        f"Semana a analizar: {semana_actual}, ya cerrada (la foto se tomó el domingo).",
        f"Semanas previas para comparar: {', '.join(historico) if historico else 'no hay'}.",
    ]
    if avisos:
        partes.append("Avisos sobre los datos: " + " ".join(avisos))

    bloques = "\n\n".join(f"Tabla `{nombre}`:\n```csv\n{csv}```" for nombre, csv in tablas.items())
    return "\n".join(partes) + "\n\n" + bloques + "\n\nEscribí el resumen ejecutivo."
