"""Camada de acesso ao banco de dados analítico.

Esta é a ÚNICA parte da aplicação que sabe que o banco é PostgreSQL. Todo
o resto (repositórios, serviços, páginas) recebe uma conexão já aberta.
O SQL usado em cada repositório é, propositalmente, ANSI-padrão sempre
que possível.

A string de conexão vem de `st.secrets["DATABASE_URL"]` (arquivo local
`.streamlit/secrets.toml`, gitignored, ou as Secrets do app no Streamlit
Community Cloud) ou, como alternativa, da variável de ambiente
`DATABASE_URL` (usada pelo Docker/outros ambientes).
"""
from __future__ import annotations

import logging
import os

import psycopg
import streamlit as st

logger = logging.getLogger(__name__)


def _database_url() -> str:
    try:
        value = st.secrets.get("DATABASE_URL")
    except Exception:
        value = None
    if not value:
        value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError(
            "DATABASE_URL não configurada. Defina em .streamlit/secrets.toml "
            "(local, veja .streamlit/secrets.toml.example) ou nas Secrets do "
            "app no Streamlit Community Cloud."
        )
    return value


@st.cache_resource(show_spinner=False)
def get_connection() -> psycopg.Connection:
    """Retorna a conexão Postgres compartilhada pela aplicação (cacheada
    pelo Streamlit para não reabrir a cada rerun)."""
    conn = psycopg.connect(_database_url(), autocommit=True)
    logger.info("Conexão Postgres aberta")
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
