"""Definição genérica de uma métrica suportada pelo dashboard.

Cada métrica (login, popup, e futuras) implementa um `MetricDefinition`
descrevendo como seus dados brutos (JSON) são lidos, validados e
persistidos. O restante da aplicação (importação, repositórios, páginas)
depende apenas desta interface, nunca de detalhes específicos de uma
métrica em particular — isso é o que permite adicionar novas métricas
sem duplicar lógica.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import pandas as pd


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    """Identificador interno estável, ex.: 'login'. Usado como chave de
    registro, prefixo de nome de arquivo e valor salvo em import_runs."""

    label: str
    """Nome exibido na interface, ex.: 'Login'."""

    icon: str
    """Emoji usado na navegação e nos títulos das páginas."""

    table_name: str
    """Nome da tabela Postgres onde os registros normalizados são persistidos."""

    key_columns: Sequence[str]
    """Colunas que formam a chave natural de um registro (usadas no
    UPSERT e na detecção de duplicidade/idempotência)."""

    value_columns: Sequence[str]
    """Colunas de valor comparadas para decidir se um registro existente
    deve ser atualizado (valor mudou) ou ignorado (valor idêntico)."""

    primary_value_column: str
    """Coluna numérica principal usada nos KPIs e gráficos de evolução
    (ex.: 'total_logins', 'cliques')."""

    ddl: str
    """Instrução CREATE TABLE IF NOT EXISTS da tabela desta métrica."""

    parse: Callable[[dict], pd.DataFrame]
    """Converte o JSON bruto (já carregado com json.load) em um DataFrame
    'largo', uma linha por registro, sem validação ainda."""

    validate: Callable[[pd.DataFrame], "tuple[pd.DataFrame, pd.DataFrame]"]
    """Recebe o DataFrame de parse() e retorna (validos, invalidos)."""

    date_column: str = "date"
    """Coluna de data usada nos filtros de período do dashboard."""

    ranking_dimensions: Mapping[str, str] | None = None
    """Dimensões disponíveis para ranking/top-N, mapeando
    coluna -> rótulo (ex.: {'codemp': 'Empresa'}). None se a métrica não
    tiver dimensão além da data (caso do login)."""
