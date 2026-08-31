"""Persistência do histórico de importações (tabela import_runs).

Cada linha representa uma execução de importação de um arquivo, com as
contagens exigidas para auditoria (recebidos/inseridos/atualizados/
ignorados/inválidos) e o status final.
"""
from __future__ import annotations

from datetime import datetime

import duckdb
import pandas as pd

DDL_STATEMENTS = [
    "CREATE SEQUENCE IF NOT EXISTS seq_import_runs START 1",
    """
    CREATE TABLE IF NOT EXISTS import_runs (
        id BIGINT PRIMARY KEY DEFAULT nextval('seq_import_runs'),
        metric_type VARCHAR NOT NULL,
        filename VARCHAR NOT NULL,
        imported_at TIMESTAMP NOT NULL,
        records_received INTEGER NOT NULL,
        records_inserted INTEGER NOT NULL,
        records_updated INTEGER NOT NULL,
        records_ignored INTEGER NOT NULL,
        records_invalid INTEGER NOT NULL,
        status VARCHAR NOT NULL,
        error_message VARCHAR
    )
    """,
]


def create_run(
    conn: duckdb.DuckDBPyConnection,
    *,
    metric_type: str,
    filename: str,
    records_received: int,
    records_inserted: int,
    records_updated: int,
    records_ignored: int,
    records_invalid: int,
    status: str,
    error_message: str | None = None,
) -> int:
    result = conn.execute(
        """
        INSERT INTO import_runs (
            metric_type, filename, imported_at, records_received, records_inserted,
            records_updated, records_ignored, records_invalid, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        [
            metric_type,
            filename,
            datetime.now(),
            records_received,
            records_inserted,
            records_updated,
            records_ignored,
            records_invalid,
            status,
            error_message,
        ],
    ).fetchone()
    return int(result[0])


def list_runs(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return conn.execute("SELECT * FROM import_runs ORDER BY imported_at DESC").fetch_df()
