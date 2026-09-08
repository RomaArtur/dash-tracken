"""Métrica de Pop-up.

Formato real observado no JSON fornecido:

    {
        "2026-08-19": {
            "total": 20,
            "usuarios": [
                {
                    "coduser": "5778",
                    "codemp": "2",
                    "cliques": 2,
                    "primeiro_clique": "2026-08-19T07:15:59-03:00",
                    "ultimo_clique": "2026-08-19T07:16:30-03:00"
                },
                ...
            ]
        },
        ...
    }

Granularidade: um registro por (dia, usuário, empresa). O campo "total"
é redundante (soma de "cliques" dos usuários do dia) e não é
persistido — é recalculado a partir dos registros normalizados sempre
que necessário, para evitar duas fontes de verdade divergentes.

A combinação (date, coduser, codemp) não se repete dentro do mesmo dia
no arquivo real analisado, então essa é a chave natural do registro.
"""
from __future__ import annotations

import pandas as pd

from metrics.base import MetricDefinition

KEY = "popup"

DDL = """
CREATE TABLE IF NOT EXISTS metric_popup_daily (
    date DATE NOT NULL,
    coduser VARCHAR NOT NULL,
    codemp VARCHAR NOT NULL,
    cliques INTEGER NOT NULL,
    primeiro_clique TIMESTAMP,
    ultimo_clique TIMESTAMP,
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (date, coduser, codemp)
)
"""


def parse(raw: dict, context: dict | None = None) -> pd.DataFrame:
    if not isinstance(raw, dict):
        raise ValueError("O JSON de popup deve ser um objeto indexado por data.")

    rows = []
    for date_str, day_payload in raw.items():
        usuarios = (day_payload or {}).get("usuarios", []) if isinstance(day_payload, dict) else []
        for usuario in usuarios:
            rows.append(
                {
                    "date": date_str,
                    "coduser": usuario.get("coduser"),
                    "codemp": usuario.get("codemp"),
                    "cliques": usuario.get("cliques"),
                    "primeiro_clique": usuario.get("primeiro_clique"),
                    "ultimo_clique": usuario.get("ultimo_clique"),
                }
            )
    return pd.DataFrame(rows)


def _parse_local_naive(series: pd.Series) -> pd.Series:
    """Interpreta timestamps ISO com offset (ex.: '...T07:15:59-03:00')
    mantendo o horário local exatamente como enviado, apenas descartando
    o offset — evita conversões de fuso horário desnecessárias já que o
    sistema de origem sempre envia no mesmo fuso."""
    stripped = series.astype(str).str.slice(0, 19)
    return pd.to_datetime(stripped, format="%Y-%m-%dT%H:%M:%S", errors="coerce")


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df

    df = df.copy()
    motivo = pd.Series("", index=df.index)

    parsed_date = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    bad_date = parsed_date.isna()
    motivo = motivo.where(~bad_date, motivo + "data inválida; ")

    bad_user = df["coduser"].isna() | (df["coduser"].astype(str).str.strip() == "")
    motivo = motivo.where(~bad_user, motivo + "coduser ausente; ")

    bad_emp = df["codemp"].isna() | (df["codemp"].astype(str).str.strip() == "")
    motivo = motivo.where(~bad_emp, motivo + "codemp ausente; ")

    cliques_numeric = pd.to_numeric(df["cliques"], errors="coerce")
    bad_cliques = cliques_numeric.isna() | (cliques_numeric < 0)
    motivo = motivo.where(~bad_cliques, motivo + "cliques inválido; ")

    primeiro = _parse_local_naive(df["primeiro_clique"])
    ultimo = _parse_local_naive(df["ultimo_clique"])
    bad_primeiro = primeiro.isna()
    bad_ultimo = ultimo.isna()
    motivo = motivo.where(~bad_primeiro, motivo + "primeiro_clique inválido; ")
    motivo = motivo.where(~bad_ultimo, motivo + "ultimo_clique inválido; ")

    invalid_mask = bad_date | bad_user | bad_emp | bad_cliques | bad_primeiro | bad_ultimo
    valid = df.loc[~invalid_mask].copy()
    invalid = df.loc[invalid_mask].copy()
    invalid["_motivo"] = motivo.loc[invalid_mask]

    valid["date"] = parsed_date.loc[~invalid_mask].dt.date
    valid["coduser"] = valid["coduser"].astype(str).str.strip()
    valid["codemp"] = valid["codemp"].astype(str).str.strip()
    valid["cliques"] = cliques_numeric.loc[~invalid_mask].astype(int)
    valid["primeiro_clique"] = primeiro.loc[~invalid_mask]
    valid["ultimo_clique"] = ultimo.loc[~invalid_mask]

    return valid, invalid


DEFINITION = MetricDefinition(
    key=KEY,
    label="Pop-up",
    icon=":material/ads_click:",
    table_name="metric_popup_daily",
    key_columns=("date", "coduser", "codemp"),
    value_columns=("cliques", "primeiro_clique", "ultimo_clique"),
    primary_value_column="cliques",
    ddl=DDL,
    parse=parse,
    validate=validate,
    ranking_dimensions=None,
    accent="purple",
)
