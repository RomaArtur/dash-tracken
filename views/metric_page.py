"""Página genérica de detalhe de uma métrica (Login, Pop-up, e futuras).

Uma única implementação atende qualquer métrica registrada em
`metrics.METRICS` — adicionar uma métrica nova não exige criar uma nova
página, apenas registrar sua MetricDefinition (ver metrics/__init__.py)."""
from __future__ import annotations

import streamlit as st

from components import cards, charts, filters
from metrics import METRICS
from services import metrics_service as ms


def render_metric_page(metric_key: str) -> None:
    metric = METRICS[metric_key]
    st.title(metric.label)

    start, end = filters.period_filter(key_prefix=metric_key)
    prev_start, prev_end = ms.previous_period(start, end)

    daily_df = ms.load_daily_series_cached(metric_key)
    period_df = daily_df[(daily_df["date"] >= start) & (daily_df["date"] <= end)]

    kpi = ms.period_kpi(
        daily_df, start, end, prev_start, prev_end, label=f"Total de {metric.label.lower()}"
    )
    cards.kpi_row([kpi], [metric], [period_df["value"] if not period_df.empty else None])

    with st.container(border=True):
        st.subheader("Evolução")
        if period_df.empty:
            st.info("Sem dados para o período selecionado.")
        else:
            st.plotly_chart(
                charts.line_evolution(period_df, accent=metric.accent),
                width="stretch",
                theme="streamlit",
                height=320,
            )

    with st.container(border=True):
        st.subheader("Comparação semanal")
        weekly_df = ms.weekly_comparison(daily_df)
        if weekly_df.empty:
            st.info("Sem dados suficientes para comparação semanal.")
        else:
            st.plotly_chart(
                charts.weekly_bar(weekly_df, accent=metric.accent),
                width="stretch",
                theme="streamlit",
                height=320,
            )

    if metric.ranking_dimensions:
        dim_col, dim_label = next(iter(metric.ranking_dimensions.items()))
        with st.container(border=True):
            st.subheader(f"Ranking por {dim_label.lower()}")
            ranking_df = ms.top_dimension(metric, dim_col, start, end)
            if ranking_df.empty:
                st.info("Sem dados para ranking no período.")
            else:
                st.plotly_chart(
                    charts.ranking_horizontal(ranking_df, label_col=dim_col, accent=metric.accent),
                    width="stretch",
                    theme="streamlit",
                )
                st.dataframe(
                    ranking_df.rename(columns={dim_col: dim_label, "value": "Total"}),
                    width="stretch",
                    hide_index=True,
                )
