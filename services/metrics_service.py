"""Cálculo de KPIs e séries agregadas a partir das métricas persistidas.

Mantido separado das páginas Streamlit de propósito: esta é a camada que,
no futuro, também alimentará o "Analista IA" (o contexto estruturado
enviado a um LLM viria destas mesmas funções).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from metrics.base import MetricDefinition
from repositories import metrics_repository
from services.database import get_connection


@dataclass
class KPI:
    label: str
    current: float
    previous: float

    @property
    def delta(self) -> float:
        return self.current - self.previous

    @property
    def delta_pct(self) -> float | None:
        if self.previous == 0:
            return None
        return (self.delta / self.previous) * 100


def load_daily_series(metric: MetricDefinition, filters: dict[str, str] | None = None) -> pd.DataFrame:
    """Retorna todo o histórico da métrica agregado por dia, colunas
    [date, value]. `filters` restringe a uma dimensão (ex.:
    {'cliente': '3dunique'}), usado pelo filtro de cliente da página de
    métrica quando `metric.ranking_dimensions` está definido. O cache
    do Streamlit fica na camada de página (st.cache_data), não aqui,
    para que uma nova importação invalide o cache corretamente."""
    conn = get_connection()
    df = metrics_repository.fetch_metric_df(conn, metric, filters=filters)
    if df.empty:
        return pd.DataFrame(columns=["date", "value"])
    daily = (
        df.groupby(metric.date_column)[metric.primary_value_column]
        .sum()
        .reset_index()
        .rename(columns={metric.date_column: "date", metric.primary_value_column: "value"})
        .sort_values("date")
    )
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    return daily


@st.cache_data(show_spinner=False)
def load_daily_series_cached(metric_key: str, dimension_value: str | None = None) -> pd.DataFrame:
    """Versão cacheada de load_daily_series, indexada pela chave da
    métrica e, opcionalmente, por um valor da primeira dimensão de
    `ranking_dimensions` (ex.: um cliente específico) — ambos strings,
    sempre hasheáveis. O cache é invalidado explicitamente por
    clear_cache() sempre que uma importação altera os dados — ver
    services/importer.py."""
    from metrics import METRICS

    metric = METRICS[metric_key]
    filters = None
    if dimension_value is not None and metric.ranking_dimensions:
        dim_col = next(iter(metric.ranking_dimensions))
        filters = {dim_col: dimension_value}
    return load_daily_series(metric, filters=filters)


def clear_cache() -> None:
    """Invalida os dados cacheados. Chamada após toda importação
    confirmada para que o dashboard nunca mostre dados desatualizados."""
    load_daily_series_cached.clear()


def total_all_time(daily_df: pd.DataFrame) -> float:
    """Soma de todo o histórico da métrica, sem filtro de período —
    usado no card de 'Total acumulado' da Visão Geral (diferente do
    KPI de período, que só soma os dias dentro do filtro selecionado)."""
    if daily_df.empty:
        return 0.0
    return float(daily_df["value"].sum())


def previous_period(start: date, end: date) -> tuple[date, date]:
    """Dado um período [start, end], retorna o período imediatamente
    anterior de mesma duração, para comparação."""
    span_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span_days - 1)
    return prev_start, prev_end


def period_kpi(
    daily_df: pd.DataFrame,
    current_start: date,
    current_end: date,
    previous_start: date,
    previous_end: date,
    label: str = "Total",
) -> KPI:
    def _sum_between(start: date, end: date) -> float:
        if daily_df.empty:
            return 0.0
        mask = (daily_df["date"] >= start) & (daily_df["date"] <= end)
        return float(daily_df.loc[mask, "value"].sum())

    return KPI(
        label=label,
        current=_sum_between(current_start, current_end),
        previous=_sum_between(previous_start, previous_end),
    )


def history_span(daily_frames: list[pd.DataFrame]) -> tuple[int, date, date] | None:
    """Dado os dataframes diários (colunas [date, value]) de uma ou mais
    métricas, retorna (dias cobertos, data mais antiga, data mais
    recente) considerando todo o histórico já importado. None se não
    houver nenhum dado ainda."""
    non_empty = [df for df in daily_frames if not df.empty]
    if not non_empty:
        return None
    earliest = min(df["date"].min() for df in non_empty)
    latest = max(df["date"].max() for df in non_empty)
    return (latest - earliest).days + 1, earliest, latest


def combined_daily(series_by_metric: dict[str, pd.DataFrame], metrics: list[MetricDefinition]) -> pd.DataFrame:
    """Combina as séries diárias de várias métricas em um único
    DataFrame largo (colunas: date, <chave_da_métrica>...), usado pelo
    gráfico de colunas agrupadas da Visão Geral (charts.grouped_columns)
    que compara as métricas lado a lado em vez de abas separadas."""
    combined: pd.DataFrame | None = None
    for metric in metrics:
        df = series_by_metric.get(metric.key)
        col = (
            df.rename(columns={"value": metric.key})[["date", metric.key]]
            if df is not None and not df.empty
            else pd.DataFrame(columns=["date", metric.key])
        )
        combined = col if combined is None else combined.merge(col, on="date", how="outer")
    if combined is None or combined.empty:
        return pd.DataFrame(columns=["date", *(m.key for m in metrics)])
    for metric in metrics:
        combined[metric.key] = combined[metric.key].fillna(0.0).astype(float)
    return combined.sort_values("date").reset_index(drop=True)


def combined_weekly(
    series_by_metric: dict[str, pd.DataFrame], metrics: list[MetricDefinition], n_weeks: int = 8
) -> pd.DataFrame:
    """Igual a combined_daily, mas agregado por semana (colunas:
    semana, <chave_da_métrica>...), reaproveitando weekly_comparison
    por métrica."""
    combined: pd.DataFrame | None = None
    for metric in metrics:
        df = series_by_metric.get(metric.key, pd.DataFrame(columns=["date", "value"]))
        weekly = weekly_comparison(df, n_weeks=n_weeks).rename(columns={"value": metric.key})
        combined = weekly if combined is None else combined.merge(weekly, on="semana", how="outer")
    if combined is None or combined.empty:
        return pd.DataFrame(columns=["semana", *(m.key for m in metrics)])
    for metric in metrics:
        combined[metric.key] = combined[metric.key].fillna(0.0).astype(float)
    return combined.sort_values("semana").reset_index(drop=True)


def weekly_comparison(daily_df: pd.DataFrame, n_weeks: int = 8) -> pd.DataFrame:
    """Agrega os valores por semana (iniciando na segunda-feira) para
    permitir comparação semana a semana."""
    if daily_df.empty:
        return pd.DataFrame(columns=["semana", "value"])
    df = daily_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["semana"] = df["date"].dt.to_period("W-SUN").apply(lambda p: p.start_time.date())
    weekly = df.groupby("semana", as_index=False)["value"].sum().sort_values("semana")
    return weekly.tail(n_weeks)


def top_dimension(
    metric: MetricDefinition,
    dimension_column: str,
    date_from: date | None = None,
    date_to: date | None = None,
    top_n: int | None = None,
) -> pd.DataFrame:
    """Ranking somando a métrica principal por uma dimensão (ex.:
    empresa, usuário). Só faz sentido para métricas que possuem essa
    coluna (ver MetricDefinition.ranking_dimensions). `top_n=None`
    (padrão) retorna todos os valores da dimensão, sem cortar — passe
    um número pra limitar a um top-N quando a dimensão tiver muitos
    valores distintos e só o topo interessar."""
    conn = get_connection()
    df = metrics_repository.fetch_metric_df(conn, metric, date_from, date_to)
    if df.empty or dimension_column not in df.columns:
        return pd.DataFrame(columns=[dimension_column, "value"])
    ranking = (
        df.groupby(dimension_column)[metric.primary_value_column]
        .sum()
        .reset_index()
        .rename(columns={metric.primary_value_column: "value"})
        .sort_values("value", ascending=False)
    )
    return ranking.head(top_n) if top_n is not None else ranking


def clicks_sent(channel_key: str, start: date, end: date) -> int | None:
    """Total de cliques importados no período, ou None se a métrica
    não medir cliques. Contagens de campanhas não são cliques."""
    from metrics import METRICS

    if channel_key not in METRICS or not METRICS[channel_key].measures_clicks:
        return None
    daily_df = load_daily_series_cached(channel_key)
    if daily_df.empty:
        return 0
    mask = (daily_df["date"] >= start) & (daily_df["date"] <= end)
    return int(daily_df.loc[mask, "value"].sum())


def traffic_visits(channel_key: str, start: date, end: date) -> int:
    """Visitas confirmadas pela Amazon (metric_amazon_traffic) pra um
    canal específico, no período."""
    from metrics import METRICS

    conn = get_connection()
    df = metrics_repository.fetch_metric_df(
        conn, METRICS["amazon_traffic"], date_from=start, date_to=end, filters={"channel": channel_key}
    )
    return int(df["visits"].sum()) if not df.empty else 0


def total_clicks_sent(start: date, end: date) -> int:
    """Cliques enviados pelos canais que medem cliques — usado no funil
    da jornada completa da Visão Geral, sem somar campanhas ou mensagens."""
    from metrics.amazon_common import CHANNEL_LABELS

    return sum(clicks_sent(channel_key, start, end) or 0 for channel_key in CHANNEL_LABELS)


def total_traffic_visits(start: date, end: date) -> int:
    """Visitas confirmadas pela Amazon somadas em todos os canais, no
    período — contraparte de `total_clicks_sent`."""
    from metrics import METRICS

    conn = get_connection()
    df = metrics_repository.fetch_metric_df(conn, METRICS["amazon_traffic"], date_from=start, date_to=end)
    return int(df["visits"].sum()) if not df.empty else 0


def funnel_stage_counts(start: date, end: date) -> tuple[list[str], list[int]]:
    """Conta, por etapa do funil de cadastro Amazon (ver
    metrics.amazon_common.FUNNEL_STAGE_COLUMNS), quantos vendedores com
    início de cadastro no período já chegaram até ali. Retorna duas
    listas vazias se não houver nenhum vendedor no período."""
    from metrics import METRICS
    from metrics.amazon_common import FUNNEL_STAGE_COLUMNS

    conn = get_connection()
    df = metrics_repository.fetch_metric_df(conn, METRICS["amazon_funnel"], date_from=start, date_to=end)
    if df.empty:
        return [], []

    labels = [label for _, label in FUNNEL_STAGE_COLUMNS]
    values = []
    for column, _ in FUNNEL_STAGE_COLUMNS:
        if column == "siv_approved_indicator":
            values.append(int((df[column] == 1).sum()))
        else:
            values.append(int(df[column].notna().sum()))
    return labels, values
