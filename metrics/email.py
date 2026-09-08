"""Métrica de Disparos E-mail.

Diferente de Login e Pop-up (que recebem JSON gerado internamente), o
disparo de e-mail vem de um CSV exportado do CRM de e-mail marketing,
um registro por destinatário de uma campanha:

    Nome;Email;"Status do envio";"Email Lido";Subscrição;"Data de criação";"Data de envio"
    ;3dunique@3dunique.com.br;Enviado;Lido;Ativa;"2026-09-08 09:44:40";"2026-09-08 11:54:47"
    ...

O CSV não identifica cliente nem campanha (o CRM não exporta isso).
Por convenção, o usuário nomeia o arquivo como
`email_<cliente>_<campanha>.csv` (ex.: `email_3dunique_11341.csv`); a
tela de importação (views/import_page.py) extrai esses dois valores do
nome do arquivo, deixa editáveis, e os injeta via `context` antes de
chamar `parse()` — por isso a chave natural do registro é (campaign_id,
email), não apenas email: o mesmo destinatário pode aparecer em
campanhas diferentes sem colidir.

Reimportar o mesmo CSV depois que alguém leu o e-mail (Email Lido muda
de "Não lido" para "Lido") atualiza o registro via UPSERT — mesmo
mecanismo genérico de idempotência usado por login/popup, sem lógica
nova.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from components import charts
from metrics.base import MetricDefinition
from repositories import metrics_repository
from services.database import get_connection
from utils.tokens import MUTED, accent_color

KEY = "email"

DDL = """
CREATE TABLE IF NOT EXISTS metric_email_campaign (
    campaign_id VARCHAR NOT NULL,
    cliente VARCHAR NOT NULL,
    email VARCHAR NOT NULL,
    date DATE NOT NULL,
    status_envio VARCHAR NOT NULL,
    enviado INTEGER NOT NULL,
    lido INTEGER NOT NULL,
    subscricao VARCHAR,
    data_criacao TIMESTAMP,
    data_envio TIMESTAMP,
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (campaign_id, email)
)
"""


def parse(raw: pd.DataFrame, context: dict | None = None) -> pd.DataFrame:
    if not isinstance(raw, pd.DataFrame):
        raise ValueError("O CSV de disparos de e-mail deve ser lido como uma tabela.")
    context = context or {}
    cliente = str(context.get("cliente") or "").strip()
    campaign_id = str(context.get("campaign_id") or "").strip()
    if not cliente or not campaign_id:
        raise ValueError("Cliente e campanha são obrigatórios para importar disparos de e-mail.")

    required_cols = {"Email", "Status do envio", "Email Lido", "Subscrição", "Data de criação", "Data de envio"}
    missing = required_cols - set(raw.columns)
    if missing:
        raise ValueError(f"Colunas ausentes no CSV: {', '.join(sorted(missing))}")

    df = pd.DataFrame(
        {
            "campaign_id": campaign_id,
            "cliente": cliente,
            "email": raw["Email"],
            "status_envio": raw["Status do envio"],
            "email_lido": raw["Email Lido"],
            "subscricao": raw["Subscrição"],
            "data_criacao": raw["Data de criação"],
            "data_envio": raw["Data de envio"],
        }
    )
    return df


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df

    df = df.copy()
    motivo = pd.Series("", index=df.index)

    email_norm = df["email"].astype(str).str.strip().str.lower()
    bad_email = email_norm.eq("") | ~email_norm.str.contains("@", regex=False)
    motivo = motivo.where(~bad_email, motivo + "email inválido; ")

    status_norm = df["status_envio"].astype(str).str.strip()
    bad_status = status_norm.eq("") | status_norm.eq("nan")
    motivo = motivo.where(~bad_status, motivo + "status do envio ausente; ")

    lido_map = {"Lido": 1, "Não lido": 0}
    lido_raw = df["email_lido"].astype(str).str.strip()
    bad_lido = ~lido_raw.isin(lido_map.keys())
    motivo = motivo.where(~bad_lido, motivo + "Email Lido inválido; ")

    subscricao_norm = df["subscricao"].astype(str).str.strip()
    bad_subscricao = subscricao_norm.eq("") | subscricao_norm.eq("nan")
    motivo = motivo.where(~bad_subscricao, motivo + "subscrição ausente; ")

    data_criacao = pd.to_datetime(df["data_criacao"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    bad_criacao = data_criacao.isna()
    motivo = motivo.where(~bad_criacao, motivo + "data de criação inválida; ")

    data_envio = pd.to_datetime(df["data_envio"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    bad_envio = data_envio.isna()
    motivo = motivo.where(~bad_envio, motivo + "data de envio inválida; ")

    invalid_mask = bad_email | bad_status | bad_lido | bad_subscricao | bad_criacao | bad_envio
    valid = df.loc[~invalid_mask].copy()
    invalid = df.loc[invalid_mask].copy()
    invalid["_motivo"] = motivo.loc[invalid_mask]

    valid["campaign_id"] = valid["campaign_id"].astype(str).str.strip()
    valid["cliente"] = valid["cliente"].astype(str).str.strip()
    valid["email"] = email_norm.loc[~invalid_mask]
    valid["status_envio"] = status_norm.loc[~invalid_mask]
    valid["enviado"] = (valid["status_envio"].str.lower() == "enviado").astype(int)
    valid["lido"] = lido_raw.loc[~invalid_mask].map(lido_map).astype(int)
    valid["subscricao"] = subscricao_norm.loc[~invalid_mask]
    valid["data_criacao"] = data_criacao.loc[~invalid_mask]
    valid["data_envio"] = data_envio.loc[~invalid_mask]
    valid["date"] = valid["data_envio"].dt.date
    valid = valid.drop(columns=["email_lido"])

    return valid, invalid


def render_summary(cliente: str | None, start: date, end: date) -> None:
    """Resumo da campanha (enviados, abertos e a proporção entre eles)
    no lugar do KPI genérico de 'total do período' — layout pedido pelo
    usuário como referência para a página de Disparos E-mail."""
    conn = get_connection()
    filters = {"cliente": cliente} if cliente else None
    df = metrics_repository.fetch_metric_df(conn, DEFINITION, date_from=start, date_to=end, filters=filters)

    enviados = int(df["enviado"].sum()) if not df.empty else 0
    abertos = int(df["lido"].sum()) if not df.empty else 0
    nao_abertos = enviados - abertos
    taxa_abertura = (abertos / enviados * 100) if enviados else 0.0

    col1, col2 = st.columns(2)
    with col1:
        with st.container(key="tk-accent-blue-email-enviados", border=True):
            st.metric("E-mails enviados", enviados, icon=":material/mail:")
    with col2:
        with st.container(key="tk-accent-blue-email-abertos", border=True):
            st.metric(f"E-mails abertos ({taxa_abertura:.0f}%)", abertos, icon=":material/mark_email_read:")

    with st.container(border=True):
        st.subheader("Alcance dos envios")
        if enviados == 0:
            st.info("Sem dados para o período selecionado.")
        else:
            fig = charts.donut_breakdown(
                labels=["Abertos", "Não abertos"],
                values=[abertos, nao_abertos],
                colors=[accent_color("blue"), MUTED],
            )
            st.plotly_chart(fig, width="stretch", theme="streamlit", height=280)


DEFINITION = MetricDefinition(
    key=KEY,
    label="Disparos E-mail",
    icon=":material/mail:",
    table_name="metric_email_campaign",
    key_columns=("campaign_id", "email"),
    value_columns=("cliente", "status_envio", "enviado", "lido", "subscricao", "date", "data_criacao", "data_envio"),
    primary_value_column="enviado",
    ddl=DDL,
    parse=parse,
    validate=validate,
    date_column="date",
    ranking_dimensions={"cliente": "Cliente", "campaign_id": "Campanha"},
    accent="blue",
    file_format="csv",
    render_summary=render_summary,
    show_trend_charts=False,
    show_in_combined_charts=False,
)
