"""Acesso genérico às tabelas de métricas.

Todas as funções operam a partir de uma `MetricDefinition`, sem conhecer
particularidades de login/popup/futuras métricas — isso é o que
mantém a aplicação extensível sem precisar de um repositório por métrica.
"""
from __future__ import annotations

from datetime import date, datetime

import duckdb
import pandas as pd

from metrics.base import MetricDefinition


def fetch_existing_keys(conn: duckdb.DuckDBPyConnection, metric: MetricDefinition) -> pd.DataFrame:
    """Carrega chave natural + colunas de valor já persistidas, usadas
    para comparar com o arquivo importado e detectar novos/atualizados/
    inalterados."""
    cols = list(metric.key_columns) + list(metric.value_columns)
    col_list = ", ".join(cols)
    return conn.execute(f"SELECT {col_list} FROM {metric.table_name}").fetch_df()


def upsert(
    conn: duckdb.DuckDBPyConnection,
    metric: MetricDefinition,
    df: pd.DataFrame,
    import_run_id: int,
) -> None:
    """Insere registros novos e atualiza os que já existem (mesma chave
    natural, valor diferente). Registros inalterados não devem ser
    passados aqui (o chamador já os filtrou)."""
    if df.empty:
        return

    staged = df.copy()
    staged["import_run_id"] = import_run_id
    staged["updated_at"] = datetime.now()

    key_cols = list(metric.key_columns)
    all_cols = list(staged.columns)
    col_list = ", ".join(all_cols)
    conflict_cols = ", ".join(key_cols)
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in all_cols if c not in key_cols)

    conn.register("_staging_df", staged)
    try:
        conn.execute(
            f"""
            INSERT INTO {metric.table_name} ({col_list})
            SELECT {col_list} FROM _staging_df
            ON CONFLICT ({conflict_cols}) DO UPDATE SET {set_clause}
            """
        )
    finally:
        conn.unregister("_staging_df")


def fetch_metric_df(
    conn: duckdb.DuckDBPyConnection,
    metric: MetricDefinition,
    date_from: date | None = None,
    date_to: date | None = None,
) -> pd.DataFrame:
    query = f"SELECT * FROM {metric.table_name}"
    conditions = []
    params: list = []
    if date_from is not None:
        conditions.append(f"{metric.date_column} >= ?")
        params.append(date_from)
    if date_to is not None:
        conditions.append(f"{metric.date_column} <= ?")
        params.append(date_to)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    return conn.execute(query, params).fetch_df()
