"""Métrica de Tráfego Amazon (aba 'traffic' do relatório semanal que a
Amazon envia).

Formato real observado no Excel:

    metric_flag | marketplace_id | day        | source       | source_detail  | device_type | visits_num
    Visits      | 526970         | 2026-08-29 | Partnerships | pop - tracken  | Mobile      | 3

`metric_flag`, `marketplace_id` e `source` são constantes no arquivo
(sempre 'Visits', o marketplace do Brasil, e 'Partnerships') — não
carregam informação por linha, então não viram coluna na tabela.
`source_detail` identifica o canal do Tracken (ver
metrics/amazon_common.py); pode haver mais de uma linha por
(dia, canal) se `device_type` variar. A validação converte as visitas
em números antes de agrupá-las por dia e canal.

Não vem por JSON/CSV como as demais métricas: é uma aba de um arquivo
Excel de múltiplas abas (ver `file_format='xlsx'` e `xlsx_sheet`) — o
usuário sobe o mesmo arquivo aqui e em metrics/amazon_funnel.py,
escolhendo a métrica correspondente a cada vez."""
from __future__ import annotations

import pandas as pd

from metrics.amazon_common import CHANNEL_BY_SOURCE_DETAIL
from metrics.base import MetricDefinition

KEY = "amazon_traffic"

DDL = """
CREATE TABLE IF NOT EXISTS metric_amazon_traffic (
    date DATE NOT NULL,
    channel VARCHAR NOT NULL,
    visits INTEGER NOT NULL,
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (date, channel)
)
"""


def parse(raw: pd.DataFrame, context: dict | None = None) -> pd.DataFrame:
    if not isinstance(raw, pd.DataFrame):
        raise ValueError("A aba de tráfego da Amazon deve ser lida como uma tabela.")

    required_cols = {"day", "source_detail", "visits_num"}
    missing = required_cols - set(raw.columns)
    if missing:
        raise ValueError(f"Colunas ausentes na aba 'traffic': {', '.join(sorted(missing))}")

    raw = raw.dropna(how="all")
    df = pd.DataFrame(
        {
            "date": raw["day"],
            "channel": raw["source_detail"],
            "visits": raw["visits_num"],
        }
    )
    return df


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df

    df = df.copy()
    motivo = pd.Series("", index=df.index)

    parsed_date = pd.to_datetime(df["date"], errors="coerce")
    bad_date = parsed_date.isna()
    motivo = motivo.where(~bad_date, motivo + "data inválida; ")

    channel_mapped = df["channel"].map(CHANNEL_BY_SOURCE_DETAIL)
    bad_channel = channel_mapped.isna()
    motivo = motivo.where(~bad_channel, motivo + "canal não reconhecido; ")

    visits_numeric = pd.to_numeric(df["visits"], errors="coerce")
    bad_visits = (
        visits_numeric.isna()
        | ~visits_numeric.between(0, 2_147_483_647)
        | visits_numeric.ne(visits_numeric.round())
    ).fillna(True)
    motivo = motivo.where(~bad_visits, motivo + "visits_num inválido; ")

    invalid_mask = bad_date | bad_channel | bad_visits
    valid = df.loc[~invalid_mask].copy()
    invalid = df.loc[invalid_mask].copy()
    invalid["_motivo"] = motivo.loc[invalid_mask]

    valid["date"] = parsed_date.loc[~invalid_mask].dt.date
    valid["channel"] = channel_mapped.loc[~invalid_mask]
    valid["visits"] = visits_numeric.loc[~invalid_mask].astype(int)
    valid = valid.groupby(["date", "channel"], as_index=False)["visits"].sum()

    return valid, invalid


DEFINITION = MetricDefinition(
    key=KEY,
    label="Tráfego Amazon",
    icon=":material/travel_explore:",
    table_name="metric_amazon_traffic",
    key_columns=("date", "channel"),
    value_columns=("visits",),
    primary_value_column="visits",
    ddl=DDL,
    parse=parse,
    validate=validate,
    date_column="date",
    accent="green",
    file_format="xlsx",
    xlsx_sheet="traffic",
    standalone_page=False,
    show_in_overview=False,
)
