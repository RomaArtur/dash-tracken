"""Cadastro de vínculos entre telefone, marketplace, transportadora e seller."""
from __future__ import annotations

import re
import unicodedata

import pandas as pd
import streamlit as st

from metrics.base import MetricDefinition
from utils.phones import normalize_phone

KEY = "sellers"
LABELS = {"phone": "Telefone", "marketplace": "Marketplace", "carrier": "Transportadora", "seller_name": "Nome do seller"}
_HEADERS = {"telefone": "phone", "marketplace": "marketplace", "transportadora": "carrier", "nomedoseller": "seller_name"}
KEY_COLUMNS = tuple(LABELS)

DDL = """
CREATE TABLE IF NOT EXISTS seller_directory (
    phone VARCHAR NOT NULL,
    marketplace VARCHAR NOT NULL,
    carrier VARCHAR NOT NULL,
    seller_name VARCHAR NOT NULL,
    registros INTEGER NOT NULL CHECK (registros = 1),
    import_run_id BIGINT,
    updated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (phone, marketplace, carrier, seller_name)
)
"""


def _headers(raw: pd.DataFrame) -> dict[str, str]:
    return {re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(c).lower())): c for c in raw.columns}


def is_seller_directory(raw: pd.DataFrame) -> bool:
    return set(_HEADERS).issubset(_headers(raw))


def parse(raw: pd.DataFrame, context: dict | None = None) -> pd.DataFrame:
    headers = _headers(raw)
    missing = [LABELS[target] for source, target in _HEADERS.items() if source not in headers]
    if missing:
        raise ValueError(f"Colunas ausentes no cadastro de sellers: {', '.join(missing)}")
    raw = raw.dropna(how="all")
    return raw[[headers[key] for key in _HEADERS]].rename(columns={headers[k]: v for k, v in _HEADERS.items()}).copy()


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = df.copy()
    phones = frame["phone"].map(normalize_phone)
    invalid = frame.loc[phones.isna()].copy()
    invalid["_motivo"] = "Telefone ausente ou inválido; informe o número com DDI. O valor 0 indica ausência de telefone."
    valid = frame.loc[phones.notna()].copy()
    valid["phone"] = phones.loc[phones.notna()]
    for column in ("marketplace", "carrier", "seller_name"):
        valid[column] = valid[column].astype("string").fillna("").str.strip().replace("", "Não informado")
    valid["registros"] = 1
    return valid.drop_duplicates(list(KEY_COLUMNS)).reset_index(drop=True), invalid


def render_import_context(raw: pd.DataFrame, filename: str) -> dict:
    st.info(
        "Cadastro de sellers: use as colunas Telefone, Marketplace, Transportadora e Nome do seller. "
        "O mesmo telefone pode ter vários vínculos. Cada associação será preservada."
    )
    st.caption("Telefones são tratados como texto com DDI. Não é necessário informar campanha, data ou status de disparo.")
    return {"seller_directory": True}


def render_import_preview(df: pd.DataFrame) -> None:
    st.caption(f"{len(df)} vínculo(s) entre sellers e transportadoras, com {df['phone'].nunique()} telefone(s) único(s).")
    st.dataframe(df[list(LABELS)].rename(columns=LABELS).head(100), width="stretch", hide_index=True)


DEFINITION = MetricDefinition(
    key=KEY, label="Cadastro de sellers", icon=":material/contacts:", table_name="seller_directory",
    key_columns=KEY_COLUMNS, value_columns=("registros",), primary_value_column="registros",
    ddl=DDL, parse=parse, validate=validate, date_column="updated_at",
    file_format="csv", additional_file_formats=("xlsx",), xlsx_sheet="Vínculos por seller", select_xlsx_sheet=True,
    detect_csv=is_seller_directory, render_import_context=render_import_context, render_import_preview=render_import_preview,
    standalone_page=False, show_in_overview=False, show_in_combined_charts=False,
)
