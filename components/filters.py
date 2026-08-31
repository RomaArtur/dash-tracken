"""Widget de filtro de período, reutilizado em todas as páginas de
métrica e na Visão Geral."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

_PRESETS = {
    "Últimos 7 dias": 7,
    "Últimos 30 dias": 30,
    "Últimos 90 dias": 90,
}


def period_filter(key_prefix: str) -> tuple[date, date]:
    """Renderiza o seletor de período (presets + intervalo personalizado)
    e retorna (data_inicio, data_fim)."""
    col1, col2 = st.columns([1, 2])
    with col1:
        preset = st.selectbox(
            "Período",
            options=[*_PRESETS.keys(), "Personalizado"],
            key=f"{key_prefix}_preset",
        )

    today = date.today()
    if preset == "Personalizado":
        with col2:
            value = st.date_input(
                "Intervalo",
                value=(today - timedelta(days=30), today),
                key=f"{key_prefix}_range",
            )
        if isinstance(value, tuple) and len(value) == 2:
            start, end = value
        else:
            start, end = today - timedelta(days=30), today
    else:
        days = _PRESETS[preset]
        start, end = today - timedelta(days=days - 1), today

    return start, end
