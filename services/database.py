"""Camada de acesso ao banco de dados analítico.

Esta é a ÚNICA parte da aplicação que sabe que o banco é DuckDB. Todo o
resto (repositórios, serviços, páginas) recebe uma conexão já aberta.
Se no futuro o DuckDB for substituído por PostgreSQL, a mudança fica
concentrada aqui e no SQL específico de cada repositório (o SQL usado
é, propositalmente, ANSI-padrão sempre que possível).
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import streamlit as st

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "analytics.duckdb"

logger = logging.getLogger(__name__)


@st.cache_resource(show_spinner=False)
def get_connection() -> duckdb.DuckDBPyConnection:
    """Retorna a conexão DuckDB compartilhada pela aplicação (cacheada
    pelo Streamlit para não reabrir o arquivo a cada rerun)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(DB_PATH))
    logger.info("Conexão DuckDB aberta em %s", DB_PATH)
    return conn


def init_schema() -> None:
    """Cria (se necessário) todas as tabelas usadas pela aplicação:
    o histórico de importações e a tabela de cada métrica registrada."""
    from metrics import METRICS
    from repositories.import_repository import DDL_STATEMENTS as IMPORT_DDL_STATEMENTS

    conn = get_connection()
    for statement in IMPORT_DDL_STATEMENTS:
        conn.execute(statement)
    for metric in METRICS.values():
        conn.execute(metric.ddl)
    logger.info("Schema verificado/criado para %d métrica(s)", len(METRICS))
