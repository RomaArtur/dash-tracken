"""Métrica de Login.

Formato real observado no JSON fornecido:

    {
        "2026-08-17": 3,
        "2026-08-18": 8,
        ...
    }

Ou seja, um objeto simples de {data: total de logins no dia}. Não há
quebra por usuário/empresa nesse arquivo — a granularidade é diária e
agregada. Cada dia é, portanto, a chave natural do registro.
"""
from __future__ import annotations

import pandas as pd

from metrics.base import MetricDefinition

KEY = "login"

DDL = """
CREATE TABLE IF NOT EXISTS metric_login_daily (
    date DATE PRIMARY KEY,
    total_logins INTEGER NOT NULL,
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL
)
"""


def parse(raw: dict, context: dict | None = None) -> pd.DataFrame:
    if not isinstance(raw, dict):
        raise ValueError("O JSON de login deve ser um objeto no formato {'YYYY-MM-DD': total}.")
    return pd.DataFrame(
        [{"date": date_str, "total_logins": total} for date_str, total in raw.items()]
    )


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df

    df = df.copy()
    motivo = pd.Series("", index=df.index)

    parsed_date = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    bad_date = parsed_date.isna()
    motivo = motivo.where(~bad_date, motivo + "data inválida; ")

    total_numeric = pd.to_numeric(df["total_logins"], errors="coerce")
    bad_total = total_numeric.isna() | (total_numeric < 0)
    motivo = motivo.where(~bad_total, motivo + "total_logins inválido; ")

    invalid_mask = bad_date | bad_total
    valid = df.loc[~invalid_mask].copy()
    invalid = df.loc[invalid_mask].copy()
    invalid["_motivo"] = motivo.loc[invalid_mask]

    valid["date"] = parsed_date.loc[~invalid_mask].dt.date
    valid["total_logins"] = total_numeric.loc[~invalid_mask].astype(int)

    return valid, invalid


DEFINITION = MetricDefinition(
    key=KEY,
    label="Login",
    icon=":material/login:",
    table_name="metric_login_daily",
    key_columns=("date",),
    value_columns=("total_logins",),
    primary_value_column="total_logins",
    ddl=DDL,
    parse=parse,
    validate=validate,
    ranking_dimensions=None,
    accent="green",
)
