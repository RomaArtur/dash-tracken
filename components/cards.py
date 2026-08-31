"""Cards de KPI. HTML próprio (via st.markdown) em vez de st.metric puro,
para reproduzir o padrão de stat-tile com ícone + valor + pill de
variação, mantendo os dados vindos de services.metrics_service.KPI."""
from __future__ import annotations

import html

import streamlit as st

from services.metrics_service import KPI


def _format_number(value: float) -> str:
    return f"{value:,.0f}".replace(",", ".")


def _delta_html(kpi: KPI) -> str:
    pct = kpi.delta_pct
    if pct is None:
        return '<span class="tk-stat-delta flat">— sem período anterior</span>'
    direction = "up" if kpi.delta > 0 else ("down" if kpi.delta < 0 else "flat")
    arrow = "▲" if direction == "up" else ("▼" if direction == "down" else "•")
    return f'<span class="tk-stat-delta {direction}">{arrow} {pct:+.1f}%</span>'


def stat_card(kpi: KPI, icon: str = "📈", purple: bool = False) -> None:
    icon_class = "tk-stat-icon tk-purple-bg" if purple else "tk-stat-icon"
    st.markdown(
        f"""
        <div class="tk-stat-card">
            <div class="tk-stat-card-header">
                <span class="tk-stat-label">{html.escape(kpi.label)}</span>
                <span class="{icon_class}">{icon}</span>
            </div>
            <div class="tk-stat-value">{_format_number(kpi.current)}</div>
            {_delta_html(kpi)}
            <span class="tk-stat-sub">vs. período anterior</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_row(kpis: list[KPI], icons: list[str] | None = None) -> None:
    if not kpis:
        return
    icons = icons or ["📈"] * len(kpis)
    cols = st.columns(len(kpis))
    for i, (col, kpi) in enumerate(zip(cols, kpis)):
        with col:
            icon = icons[i % len(icons)]
            stat_card(kpi, icon=icon, purple=(i % 2 == 1))


def hero_card(label: str, value: str, sub: str = "") -> None:
    st.markdown(
        f"""
        <div class="tk-hero">
            <div>
                <div class="tk-hero-label">{html.escape(label)}</div>
                <div class="tk-hero-value">{html.escape(value)}</div>
            </div>
            <div class="tk-hero-sub">{html.escape(sub)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
