"""Gráficos Plotly usados no dashboard.

A cor de cada série vem do acento semântico da métrica
(metrics.base.MetricDefinition.accent — verde=Login, roxo=Pop-up), não
de uma paleta fixa por posição. Isso é o que permite comparar métricas
no mesmo gráfico (ver `line_multi`, `grouped_columns`) sem perder o
significado da cor.

Cores neutras (fundo do gráfico, grade, texto dos eixos) não são
fixadas aqui de propósito: ficam a cargo do tema injetado por
`st.plotly_chart(fig, theme="streamlit")` nas views, para os gráficos
acompanharem automaticamente o modo claro/escuro escolhido pelo
usuário. Fixar essas cores aqui (como antes) deixaria os gráficos
ilegíveis no modo escuro.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from metrics.base import MetricDefinition
from utils.tokens import MUTED, accent_color

_LAYOUT_DEFAULTS = dict(
    margin=dict(l=10, r=10, t=10, b=10),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    hovermode="x unified",
    showlegend=False,
)

_LEGEND = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)


def _tint(hex_color: str, alpha: float = 0.12) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {alpha})"


def _week_range_label(monday) -> str:
    """'05/07–11/07' a partir da segunda-feira que representa a semana
    (ver services.metrics_service.weekly_comparison). Sem isso, o eixo
    mostraria só a segunda-feira, parecendo um único dia em vez da
    semana inteira que a barra soma."""
    start = pd.to_datetime(monday)
    end = start + pd.Timedelta(days=6)
    return f"{start.strftime('%d/%m')}–{end.strftime('%d/%m')}"


def line_evolution(df: pd.DataFrame, accent: str = "green") -> go.Figure:
    """Série única (magnitude ao longo do tempo) — 1 hue (o acento da
    métrica), linha de 2px, marcador só no último ponto, área em wash."""
    color = accent_color(accent)
    fig = go.Figure(
        go.Scatter(
            x=df["date"],
            y=df["value"],
            mode="lines",
            line=dict(color=color, width=2.5, shape="spline", smoothing=0.3),
            fill="tozeroy",
            fillcolor=_tint(color),
            hovertemplate="%{x|%d/%m/%Y}<br><b>%{y:,.0f}</b><extra></extra>",
        )
    )
    if not df.empty:
        last = df.iloc[-1]
        fig.add_trace(
            go.Scatter(
                x=[last["date"]],
                y=[last["value"]],
                mode="markers",
                marker=dict(size=8, color=color, line=dict(width=2, color="#FFFFFF")),
                hoverinfo="skip",
            )
        )
    fig.update_layout(**_LAYOUT_DEFAULTS)
    fig.update_yaxes(zeroline=False)
    fig.update_xaxes(showgrid=False)
    return fig


def line_multi(series_by_metric: dict[str, pd.DataFrame], metrics: list[MetricDefinition]) -> go.Figure:
    """Uma linha por métrica, cada uma com a cor do seu acento, e
    legenda — permite comparar as métricas no mesmo gráfico em vez de
    abas separadas (ver views/overview.py)."""
    fig = go.Figure()
    for metric in metrics:
        df = series_by_metric.get(metric.key)
        if df is None or df.empty:
            continue
        color = accent_color(metric.accent)
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["value"],
                mode="lines",
                name=metric.label,
                line=dict(color=color, width=2.5, shape="spline", smoothing=0.3),
                hovertemplate="%{x|%d/%m/%Y}<br><b>%{y:,.0f}</b><extra>" + metric.label + "</extra>",
            )
        )
    fig.update_layout(**{**_LAYOUT_DEFAULTS, "showlegend": True}, legend=_LEGEND)
    fig.update_yaxes(zeroline=False)
    fig.update_xaxes(showgrid=False)
    return fig


def grouped_columns(df: pd.DataFrame, metrics: list[MetricDefinition], x_col: str = "date") -> go.Figure:
    """Colunas agrupadas comparando as métricas lado a lado no mesmo
    período (diário ou semanal, conforme o df recebido) — o gráfico
    principal da Visão Geral, no estilo do dashboard de referência."""
    is_weekly = x_col == "semana"
    x_values = df[x_col].apply(_week_range_label) if is_weekly else df[x_col]
    hover_x = "%{x}" if is_weekly else "%{x|%d/%m/%Y}"
    hover_prefix = "Semana de " if is_weekly else ""

    fig = go.Figure()
    for metric in metrics:
        if metric.key not in df.columns:
            continue
        color = accent_color(metric.accent)
        fig.add_trace(
            go.Bar(
                x=x_values,
                y=df[metric.key],
                name=metric.label,
                marker=dict(color=color, cornerradius=4),
                hovertemplate=f"{hover_prefix}{hover_x}<br><b>%{{y:,.0f}}</b><extra>{metric.label}</extra>",
            )
        )
    fig.update_layout(
        **{**_LAYOUT_DEFAULTS, "showlegend": True, "hovermode": "closest"},
        legend=_LEGEND,
        barmode="group",
        bargap=0.25,
        bargroupgap=0.08,
    )
    fig.update_yaxes(zeroline=False)
    fig.update_xaxes(showgrid=False, type="category" if is_weekly else None)
    return fig


def weekly_bar(df: pd.DataFrame, accent: str = "green") -> go.Figure:
    """Comparação semanal usando o padrão de ênfase: a semana mais
    recente carrega a cor do acento da métrica, as anteriores ficam em
    cinza neutro — a história é 'como estamos agora', não uma lista de
    séries."""
    if df.empty:
        return go.Figure()
    color = accent_color(accent)
    colors = [MUTED] * (len(df) - 1) + [color]
    fig = go.Figure(
        go.Bar(
            x=df["semana"].apply(_week_range_label),
            y=df["value"],
            marker=dict(color=colors, cornerradius=4),
            hovertemplate="Semana de %{x}<br><b>%{y:,.0f}</b><extra></extra>",
        )
    )
    fig.update_layout(**_LAYOUT_DEFAULTS, bargap=0.35)
    fig.update_yaxes(zeroline=False)
    fig.update_xaxes(showgrid=False, type="category")
    return fig


def donut_breakdown(labels: list[str], values: list[float], colors: list[str]) -> go.Figure:
    """Rosca (donut) genérica com a soma das fatias em destaque no
    centro — usado tanto para comparar métricas entre si (ver
    `proportion_pie`) quanto para uma quebra dentro de uma única
    métrica (ex.: abertos vs não abertos em metrics/email.py)."""
    combined = sum(values)
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.55,
            marker=dict(colors=colors, line=dict(color="rgba(0,0,0,0)", width=0)),
            textinfo="label+percent",
            hovertemplate="%{label}<br><b>%{value:,.0f}</b> (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        **{**_LAYOUT_DEFAULTS, "showlegend": True},
        legend=_LEGEND,
        annotations=[
            dict(
                text=f"<b>{combined:,.0f}</b>".replace(",", "."),
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=20),
            )
        ],
    )
    return fig


def proportion_pie(totals: dict[str, float], metrics: list[MetricDefinition]) -> go.Figure:
    """Rosca (donut) com a proporção de cada métrica sobre um total —
    cor por acento, igual aos outros gráficos, com o total combinado
    em destaque no centro."""
    labels = [m.label for m in metrics if totals.get(m.key, 0) > 0]
    values = [totals[m.key] for m in metrics if totals.get(m.key, 0) > 0]
    colors = [accent_color(m.accent) for m in metrics if totals.get(m.key, 0) > 0]
    return donut_breakdown(labels, values, colors)


def ranking_horizontal(
    df: pd.DataFrame, label_col: str, value_col: str = "value", accent: str = "green"
) -> go.Figure:
    """Ranking (magnitude, comparar categorias) — 1 hue (o acento da
    métrica), ordenado, sem necessidade de legenda (série única)."""
    color = accent_color(accent)
    ordered = df.sort_values(value_col, ascending=True)
    fig = go.Figure(
        go.Bar(
            x=ordered[value_col],
            y=ordered[label_col].astype(str),
            orientation="h",
            marker=dict(color=color, cornerradius=4),
            hovertemplate="%{y}<br><b>%{x:,.0f}</b><extra></extra>",
        )
    )
    fig.update_layout(**_LAYOUT_DEFAULTS, bargap=0.35, height=max(220, 34 * len(ordered)))
    fig.update_xaxes(zeroline=False)
    fig.update_yaxes(showgrid=False, type="category")
    return fig
