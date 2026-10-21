"""Disparos de WhatsApp: um resumo por campanha, importado de CSV.

Transportadora e campanha podem vir do CSV ou dos metadados da importação.
O campo interno cliente armazena a transportadora, preservando os dados
anteriores. Reimportar atualiza o resumo existente por transportadora.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from metrics.base import MetricDefinition
from repositories import metrics_repository
from services.database import get_connection

KEY = "whatsapp"
CSV_TEMPLATE = (
    "Transportadora;Campanha;Data de envio;Total de contatos;Enviados;Entregues;Abertos;Mensagens com falha\n"
).encode("utf-8-sig")
_COUNT_COLUMNS = {
    "total_contatos": "Total de contatos",
    "enviados": "Enviados",
    "entregues": "Entregues",
    "abertos": "Abertos",
}

DDL = """
CREATE TABLE IF NOT EXISTS metric_whatsapp_campaign (
    cliente VARCHAR NOT NULL,
    campaign_id VARCHAR NOT NULL,
    date DATE NOT NULL,
    disparos INTEGER NOT NULL CHECK (disparos = 1),
    total_contatos INTEGER NOT NULL,
    enviados INTEGER NOT NULL,
    entregues INTEGER NOT NULL,
    abertos INTEGER NOT NULL,
    falhas INTEGER,
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (cliente, campaign_id),
    CHECK (0 <= abertos AND abertos <= entregues
           AND entregues <= enviados AND enviados <= total_contatos),
    CHECK (falhas IS NULL OR (falhas >= 0 AND falhas <= total_contatos - entregues))
)
"""


def parse(raw: pd.DataFrame, context: dict | None = None) -> pd.DataFrame:
    if not isinstance(raw, pd.DataFrame):
        raise ValueError("Os disparos de WhatsApp devem ser importados de uma tabela CSV.")
    context = context or {}
    cliente = str(context.get("cliente") or "").strip()
    if "Transportadora" not in raw.columns and not cliente:
        raise ValueError("Transportadora é obrigatória: informe na importação ou inclua a coluna 'Transportadora' no CSV.")

    required = {"Data de envio", *_COUNT_COLUMNS.values()}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Colunas ausentes no CSV: {', '.join(sorted(missing))}")
    campaign_id = str(context.get("campaign_id") or "").strip()
    if "Campanha" not in raw.columns and not campaign_id:
        raise ValueError("Informe a campanha ou inclua a coluna 'Campanha' no CSV.")

    return pd.DataFrame(
        {
            "cliente": raw["Transportadora"] if "Transportadora" in raw.columns else cliente,
            "campaign_id": raw["Campanha"] if "Campanha" in raw.columns else campaign_id,
            "date": raw["Data de envio"],
            "disparos": 1,
            **{column: raw[source] for column, source in _COUNT_COLUMNS.items()},
            "falhas": raw.get("Mensagens com falha", pd.Series(None, index=raw.index, dtype=object)),
        }
    )


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty:
        return df, df
    df = df.copy()
    motivo = pd.Series("", index=df.index)

    for column, label in (("cliente", "transportadora"), ("campaign_id", "campanha")):
        normalized = df[column].astype("string").str.strip()
        bad = normalized.isna() | normalized.eq("")
        motivo = motivo.where(~bad, motivo + f"{label} ausente; ")
        df[column] = normalized

    dates = df["date"].astype("string").str.strip()
    parsed_date = pd.to_datetime(dates, format="%Y-%m-%d", errors="coerce")
    parsed_date = parsed_date.fillna(
        pd.to_datetime(dates, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    )
    motivo = motivo.where(parsed_date.notna(), motivo + "data de envio inválida; ")

    numeric = {}
    for column, label in _COUNT_COLUMNS.items():
        values = pd.to_numeric(df[column], errors="coerce")
        bad = (
            values.isna()
            | ~values.between(0, 2_147_483_647)
            | values.ne(values.round())
        ).fillna(True)
        motivo = motivo.where(~bad, motivo + f"{label} deve ser um inteiro não negativo; ")
        numeric[column] = values

    failures = pd.to_numeric(df["falhas"], errors="coerce")
    bad_failures = df["falhas"].notna() & (
        failures.isna() | ~failures.between(0, 2_147_483_647) | failures.ne(failures.round())
    ).fillna(True)
    motivo = motivo.where(~bad_failures, motivo + "Mensagens com falha deve ser um inteiro não negativo; ")
    bad_failure_total = (failures > numeric["total_contatos"] - numeric["entregues"]).fillna(False)
    motivo = motivo.where(~bad_failure_total, motivo + "entregues e falhas excedem o total de contatos; ")

    for lower, upper, reason in (
        ("enviados", "total_contatos", "enviados maior que o total de contatos; "),
        ("entregues", "enviados", "entregues maior que enviados; "),
        ("abertos", "entregues", "abertos maior que entregues; "),
    ):
        bad = (numeric[lower] > numeric[upper]).fillna(False)
        motivo = motivo.where(~bad, motivo + reason)

    duplicate = df.duplicated(["cliente", "campaign_id"], keep=False)
    motivo = motivo.where(~duplicate, motivo + "campanha repetida no arquivo; use uma linha por disparo; ")
    invalid_mask = motivo.ne("")
    valid = df.loc[~invalid_mask].copy()
    invalid = df.loc[invalid_mask].copy()
    invalid["_motivo"] = motivo.loc[invalid_mask]
    valid["date"] = parsed_date.loc[~invalid_mask].dt.date
    for column, values in numeric.items():
        valid[column] = values.loc[~invalid_mask].astype(int)
    valid["falhas"] = pd.Series(
        [int(value) if pd.notna(value) else None for value in failures.loc[~invalid_mask]],
        index=valid.index, dtype=object,
    )
    return valid, invalid


@dataclass(frozen=True)
class WhatsAppSummary:
    disparos: int = 0
    contatos: int = 0
    taxa_entrega: float = 0.0
    taxa_abertura: float = 0.0
    falhas: int | None = 0
    taxa_falha: float | None = 0.0


def summarize(df: pd.DataFrame) -> WhatsAppSummary:
    """Taxas calculadas sobre o total de contatos do público-alvo.

    Os contatos são somados por campanha; a mesma pessoa pode fazer
    parte de campanhas diferentes e ser contada em cada público-alvo.
    """
    if df.empty:
        return WhatsAppSummary()
    contatos = int(df["total_contatos"].sum())
    entregues = int(df["entregues"].sum())
    abertos = int(df["abertos"].sum())
    failure_counts = df.get("falhas")
    falhas = (
        int(failure_counts.sum())
        if failure_counts is not None and failure_counts.notna().all()
        else None
    )
    return WhatsAppSummary(
        disparos=int(df["disparos"].sum()),
        contatos=contatos,
        taxa_entrega=entregues / contatos * 100 if contatos else 0.0,
        taxa_abertura=abertos / contatos * 100 if contatos else 0.0,
        falhas=falhas,
        taxa_falha=None if falhas is None else (falhas / contatos * 100 if contatos else 0.0),
    )


def _percentage(value: float | None) -> str:
    return f"{value:.0f}%" if value is not None else "—"


def summarize_by_carrier(df: pd.DataFrame) -> pd.DataFrame:
    """Apresenta os mesmos indicadores consolidados para cada transportadora."""
    records = []
    for carrier, campaigns in df.groupby("cliente", sort=True):
        summary = summarize(campaigns)
        records.append({
            "Transportadora": carrier,
            "Disparos": summary.disparos,
            "Total de contatos": summary.contatos,
            "Taxa média de entrega": _percentage(summary.taxa_entrega),
            "Taxa média de abertura": _percentage(summary.taxa_abertura),
            "Mensagens com falha": summary.falhas,
            "Taxa de falhas": _percentage(summary.taxa_falha),
        })
    return pd.DataFrame(records)


def render_summary(cliente: str | None, start: date, end: date) -> None:
    filters = {"cliente": cliente} if cliente else None
    df = metrics_repository.fetch_metric_df(
        get_connection(), DEFINITION, date_from=start, date_to=end, filters=filters
    )
    summary = summarize(df)
    specs = [
        ("Total de Disparos em Massa", f"{summary.disparos:,}".replace(",", "."),
         ":material/cell_tower:", "green", "Quantidade de campanhas/disparos por transportadora no período selecionado.", None),
        ("Total de contatos", f"{summary.contatos:,}".replace(",", "."),
         ":material/groups:", "blue", "Soma dos públicos-alvo das campanhas. Contatos presentes em mais de uma campanha são contados em cada uma.", None),
        ("Taxa média de entrega", _percentage(summary.taxa_entrega),
         ":material/done_all:", "green", "Total de entregues ÷ total de contatos no período.", summary.taxa_entrega),
        ("Taxa média de abertura", _percentage(summary.taxa_abertura),
         ":material/visibility:", "blue", "Total de abertos ÷ total de contatos no período.", summary.taxa_abertura),
        ("Mensagens com falha", f"{summary.falhas:,}".replace(",", ".") if summary.falhas is not None else "—",
         ":material/error:", "negative", "Falhas informadas no CSV. O percentual usa o total de contatos como base.", None),
    ]
    for index, (col, spec) in enumerate(zip(st.columns(len(specs)), specs)):
        label, value, icon, accent, help_text, progress = spec
        with col:
            with st.container(key=f"tk-accent-{accent}-whatsapp-{index}", border=True):
                st.metric(label, value, icon=icon, help=help_text)
                if progress is not None:
                    st.progress(progress / 100)
                if label == "Mensagens com falha":
                    if summary.taxa_falha is None:
                        st.caption("Falhas não informadas em todos os disparos.")
                    else:
                        caption = f"{_percentage(summary.taxa_falha)} deste público falhou"
                        st.caption(f":red[:material/warning: {caption}]" if summary.falhas else caption)

    if df.empty:
        st.info("Sem disparos de WhatsApp para o período e transportadora selecionados.")
    else:
        if cliente is None:
            with st.expander("Resumo por transportadora", icon=":material/local_shipping:"):
                st.dataframe(summarize_by_carrier(df), width="stretch", hide_index=True)
        with st.expander("Disparos no período", icon=":material/list_alt:"):
            labels = {
                "date": "Data de envio", "cliente": "Transportadora", "campaign_id": "Campanha",
                "total_contatos": "Contatos", "enviados": "Enviados", "entregues": "Entregues", "abertos": "Abertos",
                "falhas": "Mensagens com falha",
            }
            st.dataframe(
                df.sort_values("date", ascending=False)[list(labels)].rename(columns=labels),
                width="stretch", hide_index=True,
            )

    with st.expander("Como importar os disparos de WhatsApp", icon=":material/upload_file:"):
        st.write(
            "Em Importar Dados, escolha Disparos WhatsApp e envie um CSV separado por ponto e vírgula, "
            "com uma linha por campanha/disparo de cada transportadora. "
            "O mesmo arquivo pode conter todas as transportadoras. "
            "O nome whatsapp_<transportadora>_<campanha>.csv sugere os campos que não estiverem no CSV."
        )
        st.write(
            "Use as colunas Transportadora, Campanha, Data de envio, Total de contatos, Enviados, Entregues, Abertos e Mensagens com falha. "
            "A data deve estar em AAAA-MM-DD, opcionalmente com HH:MM:SS. "
            "Se o arquivo tiver uma única transportadora ou campanha, esses dados podem ser informados na importação. "
            "Para um novo disparo da mesma campanha, use um ID diferente. "
            "As taxas usam o total de contatos como base. CSVs antigos sem Mensagens com falha continuam aceitos; "
            "reimporte-os com essa coluna para completar o indicador de falhas."
        )
        st.download_button(
            "Baixar modelo CSV", data=CSV_TEMPLATE, file_name="whatsapp_transportadoras_campanhas.csv",
            mime="text/csv", key="whatsapp_csv_template", icon=":material/download:",
        )


DEFINITION = MetricDefinition(
    key=KEY,
    label="Disparos WhatsApp",
    icon=":material/chat:",
    table_name="metric_whatsapp_campaign",
    key_columns=("cliente", "campaign_id"),
    value_columns=("date", "disparos", "total_contatos", "enviados", "entregues", "abertos", "falhas"),
    primary_value_column="disparos",
    ddl=DDL,
    parse=parse,
    validate=validate,
    ranking_dimensions={"cliente": "Transportadora"},
    accent="green",
    file_format="csv",
    csv_campaign_column="Campanha",
    csv_client_column="Transportadora",
    all_dimensions_label="Todas as transportadoras",
    schema_updates=("ALTER TABLE metric_whatsapp_campaign ADD COLUMN IF NOT EXISTS falhas INTEGER",),
    render_summary=render_summary,
    show_trend_charts=False,
    show_in_combined_charts=False,
)
