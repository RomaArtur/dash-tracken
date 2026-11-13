"""Página de busca usando as colunas explícitas do cadastro de sellers."""
from __future__ import annotations

import logging

import streamlit as st

from metrics.whatsapp_contacts import CONTACT_LABELS
from services import seller_search as search

logger = logging.getLogger(__name__)
_FILTER_KEYS = ("seller_carriers", "seller_marketplaces", "seller_query", "seller_phone", "seller_contact")


def _clear_filters() -> None:
    for key in _FILTER_KEYS:
        st.session_state.pop(key, None)


def _discard_missing_options(key: str, options: list[str]) -> None:
    selected = st.session_state.get(key, [])
    remaining = [value for value in selected if value in options]
    if selected != remaining:
        st.session_state[key] = remaining


def render_seller_search() -> None:
    st.title("Buscar sellers")
    st.caption("Consulte a base importada pelas colunas Telefone, Marketplace, Transportadora e Nome do seller.")
    try:
        contacts = search.load_sellers_cached()
    except Exception:
        logger.exception("Falha ao carregar cadastro de sellers")
        st.error("Não foi possível carregar o cadastro de sellers. Verifique a conexão com o banco e tente novamente.")
        return

    if contacts.empty:
        st.info("Em Importar Dados, selecione Cadastro de sellers e envie um CSV ou Excel com os dados dos sellers.")
        return

    carriers, marketplaces = search.filter_options(contacts)
    _discard_missing_options("seller_carriers", carriers)
    _discard_missing_options("seller_marketplaces", marketplaces)
    with st.container(border=True):
        carrier_col, marketplace_col = st.columns(2)
        with carrier_col:
            selected_carriers = st.multiselect(
                "Transportadora", carriers, key="seller_carriers", placeholder="Todas as transportadoras",
            )
        with marketplace_col:
            selected_marketplaces = st.multiselect(
                "Marketplace", marketplaces, key="seller_marketplaces", placeholder="Todos os marketplaces",
            )
        seller_col, phone_col = st.columns(2)
        with seller_col:
            seller_query = st.text_input(
                "Nome do seller", key="seller_query", placeholder="Nome completo ou parte dele",
            )
        with phone_col:
            phone_query = st.text_input("Telefone", key="seller_phone", placeholder="Número completo ou parte dele")
        st.button("Limpar filtros", on_click=_clear_filters, icon=":material/filter_alt_off:")

    if phone_query.strip() and not search.phone_digits(phone_query):
        st.warning("Digite os números do telefone. Espaços, parênteses, hífen e + são aceitos.")
    matches = search.filter_contacts(
        contacts, carriers=selected_carriers, marketplaces=selected_marketplaces,
        seller_query=seller_query, phone_query=phone_query,
    )
    if matches.empty:
        st.info("Nenhum contato encontrado com os filtros informados.")
        return

    results = search.summarize_contacts(matches)
    st.subheader("Sellers encontrados")
    st.caption(
        f"{len(results)} vínculo(s), com {results['Telefone'].nunique()} telefone(s) único(s). "
        "Cada linha preserva a associação entre seller, transportadora e marketplace do arquivo."
    )
    st.dataframe(
        results, width="stretch", hide_index=True,
        column_config={
            "Telefone": st.column_config.TextColumn(),
            "Nome do seller": st.column_config.TextColumn(width="large"),
        },
    )

    st.subheader("Histórico de disparos do telefone")
    numbers = results["Telefone"].drop_duplicates().tolist()
    if st.session_state.get("seller_contact") not in numbers:
        st.session_state["seller_contact"] = None
    number = st.selectbox(
        "Telefone para consultar o histórico", numbers, index=None, key="seller_contact",
        placeholder="Selecione um contato encontrado",
    )
    if number is not None:
        try:
            campaigns, without_details = search.load_contacts_cached()
        except Exception:
            logger.exception("Falha ao carregar histórico de WhatsApp")
            st.warning("Não foi possível carregar o histórico de WhatsApp deste telefone.")
            return
        if without_details:
            st.caption(f"{without_details} disparo(s) importado(s) como resumo não possuem detalhes de contatos.")
        st.caption("Disparos associados a este telefone. Um número pode estar vinculado a mais de um seller.")
        history = search.contact_history(campaigns, number)
        if history.empty:
            st.info("Nenhum disparo de WhatsApp encontrado para este telefone.")
            return
        labels = {column: CONTACT_LABELS[column] for column in ("date", "cliente", "campaign_id", "broadcast_status", "tags")}
        st.dataframe(
            history[list(labels)].rename(columns=labels), width="stretch", hide_index=True,
            column_config={"Data do disparo": st.column_config.DateColumn(format="DD/MM/YYYY")},
        )
