"""Disparos de WhatsApp: um resumo por campanha, importado de CSV.

Cliente vem dos metadados da importação. Campanha pode vir da coluna
Campanha, permitindo importar várias campanhas do mesmo cliente juntas,
ou dos metadados, como no E-mail. Reimportar atualiza o resumo existente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from metrics.base import MetricDefinition
from repositories import metrics_repository
from services.database import get_connection

KEY = "whatsapp"
CSV_TEMPLATE = (
    "Campanha;Data de envio;Total de contatos;Enviados;Entregues;Abertos\n"
).encode("utf-8-sig")
_COUNT_COLUMNS = {
    "total_contatos": "Total de contatos",
    "enviados": "Enviados",
    "entregues": "Entregues",
    "abertos": "Abertos",
}

DDL = """
CREATE TABLE IF NOT EXISTS metric_whatsapp_campaign (
    cliente VARCHAR NOT NULL,
    campaign_id VARCHAR NOT NULL,
    date DATE NOT NULL,
    disparos INTEGER NOT NULL CHECK (disparos = 1),
    total_contatos INTEGER NOT NULL,
    enviados INTEGER NOT NULL,
    entregues INTEGER NOT NULL,
    abertos INTEGER NOT NULL,
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (cliente, campaign_id),
    CHECK (0 <= abertos AND abertos <= entregues
           AND entregues <= enviados AND enviados <= total_contatos)
)
"""


def parse(raw: pd.DataFrame, context: dict | None = None) -> pd.DataFrame:
    if not isinstance(raw, pd.DataFrame):
        raise ValueError("Os disparos de WhatsApp devem ser importados de uma tabela CSV.")
    context = context or {}
    cliente = str(context.get("cliente") or "").strip()
    if not cliente:
        raise ValueError("Cliente é obrigatório para importar disparos de WhatsApp.")

    required = {"Data de envio", *_COUNT_COLUMNS.values()}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Colunas ausentes no CSV: {', '.join(sorted(missing))}")
    campaign_id = str(context.get("campaign_id") or "").strip()
    if "Campanha" not in raw.columns and not campaign_id:
        raise ValueError("Informe a campanha ou inclua a coluna 'Campanha' no CSV.")

    return pd.DataFrame(
        {
            "cliente": cliente,
            "campaign_id": raw["Campanha"] if "Campanha" in raw.columns else campaign_id,
            "date": raw["Data de envio"],
            "disparos": 1,
            **{column: raw[source] for column, source in _COUNT_COLUMNS.items()},
        }
    )


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df
    df = df.copy()
    motivo = pd.Series("", index=df.index)

    for column, label in (("cliente", "cliente"), ("campaign_id", "campanha")):
        normalized = df[column].astype("string").str.strip()
        bad = normalized.isna() | normalized.eq("")
        motivo = motivo.where(~bad, motivo + f"{label} ausente; ")
        df[column] = normalized

    dates = df["date"].astype("string").str.strip()
    parsed_date = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce")
    parsed_date = parsed_date.fillna(
        pd.to_datetime(dates, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    )
    motivo = motivo.where(parsed_date.notna(), motivo + "data de envio inválida; ")

    numeric = {}
    for column, label in _COUNT_COLUMNS.items():
        values = pd.to_numeric(df[column], errors="coerce")
        bad = (
            values.isna()
            | ~values.between(0, 2_147_483_647)
            | values.ne(values.round())
        ).fillna(True)
        motivo = motivo.where(~bad, motivo + f"{label} deve ser um inteiro não negativo; ")
        numeric[column] = values

    for lower, upper, reason in (
        ("enviados", "total_contatos", "enviados maior que o total de contatos; "),
        ("entregues", "enviados", "entregues maior que enviados; "),
        ("abertos", "entregues", "abertos maior que entregues; "),
    ):
        bad = (numeric[lower] > numeric[upper]).fillna(False)
        motivo = motivo.where(~bad, motivo + reason)

    duplicate = df.duplicated(["cliente", "campaign_id"], keep=False)
    motivo = motivo.where(~duplicate, motivo + "campanha repetida no arquivo; use uma linha por disparo; ")
    invalid_mask = motivo.ne("")
    valid = df.loc[~invalid_mask].copy()
    invalid = df.loc[invalid_mask].copy()
    invalid["_motivo"] = motivo.loc[invalid_mask]
    valid["date"] = parsed_date.loc[~invalid_mask].dt.date
    for column, values in numeric.items():
        valid[column] = values.loc[~invalid_mask].astype(int)
    return valid, invalid


@dataclass(frozen=True)
class WhatsAppSummary:
    disparos: int = 0
    contatos: int = 0
    taxa_entrega: float = 0.0
    taxa_abertura: float = 0.0


def summarize(df: pd.DataFrame) -> WhatsAppSummary:
    """Taxas ponderadas pelos volumes, sem calcular média de percentuais.

    Os contatos são somados por campanha; a mesma pessoa pode fazer
    parte de campanhas diferentes e ser contada em cada público-alvo.
    """
    if df.empty:
        return WhatsAppSummary()
    enviados = int(df["enviados"].sum())
    entregues = int(df["entregues"].sum())
    abertos = int(df["abertos"].sum())
    return WhatsAppSummary(
        disparos=int(df["disparos"].sum()),
        contatos=int(df["total_contatos"].sum()),
        taxa_entrega=entregues / enviados * 100 if enviados else 0.0,
        taxa_abertura=abertos / entregues * 100 if entregues else 0.0,
    )


def _percentage(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".").replace(".", ",") + "%"


def render_summary(cliente: str | None, start: date, end: date) -> None:
    filters = {"cliente": cliente} if cliente else None
    df = metrics_repository.fetch_metric_df(
        get_connection(), DEFINITION, date_from=start, date_to=end, filters=filters
    )
    summary = summarize(df)
    daily = (
        df.groupby("date", sort=True)[["enviados", "entregues", "abertos"]].sum()
        if not df.empty else pd.DataFrame(columns=["enviados", "entregues", "abertos"])
    )
    delivery_trend = daily["entregues"].div(daily["enviados"].replace(0, float("nan"))).fillna(0) * 100
    open_trend = daily["abertos"].div(daily["entregues"].replace(0, float("nan"))).fillna(0) * 100
    specs = [
        ("Total de Disparos em Massa", f"{summary.disparos:,}".replace(",", "."),
         ":material/cell_tower:", "green", None, "Quantidade de campanhas/disparos no período selecionado."),
        ("Total de contatos", f"{summary.contatos:,}".replace(",", "."),
         ":material/groups:", "blue", None, "Soma dos públicos-alvo das campanhas. Contatos presentes em mais de uma campanha são contados em cada uma."),
        ("Taxa média de entrega", _percentage(summary.taxa_entrega),
         ":material/done_all:", "green", delivery_trend, "Total de entregues ÷ total de enviados no período."),
        ("Taxa média de abertura", _percentage(summary.taxa_abertura),
         ":material/mark_email_read:", "amber", open_trend, "Total de abertos ÷ total de entregues no período."),
    ]
    for index, (col, spec) in enumerate(zip(st.columns(4), specs)):
        label, value, icon, accent, trend, help_text = spec
        with col:
            with st.container(key=f"tk-accent-{accent}-whatsapp-{index}"):
                st.metric(
                    label, value, icon=icon, border=True, help=help_text,
                    chart_data=trend if trend is not None and not trend.empty else None,
                    chart_type="bar",
                )

    if df.empty:
        st.info("Sem disparos de WhatsApp para o período e cliente selecionados.")
    else:
        with st.expander("Disparos no período", icon=":material/list_alt:"):
            labels = {
                "date": "Data de envio", "cliente": "Cliente", "campaign_id": "Campanha",
                "total_contatos": "Contatos", "enviados": "Enviados", "entregues": "Entregues", "abertos": "Abertos",
            }
            st.dataframe(
                df.sort_values("date", ascending=False)[list(labels)].rename(columns=labels),
                width="stretch", hide_index=True,
            )

    with st.expander("Como importar os disparos de WhatsApp", icon=":material/upload_file:"):
        st.write(
            "Em Importar Dados, escolha Disparos WhatsApp e envie um CSV separado por ponto e vírgula, "
            "com uma linha por campanha/disparo. Informe o cliente na importação. "
            "O nome whatsapp_<cliente>_<campanha>.csv sugere esses campos automaticamente."
        )
        st.write(
            "Use as colunas Campanha, Data de envio, Total de contatos, Enviados, Entregues e Abertos. "
            "A data deve estar em AAAA-MM-DD, opcionalmente com HH:MM:SS. "
            "Se o arquivo tiver uma única campanha, ela pode ser informada na importação em vez da coluna Campanha. "
            "Para um novo disparo da mesma campanha, use um ID diferente."
        )
        st.download_button(
            "Baixar modelo CSV", data=CSV_TEMPLATE, file_name="whatsapp_cliente_campanhas.csv",
            mime="text/csv", key="whatsapp_csv_template", icon=":material/download:",
        )


DEFINITION = MetricDefinition(
    key=KEY,
    label="Disparos WhatsApp",
    icon=":material/chat:",
    table_name="metric_whatsapp_campaign",
    key_columns=("cliente", "campaign_id"),
    value_columns=("date", "disparos", "total_contatos", "enviados", "entregues", "abertos"),
    primary_value_column="disparos",
    ddl=DDL,
    parse=parse,
    validate=validate,
    ranking_dimensions={"cliente": "Cliente"},
    accent="green",
    file_format="csv",
    csv_campaign_column="Campanha",
    render_summary=render_summary,
    show_trend_charts=False,
    show_in_combined_charts=False,
)
