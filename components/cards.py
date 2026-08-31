"""Cards de KPI e hero card da Visão Geral.

Os cards de KPI usam st.metric nativo (Streamlit 1.62), que já
reproduz o padrão de stat-tile com ícone + valor + sparkline, sem
precisar de HTML customizado — a cor por métrica (verde Login / roxo
Pop-up / navy) é aplicada via CSS, escopada por um st.container(key=...)
que vira uma classe "st-key-..." no DOM (ver assets/styles.css).

O comparativo com o período anterior (delta) foi removido por decisão
do usuário — kpi.delta_pct continua calculado em services/metrics_service.py
(usado em outros lugares), só não é mais exibido aqui.

O hero card ("Histórico acumulado") é o único que continua HTML
customizado, por não ter equivalente nativo.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from metrics.base import MetricDefinition
from services.metrics_service import KPI


def _format_number(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def stat_card(
    kpi: KPI,
    *,
    icon: str,
    accent: str = "green",
    key: str = "tk-accent-green-0",
    sparkline: pd.Series | None = None,
) -> None:
    with st.container(key=key):
        st.metric(
            label=kpi.label,
            value=_format_number(kpi.current),
            icon=icon,
            border=True,
            chart_data=sparkline if sparkline is not None and not sparkline.empty else None,
            chart_type="area",
        )


def kpi_row(
    kpis: list[KPI],
    metrics: list[MetricDefinition],
    sparklines: list[pd.Series | None] | None = None,
    key_prefix: str = "kpi",
) -> None:
    if not kpis:
        return
    sparklines = sparklines or [None] * len(kpis)
    cols = st.columns(len(kpis))
    for i, (col, kpi, metric, spark) in enumerate(zip(cols, kpis, metrics, sparklines)):
        with col:
            stat_card(
                kpi,
                icon=metric.icon,
                accent=metric.accent,
                key=f"tk-accent-{metric.accent}-{key_prefix}-{i}",
                sparkline=spark,
            )


def hero_card(label: str, value: str, sub: str = "", icon: str = "database") -> None:
    st.html(
        f"""
        <div class="tk-hero">
            <div>
                <span class="tk-icon tk-hero-icon">{html.escape(icon)}</span>
                <div class="tk-hero-label">{html.escape(label)}</div>
                <div class="tk-hero-value">{html.escape(value)}</div>
            </div>
            <div class="tk-hero-sub">{html.escape(sub)}</div>
        </div>
        """
    )
