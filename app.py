"""Ponto de entrada da aplicação.

A navegação combina páginas fixas (Visão Geral, Importar Dados,
Histórico) com páginas geradas dinamicamente a partir do registro de
métricas em `metrics.METRICS`. Adicionar uma nova métrica no futuro
(ex.: uma terceira funcionalidade rastreada) não exige tocar neste
arquivo nem duplicar páginas: basta registrar a nova MetricDefinition.
"""
from __future__ import annotations

import functools
from pathlib import Path

import streamlit as st

from components.branding import render_sidebar_brand
from metrics import METRICS
from services.database import init_schema
from utils.logging_config import setup_logging
from utils.styles import inject_css
from views.amazon_page import render_amazon_page
from views.import_history import render_import_history
from views.import_page import render_import_page
from views.metric_page import render_metric_page
from views.overview import render_overview

setup_logging()

_FAVICON = Path(__file__).resolve().parent / "assets" / "logo-mark.png"

st.set_page_config(
    page_title="Tracken Analytics",
    page_icon=str(_FAVICON) if _FAVICON.exists() else ":material/monitoring:",
    layout="wide",
)

init_schema()
inject_css()

with st.sidebar:
    render_sidebar_brand()

overview_page = st.Page(
    render_overview, title="Visão Geral", icon=":material/space_dashboard:", url_path="visao-geral", default=True
)
import_page = st.Page(
    render_import_page, title="Importar Dados", icon=":material/upload_file:", url_path="importar-dados"
)
history_page = st.Page(
    render_import_history, title="Histórico de Importações", icon=":material/history:", url_path="historico-importacoes"
)

metric_pages = [
    st.Page(
        functools.partial(render_metric_page, metric.key),
        title=metric.label,
        icon=metric.icon,
        url_path=f"metrica-{metric.key}",
    )
    for metric in METRICS.values()
    if metric.standalone_page
]
amazon_page = st.Page(
    render_amazon_page,
    title="Amazon",
    icon=":material/storefront:",
    url_path="amazon",
)
metric_pages.append(amazon_page)

navigation = st.navigation(
    {
        "Geral": [overview_page],
        "Métricas": metric_pages,
        "Dados": [import_page, history_page],
    }
)
navigation.run()
