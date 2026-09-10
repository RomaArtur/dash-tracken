"""Visão Geral: hero card com o histórico acumulado, KPIs com
sparkline por métrica, um gráfico de colunas comparando as métricas
lado a lado (diário/semanal) e a proporção do total acumulado em uma
rosca — sem as abas duplicadas que a versão anterior tinha (Evolução e
Comparação semanal, cada uma repetindo os mesmos rótulos de métrica).
A comparação semanal por métrica individual mora só nas páginas de
detalhe (views/metric_page.py), não aqui — repeti-la na Visão Geral
era redundante."""
from __future__ import annotations

import streamlit as st

from components import cards, charts, filters
from metrics import METRICS
from repositories import import_repository
from services import metrics_service as ms
from services.database import get_connection


def render_overview() -> None:
    header_col, filter_col = st.columns([2, 1], vertical_alignment="bottom")
    with header_col:
        st.title("Visão Geral")
    with filter_col:
        start, end = filters.period_filter(key_prefix="overview")
    prev_start, prev_end = ms.previous_period(start, end)

    metrics = [metric for metric in METRICS.values() if metric.show_in_overview]
    series_by_metric = {}
    kpis = []
    sparklines = []
    for metric in metrics:
        daily_df = ms.load_daily_series_cached(metric.key)
        series_by_metric[metric.key] = daily_df
        kpis.append(ms.period_kpi(daily_df, start, end, prev_start, prev_end, label=metric.label))
        period_df = daily_df[(daily_df["date"] >= start) & (daily_df["date"] <= end)] if not daily_df.empty else daily_df
        sparklines.append(period_df["value"] if not period_df.empty else None)

    span = ms.history_span(list(series_by_metric.values()))
    runs = import_repository.list_runs(get_connection())

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

    st.subheader("Total acumulado")
    total_cols = st.columns(len(metrics))
    for col, metric in zip(total_cols, metrics):
        with col:
            cards.total_card(
                metric.label,
                ms.total_all_time(series_by_metric[metric.key]),
                icon=metric.icon,
                accent=metric.accent,
            )

    st.subheader(f"Período selecionado — {start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}")
    cards.kpi_row(kpis, metrics, sparklines)

    st.divider()
    st.subheader("Jornada Completa")
    cliques = ms.total_clicks_sent(start, end)
    visitas = ms.total_traffic_visits(start, end)
    stage_labels, stage_values = ms.funnel_stage_counts(start, end)
    if not stage_labels and not cliques and not visitas:
        st.info("Sem dados suficientes para montar a jornada completa ainda.")
    else:
        journey_labels = ["Cliques enviados", "Visitas confirmadas (Amazon)"] + stage_labels
        journey_values = [cliques, visitas] + stage_values
        st.plotly_chart(
            charts.funnel_chart(journey_labels, journey_values, accent="amber"),
            width="stretch",
            theme="streamlit",
            height=480,
        )

    combined_metrics = [metric for metric in metrics if metric.show_in_combined_charts]

    st.divider()
    st.subheader(" · ".join(metric.label for metric in combined_metrics))
    granularity = st.segmented_control(
        "Granularidade",
        options=["Diário", "Semanal"],
        default="Diário",
        key="overview_granularity",
        label_visibility="collapsed",
    )
    if granularity == "Semanal":
        combined_df = ms.combined_weekly(series_by_metric, combined_metrics)
        chart_df = combined_df
        x_col = "semana"
    else:
        combined_df = ms.combined_daily(series_by_metric, combined_metrics)
        chart_df = combined_df[(combined_df["date"] >= start) & (combined_df["date"] <= end)] if not combined_df.empty else combined_df
        x_col = "date"

    if combined_df.empty:
        st.info("Sem dados para exibir ainda.")
    else:
        st.plotly_chart(
            charts.grouped_columns(chart_df, combined_metrics, x_col=x_col),
            width="stretch",
            theme="streamlit",
            height=360,
        )

    st.subheader("Proporção do total acumulado")
    totals = {metric.key: ms.total_all_time(series_by_metric[metric.key]) for metric in combined_metrics}
    if not any(totals.values()):
        st.info("Sem dados para exibir ainda.")
    else:
        st.plotly_chart(
            charts.proportion_pie(totals, combined_metrics),
            width="stretch",
            theme="streamlit",
            height=320,
        )
