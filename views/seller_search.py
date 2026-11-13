"""Página de busca de sellers com os contatos e tags já importados."""
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
    st.caption("Localize os contatos importados do WhatsApp por transportadora, tags e telefone, em todo o histórico.")
    try:
        contacts, without_details = search.load_contacts_cached()
    except Exception:
        logger.exception("Falha ao carregar contatos para busca de sellers")
        st.error("Não foi possível carregar os contatos. Verifique a conexão com o banco e tente novamente.")
        return

    if without_details:
        st.caption(f"{without_details} disparo(s) no formato de resumo não possuem detalhes de contatos para consulta.")
    if contacts.empty:
        st.info("Importe um CSV de contatos em Disparos WhatsApp para habilitar a busca de sellers.")
        return

    carriers, tags = search.filter_options(contacts)
    _discard_missing_options("seller_carriers", carriers)
    _discard_missing_options("seller_marketplaces", tags)
    with st.container(border=True):
        carrier_col, marketplace_col = st.columns(2)
        with carrier_col:
            selected_carriers = st.multiselect(
                "Transportadora", carriers, key="seller_carriers", placeholder="Todas as transportadoras",
            )
        with marketplace_col:
            selected_marketplaces = st.multiselect(
                "Marketplace (tag)", tags, key="seller_marketplaces", placeholder="Selecione a tag do marketplace",
                help="Selecione as tags que identificam o marketplace. Tags novas ficam disponíveis após a importação.",
            )
        seller_col, phone_col = st.columns(2)
        with seller_col:
            seller_query = st.text_input(
                "Seller / tag", key="seller_query", placeholder="Nome, ID ou texto presente nas tags",
            )
        with phone_col:
            phone_query = st.text_input("Telefone", key="seller_phone", placeholder="Número completo ou parte dele")
        st.button("Limpar filtros", on_click=_clear_filters, icon=":material/filter_alt_off:")

    if phone_query.strip() and not search.phone_digits(phone_query):
        st.warning("Digite os números do telefone. Espaços, parênteses, hífen e + são aceitos.")
    matches = search.filter_contacts(
        contacts, carriers=selected_carriers, marketplace_tags=selected_marketplaces,
        seller_query=seller_query, phone_query=phone_query,
    )
    if matches.empty:
        st.info("Nenhum contato encontrado com os filtros informados.")
        return

    results = search.summarize_contacts(matches)
    st.subheader("Contatos encontrados")
    st.caption(
        f"{len(results)} telefone(s) encontrado(s). Cada linha reúne os disparos que atendem aos filtros. "
        "O filtro Marketplace usa as tags selecionadas; a busca por seller consulta o texto das tags."
    )
    st.dataframe(
        results, width="stretch", hide_index=True,
        column_config={
            "Telefone": st.column_config.TextColumn(),
            "Tags": st.column_config.TextColumn(width="medium"),
            "Disparos encontrados": st.column_config.NumberColumn("Disparos", width="small"),
            "Último disparo": st.column_config.DateColumn(format="DD/MM/YYYY"),
        },
    )

    st.subheader("Histórico do contato")
    numbers = results["Telefone"].tolist()
    if st.session_state.get("seller_contact") not in numbers:
        st.session_state["seller_contact"] = None
    number = st.selectbox(
        "Telefone para consultar o histórico", numbers, index=None, key="seller_contact",
        placeholder="Selecione um contato encontrado",
    )
    if number is not None:
        st.caption("Todos os disparos importados deste telefone, incluindo outros períodos e transportadoras.")
        history = search.contact_history(contacts, number)
        labels = {column: CONTACT_LABELS[column] for column in ("date", "cliente", "campaign_id", "broadcast_status", "tags")}
        st.dataframe(
            history[list(labels)].rename(columns=labels), width="stretch", hide_index=True,
            column_config={"Data do disparo": st.column_config.DateColumn(format="DD/MM/YYYY")},
        )
