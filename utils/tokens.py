"""Fonte única de cores compartilhadas entre CSS (assets/styles.css) e
Python (components/charts.py, components/cards.py). Evita hexadecimais
duplicados/divergentes entre os dois lados.

O roxo usa um único tom (`#9A5FE0`) em vez de um par claro/escuro
porque o Python não tem como saber, de forma confiável, se o tema ativo
no navegador é claro ou escuro (ver components/charts.py) — esse tom
foi escolhido para manter contraste aceitável nos dois casos.
"""
from __future__ import annotations

GREEN = "#28A828"
GREEN_DARK = "#1E8A1E"
PURPLE = "#9A5FE0"
NAVY = "#22305E"
BLUE = "#2F6FE0"
MUTED = "#C7C9CC"
NEGATIVE = "#D64545"

ACCENTS: dict[str, str] = {
    "green": GREEN,
    "purple": PURPLE,
    "navy": NAVY,
    "blue": BLUE,
    "negative": NEGATIVE,
}


def accent_color(accent: str) -> str:
    """Cor hexadecimal correspondente a um acento semântico (ver
    metrics.base.MetricDefinition.accent). Cai em verde se o acento for
    desconhecido, para nunca quebrar um gráfico por um valor inválido."""
    return ACCENTS.get(accent, GREEN)
