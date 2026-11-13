"""Consulta do cadastro de sellers e do histórico de disparos de cada telefone."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

import pandas as pd
import streamlit as st

from metrics import METRICS
from metrics.sellers import LABELS
from metrics.whatsapp_contacts import contacts_from_campaigns
from repositories import metrics_repository
from services.database import get_connection
from utils.phones import normalize_phone


def _text(value) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _normalized(value) -> str:
    text = unicodedata.normalize("NFKD", _text(value).casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def phone_digits(value) -> str:
    return re.sub(r"[^0-9]", "", _text(value))


def marketplaces_from_text(value) -> list[str]:
    return [tag.strip() for tag in _text(value).split("|") if tag.strip()]


def _unique(values) -> list[str]:
    found = {}
    for value in values:
        text = _text(value)
        if text:
            found.setdefault(_normalized(text), text)
    return sorted(found.values(), key=_normalized)


@st.cache_data(ttl=60, max_entries=1, show_spinner=False)
def load_sellers_cached() -> pd.DataFrame:
    return metrics_repository.fetch_metric_df(get_connection(), METRICS["sellers"])


@st.cache_data(ttl=60, max_entries=1, show_spinner=False)
def load_contacts_cached() -> tuple[pd.DataFrame, int]:
    campaigns = metrics_repository.fetch_metric_df(get_connection(), METRICS["whatsapp"])
    contacts = contacts_from_campaigns(campaigns)
    detailed = campaigns.get("contacts_json", pd.Series(dtype="string")).fillna("").astype(str).str.strip().ne("")
    return contacts, int((~detailed).sum())


def filter_options(contacts: pd.DataFrame) -> tuple[list[str], list[str]]:
    if contacts.empty:
        return [], []
    return _unique(contacts["carrier"]), _unique(
        marketplace for value in contacts["marketplace"] for marketplace in marketplaces_from_text(value)
    )


def filter_contacts(
    contacts: pd.DataFrame, *, carriers: Sequence[str] = (), marketplaces: Sequence[str] = (),
    seller_query: str = "", phone_query: str = "",
) -> pd.DataFrame:
    """Combina os filtros no mesmo vínculo entre telefone, seller e transportadora.

    Seleções no mesmo campo usam OU; campos diferentes usam E.
    """
    if contacts.empty:
        return contacts.copy()
    matches = pd.Series(True, index=contacts.index)
    if carriers:
        matches &= contacts["carrier"].map(_normalized).isin({_normalized(c) for c in carriers})
    if marketplaces:
        selected = {_normalized(t) for t in marketplaces}
        matches &= contacts["marketplace"].map(lambda value: bool(selected & {_normalized(t) for t in marketplaces_from_text(value)}))
    if seller_query.strip():
        matches &= contacts["seller_name"].map(_normalized).str.contains(_normalized(seller_query), regex=False)
    if phone_query.strip():
        digits = phone_digits(phone_query)
        matches &= contacts["phone"].map(phone_digits).str.contains(digits, regex=False) if digits else False
    return contacts.loc[matches].copy()


def summarize_contacts(contacts: pd.DataFrame) -> pd.DataFrame:
    return contacts[list(LABELS)].drop_duplicates().rename(columns=LABELS).sort_values(
        ["Nome do seller", "Transportadora", "Marketplace", "Telefone"], ignore_index=True,
    )


def contact_history(contacts: pd.DataFrame, number: str) -> pd.DataFrame:
    canonical = normalize_phone(number)
    if canonical is None:
        return contacts.iloc[:0].copy()
    history = contacts.loc[contacts["whatsapp_number"].map(normalize_phone).eq(canonical)].copy()
    return history.sort_values(["date", "cliente", "campaign_id"], ascending=[False, True, True])
