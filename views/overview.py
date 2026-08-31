"""Visão Geral: um hero card com o histórico acumulado (o motivo de
existir do projeto — dados que persistem entre importações), KPIs de
cada métrica lado a lado, e evolução/comparação semanal em abas."""
from __future__ import annotations

import streamlit as st

from components import cards, charts, filters
from metrics import METRICS
from repositories import import_repository
from services import metrics_service as ms
from services.database import get_connection


def render_overview() -> None:
    st.title("📊 Visão Geral")

    start, end = filters.period_filter(key_prefix="overview")
    prev_start, prev_end = ms.previous_period(start, end)

    series_by_metric = {}
    kpis = []
    for metric in METRICS.values():
        daily_df = ms.load_daily_series_cached(metric.key)
        series_by_metric[metric.key] = daily_df
        kpis.append(ms.period_kpi(daily_df, start, end, prev_start, prev_end, label=metric.label))

    span = ms.history_span(list(series_by_metric.values()))
    runs = import_repository.list_runs(get_connection())

    hero_col, *metric_cols = st.columns([1.3] + [1] * len(kpis))
    with hero_col:
        if span is None:
            cards.hero_card("Histórico acumulado", "—", "Nenhum dado importado ainda")
        else:
            n_days, earliest, latest = span
            last_import_sub = "Nenhuma importação registrada"
            if not runs.empty:
                last_run = runs.iloc[0]
                last_import_sub = f"Última importação: {last_run['filename']}"
            cards.hero_card(
                "Histórico acumulado",
                f"{n_days} dias",
                f"{earliest.strftime('%d/%m/%Y')} → {latest.strftime('%d/%m/%Y')} · {last_import_sub}",
            )

    for i, (col, metric, kpi) in enumerate(zip(metric_cols, METRICS.values(), kpis)):
        with col:
            cards.stat_card(kpi, icon=metric.icon, purple=(i % 2 == 1))

    st.divider()
    st.subheader("Evolução das métricas")
    tabs = st.tabs([m.label for m in METRICS.values()])
    for tab, metric in zip(tabs, METRICS.values()):
        with tab:
            df = series_by_metric[metric.key]
            period_df = df[(df["date"] >= start) & (df["date"] <= end)] if not df.empty else df
            if period_df.empty:
                st.info("Sem dados para o período selecionado.")
            else:
                st.plotly_chart(charts.line_evolution(period_df), width="stretch")

    st.subheader("Comparação semanal")
    tabs2 = st.tabs([m.label for m in METRICS.values()])
    for tab, metric in zip(tabs2, METRICS.values()):
        with tab:
            weekly_df = ms.weekly_comparison(series_by_metric[metric.key])
            if weekly_df.empty:
                st.info("Sem dados suficientes para comparação semanal.")
            else:
                st.plotly_chart(charts.weekly_bar(weekly_df), width="stretch")
