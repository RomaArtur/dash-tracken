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
from services.database import get_connection

_FUNNEL_STAGES: list[tuple[str, str]] = [
    ("registration_start_date", "Reg Start"),
    ("registration_complete_date", "Reg Complete"),
    ("siv_approved_indicator", "Verificado (RV)"),
    ("kyctrigger_date", "KYC"),
    ("rtl_date", "Ready to Launch"),
    ("launch_date", "Launch"),
    ("fba_launch_date", "FBA Launch"),
]


def _clicks_sent(channel_key: str, start, end) -> int | None:
    """Total de cliques já importados pro canal no período, ou None se
    o canal ainda não tem métrica própria de disparo (caso do
    WhatsApp, só com placeholder por enquanto)."""
    if channel_key not in METRICS:
        return None
    daily_df = ms.load_daily_series_cached(channel_key)
    if daily_df.empty:
        return 0
    mask = (daily_df["date"] >= start) & (daily_df["date"] <= end)
    return int(daily_df.loc[mask, "value"].sum())


def _traffic_visits(channel_key: str, start, end) -> int:
    conn = get_connection()
    df = metrics_repository.fetch_metric_df(
        conn, METRICS["amazon_traffic"], date_from=start, date_to=end, filters={"channel": channel_key}
    )
    return int(df["visits"].sum()) if not df.empty else 0


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
        clicks = _clicks_sent(channel_key, start, end)
        visits = _traffic_visits(channel_key, start, end)
        with col:
            with st.container(key=f"tk-accent-amber-amazon-{channel_key}", border=True):
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

    stage_labels = [label for _, label in _FUNNEL_STAGES]
    stage_values = []
    for col, _ in _FUNNEL_STAGES:
        if col == "siv_approved_indicator":
            stage_values.append(int((funnel_df[col] == 1).sum()))
        else:
            stage_values.append(int(funnel_df[col].notna().sum()))

    st.plotly_chart(
        charts.funnel_chart(stage_labels, stage_values, accent="amber"),
        width="stretch",
        theme="streamlit",
        height=380,
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
