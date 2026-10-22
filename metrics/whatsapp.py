"""Disparos de WhatsApp: contatos do CSV consolidados por campanha.

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
from metrics.whatsapp_contacts import (
    CONTACT_LABELS, contacts_from_campaigns, is_contacts_export, parse_contacts,
)
from repositories import metrics_repository
from services.database import get_connection

KEY = "whatsapp"
CSV_TEMPLATE = (
    "Tags,Whatsapp numbers,Broadcast Status\n"
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
    contacts_json TEXT,
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
    if is_contacts_export(raw):
        return parse_contacts(raw, context)
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
            "contacts_json": pd.Series(None, index=raw.index, dtype=object),
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


def render_import_context(raw: pd.DataFrame, filename: str) -> dict | None:
    if not is_contacts_export(raw):
        return {}
    st.info(
        "CSV de contatos WhatsApp identificado. Cada arquivo representa um disparo completo. "
        "As Tags definem a transportadora: Flexboys, flexboys_falha e flexboys_bkp pertencem a Flexboys."
    )
    st.caption(
        "Informe a campanha e a data do disparo. Created On é a data de cadastro do contato. "
        "Para atualizar os status, reimporte o CSV completo usando o mesmo ID da campanha. "
        "Para outro disparo, use um novo ID."
    )
    campaign_col, date_col = st.columns(2)
    with campaign_col:
        campaign = st.text_input("Campanha / ID", key=f"whatsapp_campaign_{filename}").strip()
    with date_col:
        dispatch_date = st.date_input("Data do disparo", value=None, key=f"whatsapp_date_{filename}", format="DD/MM/YYYY")
    if not campaign or dispatch_date is None:
        st.info("Preencha a campanha e a data do disparo para gerar a prévia da importação.")
        return None
    return {"campaign_id": campaign, "date": dispatch_date}


def render_import_preview(df: pd.DataFrame) -> None:
    contacts = contacts_from_campaigns(df)
    if contacts.empty:
        st.dataframe(df.drop(columns="contacts_json", errors="ignore").head(100), width="stretch", hide_index=True)
        return
    st.caption(
        f"{len(contacts):,} contatos em {len(df)} disparo(s) por transportadora. "
        "Os contadores da importação representam os resumos desses disparos. "
        "Os indicadores são calculados pelo Broadcast Status, sem usar segmentos das Tags como status."
    )
    st.dataframe(contacts[list(CONTACT_LABELS)].rename(columns=CONTACT_LABELS), width="stretch", hide_index=True)
    with st.expander("Indicadores calculados do CSV", icon=":material/analytics:"):
        st.dataframe(summarize_by_carrier(df), width="stretch", hide_index=True)


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

        contacts = contacts_from_campaigns(df)
        if not contacts.empty:
            with st.expander("Contatos dos disparos", icon=":material/contacts:"):
                st.dataframe(
                    contacts.sort_values(["date", "cliente", "whatsapp_number"], ascending=[False, True, True])
                    [list(CONTACT_LABELS)].rename(columns=CONTACT_LABELS),
                    width="stretch", hide_index=True,
                )
                if df["contacts_json"].isna().any():
                    st.caption("Disparos importados pelo resumo antigo não possuem detalhes de contatos.")

    with st.expander("Como importar os disparos de WhatsApp", icon=":material/upload_file:"):
        st.write(
            "Em Importar Dados, envie o CSV de contatos com as colunas Tags, Whatsapp numbers e Broadcast Status. "
            "Arquivos separados por vírgula ou ponto e vírgula são reconhecidos automaticamente. "
            "Informe a campanha / ID e a data do disparo na tela. O arquivo pode conter várias transportadoras. "
            "Os segmentos falha e bkp das Tags são agrupados pelo nome da transportadora."
        )
        st.write(
            "Broadcast Status aceita Sent (enviado), Delivered (entregue), Read (lido) e Failed (falha). "
            "Read também conta como entregue e enviado; Delivered também conta como enviado. "
            "As taxas usam o total de contatos como base. Reimportar o CSV completo com o mesmo ID atualiza "
            "o disparo existente. Para um novo disparo, use outro ID. "
            "O formato anterior de resumo por campanha continua aceito."
        )
        st.download_button(
            "Baixar modelo CSV", data=CSV_TEMPLATE, file_name="whatsapp_contatos.csv",
            mime="text/csv", key="whatsapp_csv_template", icon=":material/download:",
        )


DEFINITION = MetricDefinition(
    key=KEY,
    label="Disparos WhatsApp",
    icon=":material/chat:",
    table_name="metric_whatsapp_campaign",
    key_columns=("cliente", "campaign_id"),
    value_columns=("date", "disparos", "total_contatos", "enviados", "entregues", "abertos", "falhas", "contacts_json"),
    primary_value_column="disparos",
    ddl=DDL,
    parse=parse,
    validate=validate,
    ranking_dimensions={"cliente": "Transportadora"},
    accent="green",
    file_format="csv",
    csv_campaign_column="Campanha",
    csv_client_column="Transportadora",
    detect_csv=is_contacts_export,
    render_import_context=render_import_context,
    render_import_preview=render_import_preview,
    all_dimensions_label="Todas as transportadoras",
    schema_updates=(
        "ALTER TABLE metric_whatsapp_campaign ADD COLUMN IF NOT EXISTS falhas INTEGER",
        "ALTER TABLE metric_whatsapp_campaign ADD COLUMN IF NOT EXISTS contacts_json TEXT",
    ),
    render_summary=render_summary,
    show_trend_charts=False,
    show_in_combined_charts=False,
)
