"""Registro central das métricas suportadas pelo dashboard.

Para adicionar uma nova métrica no futuro:
  1. Criar um novo módulo em `metrics/` (ex.: metrics/nova_metrica.py)
     seguindo o padrão de `metrics/login.py` ou `metrics/popup.py`
     (funções `parse` e `validate` + uma `MetricDefinition`).
  2. Registrar a `MetricDefinition` no dicionário `METRICS` abaixo.

Nenhum outro módulo da aplicação (importação, persistência, páginas do
dashboard) precisa ser alterado: importação, histórico, KPIs e navegação
são todos genéricos e operam sobre `MetricDefinition`.
"""
from __future__ import annotations

from metrics.amazon_funnel import DEFINITION as AMAZON_FUNNEL_DEFINITION
from metrics.amazon_traffic import DEFINITION as AMAZON_TRAFFIC_DEFINITION
from metrics.base import MetricDefinition
from metrics.email import DEFINITION as EMAIL_DEFINITION
from metrics.login import DEFINITION as LOGIN_DEFINITION
from metrics.popup import DEFINITION as POPUP_DEFINITION

METRICS: dict[str, MetricDefinition] = {
    LOGIN_DEFINITION.key: LOGIN_DEFINITION,
    POPUP_DEFINITION.key: POPUP_DEFINITION,
    EMAIL_DEFINITION.key: EMAIL_DEFINITION,
    AMAZON_TRAFFIC_DEFINITION.key: AMAZON_TRAFFIC_DEFINITION,
    AMAZON_FUNNEL_DEFINITION.key: AMAZON_FUNNEL_DEFINITION,
}


def detect_metric_from_filename(filename: str) -> str | None:
    """Tenta adivinhar a métrica a partir do prefixo do nome do arquivo
    (ex.: 'login-19-08_26-08.json' -> 'login'). Usado apenas como sugestão
    inicial no seletor da tela de importação; o usuário sempre confirma.
    """
    name = filename.lower()
    for key in METRICS:
        if name.startswith(key):
            return key
    return None
