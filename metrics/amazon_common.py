"""Mapeamento compartilhado entre as métricas Amazon (traffic e funnel)
e a página que as combina (views/amazon_page.py).

A Amazon identifica os canais do Tracken por um `source_detail` interno
dela (`log - tracken`, `pop - tracken`, `wa - tracken`) — este módulo
traduz isso para as mesmas chaves usadas pelas métricas de disparo
(`login`, `popup`, e o futuro `whatsapp`), permitindo comparar cliques
enviados com visitas confirmadas pela Amazon sem duplicar o mapeamento
em cada métrica."""
from __future__ import annotations

CHANNEL_BY_SOURCE_DETAIL: dict[str, str] = {
    "log - tracken": "login",
    "pop - tracken": "popup",
    "wa - tracken": "whatsapp",
}

CHANNEL_LABELS: dict[str, str] = {
    "login": "Login",
    "popup": "Pop-up",
    "whatsapp": "WhatsApp",
}

FUNNEL_STAGE_COLUMNS: list[tuple[str, str]] = [
    ("registration_start_date", "Reg Start"),
    ("registration_complete_date", "Reg Complete"),
    ("siv_approved_indicator", "Verificado (RV)"),
    ("kyctrigger_date", "KYC"),
    ("rtl_date", "Ready to Launch"),
    ("launch_date", "Launch"),
    ("fba_launch_date", "FBA Launch"),
]
"""Colunas de metric_amazon_funnel (ver metrics/amazon_funnel.py) na
ordem da jornada de cadastro, com o rótulo exibido em cada etapa do
funil. 'Verificado (RV)' é a exceção: conta linhas com valor == 1, as
demais contam quantas linhas têm a data daquela etapa preenchida."""
