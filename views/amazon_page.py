"""Página combinada 'Amazon': cruza o retorno que a Amazon manda sobre
as campanhas do Tracken com os dados que o dash já importa.

Duas métricas alimentam essa página (metrics/amazon_traffic.py e
metrics/amazon_funnel.py), mas nenhuma das duas tem página própria no
menu (`standalone_page=False`) — o usuário pediu uma seção única, não
duas páginas separadas, já que os dois conjuntos de dados vêm do mesmo
relatório semanal da Amazon e se complementam."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components import charts, filters
from metrics.amazon_common import CHANNEL_LABELS
from metrics import METRICS
from repositories import metrics_repository
from services import metrics_service as ms
from services.amazon_conversions import conversion_rates, funnel_counts
from services.database import get_connection
from utils.tokens import AMAZON_GREENS


def render_amazon_page() -> None:
    st.title("Amazon")
    st.caption(
        "Retorno da Amazon sobre as campanhas do Tracken: visitas confirmadas na página de "
        "cadastro de vendedor e o quanto cada vendedor avançou no cadastro."
    )

    start, end = filters.period_filter(key_prefix="amazon")

    st.subheader("Tráfego x Cliques")
    cols = st.columns(len(CHANNEL_LABELS))
    for col, (channel_key, channel_label) in zip(cols, CHANNEL_LABELS.items()):
        clicks = ms.clicks_sent(channel_key, start, end)
        visits = ms.traffic_visits(channel_key, start, end)
        with col:
            with st.container(key=f"tk-accent-green-amazon-{channel_key}", border=True):
                st.markdown(f"**{channel_label}**")
                st.metric("Visitas confirmadas (Amazon)", visits, icon=":material/travel_explore:")
                if clicks is None:
                    st.caption("Cliques enviados: ainda não disponível")
                else:
                    taxa = f"{(visits / clicks * 100):.1f}%" if clicks else "—"
                    st.metric("Cliques enviados", clicks, icon=":material/ads_click:")
                    st.caption(f"Taxa de conversão clique → visita: {taxa}")

    st.divider()
    st.subheader("Funil de Cadastro")
    conn = get_connection()
    funnel_df = metrics_repository.fetch_metric_df(
        conn, METRICS["amazon_funnel"], date_from=start, date_to=end
    )

    if funnel_df.empty:
        st.info("Sem vendedores com início de cadastro no período selecionado.")
        return

    stage_labels, stage_values = funnel_counts(funnel_df)

    st.plotly_chart(
        charts.funnel_chart(stage_labels, stage_values, colors=AMAZON_GREENS[:len(stage_labels)]),
        width="stretch",
        theme="streamlit",
        height=380,
    )

    st.divider()
    st.subheader("Conversão entre etapas")
    st.caption(
        "Base: vendedores que iniciaram o cadastro no período selecionado, com o avanço registrado "
        "no último arquivo importado. Tráfego considera as visitas da Amazon no mesmo período."
    )
    traffic_df = metrics_repository.fetch_metric_df(conn, METRICS["amazon_traffic"], date_from=start, date_to=end)
    conversions = conversion_rates(funnel_df, traffic_df)
    indexed = conversions.set_index("key")
    for col, key in zip(st.columns(3), ("traffic_rs", "rs_rtl", "rs_launch")):
        row = indexed.loc[key]
        with col:
            with st.container(key=f"tk-accent-green-amazon-conversion-{key}", border=True):
                rate = f"{row['rate']:.1f}%".replace(".", ",") if pd.notna(row["rate"]) else "—"
                st.metric(row["label"], rate, icon=":material/trending_up:")
                st.caption(
                    f"{int(row['converted'])} de {int(row['base'])}"
                    if pd.notna(row["base"]) and row["base"] > 0 else "Sem base para calcular a conversão."
                )
    st.plotly_chart(charts.conversion_bars(conversions), width="stretch", theme="streamlit", height=400)
    with st.expander("Bases e cálculos das conversões", icon=":material/calculate:"):
        st.dataframe(
            conversions[["label", "base", "converted", "rate"]].rename(columns={
                "label": "Conversão", "base": "Base", "converted": "Convertidos", "rate": "Taxa (%)",
            }),
            column_config={"Taxa (%)": st.column_config.NumberColumn(format="%.1f%%")},
            width="stretch", hide_index=True,
        )
        st.caption(
            "Taxa = convertidos ÷ base × 100. Sem base, a taxa aparece como n/a. "
            "A conversão FBA usa os vendedores elegíveis para FBA como base."
        )

    with st.expander("Vendedores no período", icon=":material/list_alt:"):
        display_df = funnel_df.rename(
            columns={
                "merchant_customer_id": "Vendedor",
                "channel": "Canal",
                "seller_state": "Estado",
                "launch_date": "Lançou em",
            }
        )
        display_df["Lançou em"] = [
            v.strftime("%Y-%m-%d") if pd.notna(v) else "" for v in display_df["Lançou em"]
        ]
        st.dataframe(
            display_df[["Vendedor", "Canal", "Estado", "Lançou em"]],
            width="stretch",
            hide_index=True,
        )
