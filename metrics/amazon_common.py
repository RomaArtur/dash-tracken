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
