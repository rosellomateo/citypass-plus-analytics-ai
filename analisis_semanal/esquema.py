"""Esquema de salida del LLM (structured outputs). Es lo que consume el tablero."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ResumenEjecutivo(BaseModel):
    parrafo_ejecutivo: str = Field(
        description="Un único párrafo de 120 a 180 palabras: cómo fue la última semana frente al histórico, "
                    "integrando lo más importante de los puntos destacados, riesgos y recomendaciones."
    )
    puntos_destacados: list[str] = Field(description="2 a 5 ítems, una oración cada uno, con cifras cuando aplique.")
    riesgos: list[str] = Field(description="1 a 5 ítems, una oración cada uno.")
    recomendaciones: list[str] = Field(
        description="2 a 5 acciones concretas que un área de gobierno pueda ejecutar, una oración cada una."
    )
