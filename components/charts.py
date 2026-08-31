"""Gráficos Plotly usados no dashboard.

Paleta e specs seguem a metodologia de dataviz do projeto: verde da marca
como cor sequencial única (magnitude), roxo reservado para o segundo
elemento visual quando necessário, barras finas com pontas arredondadas,
linhas de 2px, grid discreto e hover sempre ativo.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

GREEN = "#28A828"
GREEN_DARK = "#1E8A1E"
GREEN_TINT = "rgba(40, 168, 40, 0.10)"
PURPLE = "#8848D8"
GRID_GRAY = "rgba(22, 24, 29, 0.07)"
MUTED_GRAY = "#C7C9CC"
INK = "#16181D"

_LAYOUT_DEFAULTS = dict(
    margin=dict(l=10, r=10, t=10, b=10),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, -apple-system, Segoe UI, sans-serif", size=13, color=INK),
    hovermode="x unified",
    height=320,
    showlegend=False,
)


def line_evolution(df: pd.DataFrame) -> go.Figure:
    """Série única (magnitude ao longo do tempo) — 1 hue, linha de 2px,
    marcador só no último ponto, área em wash (~10% opacidade)."""
    fig = go.Figure(
        go.Scatter(
            x=df["date"],
            y=df["value"],
            mode="lines",
            line=dict(color=GREEN, width=2.5, shape="spline", smoothing=0.3),
            fill="tozeroy",
            fillcolor=GREEN_TINT,
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
                marker=dict(size=8, color=GREEN, line=dict(width=2, color="#FFFFFF")),
                hoverinfo="skip",
            )
        )
    fig.update_layout(**_LAYOUT_DEFAULTS)
    fig.update_yaxes(gridcolor=GRID_GRAY, zeroline=False, tickfont=dict(color="#9A9EA6"))
    fig.update_xaxes(showgrid=False, tickfont=dict(color="#9A9EA6"))
    return fig


def weekly_bar(df: pd.DataFrame) -> go.Figure:
    """Comparação semanal usando o padrão de ênfase: a semana mais
    recente carrega a cor de destaque, as anteriores ficam em cinza
    neutro — a história é 'como estamos agora', não uma lista de séries."""
    if df.empty:
        return go.Figure()
    colors = [MUTED_GRAY] * (len(df) - 1) + [GREEN]
    fig = go.Figure(
        go.Bar(
            x=df["semana"],
            y=df["value"],
            marker=dict(color=colors, cornerradius=4),
            hovertemplate="Semana de %{x|%d/%m/%Y}<br><b>%{y:,.0f}</b><extra></extra>",
        )
    )
    fig.update_layout(**_LAYOUT_DEFAULTS, bargap=0.35)
    fig.update_yaxes(gridcolor=GRID_GRAY, zeroline=False, tickfont=dict(color="#9A9EA6"))
    fig.update_xaxes(showgrid=False, tickfont=dict(color="#9A9EA6"))
    return fig


def ranking_horizontal(df: pd.DataFrame, label_col: str, value_col: str = "value") -> go.Figure:
    """Ranking (magnitude, comparar categorias) — 1 hue sequencial,
    ordenado, sem necessidade de legenda (série única)."""
    ordered = df.sort_values(value_col, ascending=True)
    fig = go.Figure(
        go.Bar(
            x=ordered[value_col],
            y=ordered[label_col].astype(str),
            orientation="h",
            marker=dict(color=GREEN, cornerradius=4),
            hovertemplate="%{y}<br><b>%{x:,.0f}</b><extra></extra>",
        )
    )
    fig.update_layout(**_LAYOUT_DEFAULTS, bargap=0.35)
    fig.update_layout(height=max(220, 34 * len(ordered)))
    fig.update_xaxes(gridcolor=GRID_GRAY, zeroline=False, tickfont=dict(color="#9A9EA6"))
    fig.update_yaxes(showgrid=False, tickfont=dict(color=INK), type="category")
    return fig
