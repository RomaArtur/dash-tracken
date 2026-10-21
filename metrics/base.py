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
from datetime import date
from typing import Any, Callable, Literal, Mapping, Sequence

import pandas as pd


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    """Identificador interno estável, ex.: 'login'. Usado como chave de
    registro, prefixo de nome de arquivo e valor salvo em import_runs."""

    label: str
    """Nome exibido na interface, ex.: 'Login'."""

    icon: str
    """Token de ícone Material Symbols no formato ':material/nome:',
    aceito nativamente por st.Page, st.metric, st.page_link etc."""

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

    parse: Callable[[Any, dict], pd.DataFrame]
    """Converte o conteúdo bruto do arquivo (dict, se JSON; DataFrame, se
    CSV) em um DataFrame 'largo', uma linha por registro, sem validação
    ainda. `context` carrega metadados que não vêm do arquivo em si
    (ex.: cliente/campanha extraídos do nome do arquivo pela tela de
    importação) — métricas JSON simplesmente ignoram esse parâmetro."""

    validate: Callable[[pd.DataFrame], "tuple[pd.DataFrame, pd.DataFrame]"]
    """Recebe o DataFrame de parse() e retorna (validos, invalidos)."""

    date_column: str = "date"
    """Coluna de data usada nos filtros de período do dashboard."""

    ranking_dimensions: Mapping[str, str] | None = None
    """Dimensões disponíveis para ranking/top-N, mapeando
    coluna -> rótulo (ex.: {'codemp': 'Empresa'}). None se a métrica não
    tiver dimensão além da data (caso do login)."""

    accent: Literal["green", "purple", "navy", "blue", "amber"] = "green"
    """Papel semântico de cor da métrica em toda a UI (nav, cards de
    KPI, gráficos). Cada métrica deve usar um valor distinto para
    permanecer distinguível quando comparada a outras no mesmo gráfico
    (ver components/charts.py: line_multi, grouped_columns)."""

    file_format: Literal["json", "csv", "xlsx"] = "json"
    """Formato de arquivo aceito na tela de importação. Métricas 'csv'
    e 'xlsx' recebem um pandas.DataFrame já lido (não um dict) em
    `parse`, e normalmente dependem de metadados que não vêm do
    arquivo (ver `parse` e `context` acima). Métricas 'xlsx' também
    precisam de `xlsx_sheet`."""

    xlsx_sheet: str | None = None
    """Nome da aba a ler quando `file_format == 'xlsx'` — o arquivo
    pode ter várias abas (ex.: o relatório semanal da Amazon vem com
    'traffic' e 'funnel' no mesmo arquivo, cada uma virando uma
    métrica registrada separadamente)."""

    csv_campaign_column: str | None = None
    """Coluna opcional com o ID da campanha em cada linha do CSV. Quando
    presente no arquivo, substitui o campo de campanha da importação."""

    measures_clicks: bool = False
    """Indica que o valor principal mede cliques enviados à Amazon.
    Campanhas e mensagens enviadas não devem ser contadas como cliques."""

    standalone_page: bool = True
    """Se False, `app.py` não gera uma página de detalhe própria pra
    essa métrica — ela só é renderizada dentro de uma página
    customizada que combina várias métricas (ex.: `views/amazon_page.py`
    combinando `amazon_traffic` e `amazon_funnel` numa única seção
    'Amazon', em vez de duas páginas separadas no menu)."""

    show_in_overview: bool = True
    """Se False, `views/overview.py` ignora essa métrica por completo
    (nem cards de Total acumulado, nem gráficos combinados) — usado
    quando a métrica tem granularidade ou propósito incompatível com a
    Visão Geral (ex.: métricas Amazon, que não são 'contagem de
    eventos por dia')."""

    show_in_combined_charts: bool = True
    """Se False, `views/overview.py` exclui essa métrica do gráfico
    diário/semanal comparado e da rosca de proporção do total
    acumulado — usado quando a escala da métrica é incompatível com as
    demais (ex.: Disparos E-mail, com volume muito maior que Login/
    Pop-up) e misturá-las tornaria os gráficos ilegíveis. A métrica
    continua aparecendo nos cards de Total acumulado e no KPI do
    período, só fica fora dos dois gráficos combinados."""

    show_trend_charts: bool = True
    """Se False, `views/metric_page.py` não renderiza os blocos de
    'Evolução' e 'Comparação semanal' — usado por métricas cujo resumo
    próprio (ver `render_summary`) já cobre o que essas seções
    mostrariam, tornando-as redundantes (ex.: Disparos E-mail)."""

    render_summary: Callable[[str | None, date, date], None] | None = None
    """Hook de UI opcional: se definido, `views/metric_page.py` chama
    essa função (recebendo o valor selecionado no filtro da primeira
    `ranking_dimensions`, ou None se 'Todos', e o período selecionado)
    no lugar do KPI padrão — usado quando uma métrica precisa de um
    resumo visual próprio (ver metrics/email.py) em vez do card
    genérico de total do período. Mantém a UI específica dentro do
    módulo da métrica, sem `if metric.key == ...` na página genérica."""
