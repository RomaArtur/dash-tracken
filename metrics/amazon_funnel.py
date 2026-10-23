"""Métrica de Funil de Cadastro Amazon (aba 'funnel' do relatório
semanal que a Amazon envia).

Uma linha por vendedor (`merchant_customer_id`) que veio de um clique
de campanha do Tracken, com o timestamp de cada etapa do cadastro na
Amazon: Reg Start (criou login) -> Reg Complete (dados da empresa) ->
RV/'Registration Verified' (Amazon aprovou documentos) -> KYC (docs do
responsável) -> RTL/'Ready to Launch' -> Launch (produto ativo) -> FBA
Launch. Cada etapa é opcional/progressiva — um vendedor pode aparecer
com só Reg Start preenchido numa semana e ganhar mais etapas nas
seguintes, por isso a chave natural é só o vendedor: reimportar
atualiza o progresso dele via UPSERT, sem lógica adicional.

`date` é `registration_start_date` truncado — não existe no arquivo
original, é calculado aqui só para o filtro de período genérico
(`metrics_repository.fetch_metric_df`) funcionar como nas demais
métricas."""
from __future__ import annotations

import pandas as pd

from metrics.amazon_common import CHANNEL_BY_SOURCE_DETAIL
from metrics.base import MetricDefinition

KEY = "amazon_funnel"

DDL = """
CREATE TABLE IF NOT EXISTS metric_amazon_funnel (
    merchant_customer_id VARCHAR PRIMARY KEY,
    channel VARCHAR NOT NULL,
    date DATE NOT NULL,
    registration_start_date TIMESTAMP NOT NULL,
    registration_complete_date TIMESTAMP,
    siv_approved_indicator INTEGER,
    kyctrigger_date TIMESTAMP,
    rtl_date TIMESTAMP,
    launch_date TIMESTAMP,
    fba_launch_date TIMESTAMP,
    seller_state VARCHAR,
    is_fba_eligible VARCHAR,
    registros INTEGER NOT NULL,
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL
)
"""

_SOURCE_COLUMNS = (
    "merchant_customer_id",
    "source_detail",
    "registration_start_date",
    "registration_complete_date",
    "siv_approved_indicator",
    "kyctrigger_date",
    "rtl_date",
    "launch_date",
    "fba_launch_date",
    "seller_state",
    "is_fba_eligible",
)


def parse(raw: pd.DataFrame, context: dict | None = None) -> pd.DataFrame:
    if not isinstance(raw, pd.DataFrame):
        raise ValueError("A aba de funil da Amazon deve ser lida como uma tabela.")

    missing = set(_SOURCE_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"Colunas ausentes na aba 'funnel': {', '.join(sorted(missing))}")

    df = raw.dropna(how="all")[list(_SOURCE_COLUMNS)].copy()
    df = df.rename(columns={"source_detail": "channel"})
    return df


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df

    df = df.copy()
    motivo = pd.Series("", index=df.index)

    merchant_id = df["merchant_customer_id"].astype(str).str.strip()
    bad_merchant = merchant_id.eq("") | merchant_id.eq("nan")
    motivo = motivo.where(~bad_merchant, motivo + "merchant_customer_id ausente; ")

    channel_mapped = df["channel"].map(CHANNEL_BY_SOURCE_DETAIL)
    bad_channel = channel_mapped.isna()
    motivo = motivo.where(~bad_channel, motivo + "canal não reconhecido; ")

    reg_start = pd.to_datetime(df["registration_start_date"], errors="coerce")
    bad_reg_start = reg_start.isna()
    motivo = motivo.where(~bad_reg_start, motivo + "registration_start_date inválido; ")

    invalid_mask = bad_merchant | bad_channel | bad_reg_start
    valid = df.loc[~invalid_mask].copy()
    invalid = df.loc[invalid_mask].copy()
    invalid["_motivo"] = motivo.loc[invalid_mask]

    valid["merchant_customer_id"] = merchant_id.loc[~invalid_mask]
    valid["channel"] = channel_mapped.loc[~invalid_mask]
    valid["registration_start_date"] = reg_start.loc[~invalid_mask]
    valid["date"] = valid["registration_start_date"].dt.date

    # Colunas opcionais/progressivas: convertidas para objeto com `None`
    # nativo do Python (em vez de NaT/pd.NA) nos ausentes, porque o
    # driver do Postgres não sabe adaptar os tipos nulos do pandas ao
    # gravar NULL — só None e datetime/int comuns.
    for col in (
        "registration_complete_date",
        "kyctrigger_date",
        "rtl_date",
        "launch_date",
        "fba_launch_date",
    ):
        parsed = pd.to_datetime(valid[col], errors="coerce")
        valid[col] = parsed.astype(object).where(parsed.notna(), None)

    siv_numeric = pd.to_numeric(valid["siv_approved_indicator"], errors="coerce")
    valid["siv_approved_indicator"] = pd.Series(
        [int(v) if pd.notna(v) else None for v in siv_numeric], index=valid.index, dtype=object
    )
    valid["seller_state"] = valid["seller_state"].astype(object).where(valid["seller_state"].notna(), None)
    valid["is_fba_eligible"] = valid["is_fba_eligible"].astype(object).where(valid["is_fba_eligible"].notna(), None)
    valid["registros"] = 1

    return valid, invalid


DEFINITION = MetricDefinition(
    key=KEY,
    label="Funil de Cadastro Amazon",
    icon=":material/filter_alt:",
    table_name="metric_amazon_funnel",
    key_columns=("merchant_customer_id",),
    value_columns=(
        "channel",
        "registration_complete_date",
        "siv_approved_indicator",
        "kyctrigger_date",
        "rtl_date",
        "launch_date",
        "fba_launch_date",
        "seller_state",
        "is_fba_eligible",
        "registros",
        "date",
        "registration_start_date",
    ),
    primary_value_column="registros",
    ddl=DDL,
    parse=parse,
    validate=validate,
    date_column="date",
    accent="green",
    file_format="xlsx",
    xlsx_sheet="funnel",
    standalone_page=False,
    show_in_overview=False,
)
