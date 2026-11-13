"""Consulta dos contatos de WhatsApp preservando as tags e seus vínculos por disparo."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

import pandas as pd
import streamlit as st

from metrics import METRICS
from metrics.whatsapp_contacts import contacts_from_campaigns
from repositories import metrics_repository
from services.database import get_connection


def _text(value) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _normalized(value) -> str:
    text = unicodedata.normalize("NFKD", _text(value).casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def phone_digits(value) -> str:
    return re.sub(r"[^0-9]", "", _text(value))


def tags_from_text(value) -> list[str]:
    return [tag.strip() for tag in _text(value).split("|") if tag.strip()]


def _unique(values) -> list[str]:
    found = {}
    for value in values:
        text = _text(value)
        if text:
            found.setdefault(_normalized(text), text)
    return sorted(found.values(), key=_normalized)


@st.cache_data(ttl=60, max_entries=1, show_spinner=False)
def load_contacts_cached() -> tuple[pd.DataFrame, int]:
    campaigns = metrics_repository.fetch_metric_df(get_connection(), METRICS["whatsapp"])
    contacts = contacts_from_campaigns(campaigns)
    detailed = campaigns.get("contacts_json", pd.Series(dtype="string")).fillna("").astype(str).str.strip().ne("")
    return contacts, int((~detailed).sum())


def filter_options(contacts: pd.DataFrame) -> tuple[list[str], list[str]]:
    if contacts.empty:
        return [], []
    return _unique(contacts["cliente"]), _unique(
        tag for value in contacts["tags"] for tag in tags_from_text(value)
    )


def filter_contacts(
    contacts: pd.DataFrame, *, carriers: Sequence[str] = (), marketplace_tags: Sequence[str] = (),
    seller_query: str = "", phone_query: str = "",
) -> pd.DataFrame:
    """Combina filtros na mesma ocorrência, antes de consolidar por telefone.

    As tags são livres: o usuário escolhe as que identificam o marketplace.
    Seleções no mesmo campo usam OU; campos diferentes usam E.
    """
    if contacts.empty:
        return contacts.copy()
    matches = pd.Series(True, index=contacts.index)
    if carriers:
        matches &= contacts["cliente"].map(_normalized).isin({_normalized(c) for c in carriers})
    if marketplace_tags:
        selected = {_normalized(t) for t in marketplace_tags}
        matches &= contacts["tags"].map(lambda value: bool(selected & {_normalized(t) for t in tags_from_text(value)}))
    if seller_query.strip():
        matches &= contacts["tags"].map(_normalized).str.contains(_normalized(seller_query), regex=False)
    if phone_query.strip():
        digits = phone_digits(phone_query)
        matches &= contacts["whatsapp_number"].map(phone_digits).str.contains(digits, regex=False) if digits else False
    return contacts.loc[matches].copy()


def summarize_contacts(contacts: pd.DataFrame) -> pd.DataFrame:
    columns = ["Telefone", "Transportadoras", "Tags", "Disparos encontrados", "Último disparo"]
    records = []
    for number, group in contacts.groupby("whatsapp_number", sort=True):
        records.append({
            "Telefone": number,
            "Transportadoras": " | ".join(_unique(group["cliente"])),
            "Tags": " | ".join(_unique(tag for value in group["tags"] for tag in tags_from_text(value))),
            "Disparos encontrados": len(group[["cliente", "campaign_id"]].drop_duplicates()),
            "Último disparo": pd.to_datetime(group["date"]).max().date(),
        })
    return pd.DataFrame(records, columns=columns).sort_values(
        ["Último disparo", "Telefone"], ascending=[False, True], ignore_index=True,
    )


def contact_history(contacts: pd.DataFrame, number: str) -> pd.DataFrame:
    history = contacts.loc[contacts["whatsapp_number"].eq(number)].copy()
    return history.sort_values(["date", "cliente", "campaign_id"], ascending=[False, True, True])
