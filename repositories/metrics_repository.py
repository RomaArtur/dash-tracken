"""Acesso genérico às tabelas de métricas.

Todas as funções operam a partir de uma `MetricDefinition`, sem conhecer
particularidades de login/popup/futuras métricas — isso é o que
mantém a aplicação extensível sem precisar de um repositório por métrica.
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import psycopg

from metrics.base import MetricDefinition


def fetch_existing_keys(conn: psycopg.Connection, metric: MetricDefinition) -> pd.DataFrame:
    """Carrega chave natural + colunas de valor já persistidas, usadas
    para comparar com o arquivo importado e detectar novos/atualizados/
    inalterados."""
    cols = list(metric.key_columns) + list(metric.value_columns)
    col_list = ", ".join(cols)
    cur = conn.execute(f"SELECT {col_list} FROM {metric.table_name}")
    columns = [col.name for col in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=columns)


def upsert(
    conn: psycopg.Connection,
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
    placeholders = ", ".join(["%s"] * len(all_cols))
    conflict_cols = ", ".join(key_cols)
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in all_cols if c not in key_cols)

    rows = [tuple(row) for row in staged.itertuples(index=False, name=None)]
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {metric.table_name} ({col_list})
            VALUES ({placeholders})
            ON CONFLICT ({conflict_cols}) DO UPDATE SET {set_clause}
            """,
            rows,
        )


def distinct_values(conn: psycopg.Connection, table_name: str, column: str) -> list[str]:
    """Valores distintos já persistidos numa coluna de uma tabela de
    métrica — usado para sugerir opções já usadas (ex.: nomes de
    cliente) na tela de importação, evitando duplicar o mesmo cliente
    com grafias diferentes."""
    cur = conn.execute(f"SELECT DISTINCT {column} FROM {table_name} ORDER BY {column}")
    return [row[0] for row in cur.fetchall()]


def delete_by_import_run(conn: psycopg.Connection, metric: MetricDefinition, run_id: int) -> int:
    """Remove os registros que ainda apontam pra essa execução de
    importação (import_run_id) — usado ao excluir uma importação do
    histórico. Registros já sobrescritos por uma importação mais
    recente (mesma chave natural, import_run_id atualizado) não são
    afetados, só os que essa execução específica deixou como estão."""
    cur = conn.execute(f"DELETE FROM {metric.table_name} WHERE import_run_id = %s", (run_id,))
    return cur.rowcount


def fetch_metric_df(
    conn: psycopg.Connection,
    metric: MetricDefinition,
    date_from: date | None = None,
    date_to: date | None = None,
    filters: dict[str, str] | None = None,
) -> pd.DataFrame:
    """`filters` aplica igualdade simples (coluna = valor) — usado para
    restringir a uma dimensão (ex.: {'cliente': '3dunique'}) sem
    precisar de uma query dedicada por métrica."""
    query = f"SELECT * FROM {metric.table_name}"
    conditions = []
    params: list = []
    if date_from is not None:
        conditions.append(f"{metric.date_column} >= %s")
        params.append(date_from)
    if date_to is not None:
        conditions.append(f"{metric.date_column} <= %s")
        params.append(date_to)
    for column, value in (filters or {}).items():
        conditions.append(f"{column} = %s")
        params.append(value)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    cur = conn.execute(query, params)
    columns = [col.name for col in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=columns)
