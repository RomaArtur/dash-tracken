"""Página reservada para Disparos WhatsApp — ainda sem mecanismo de
importação nem tabela própria. Existe só para o item aparecer no menu
e sinalizar que a funcionalidade está a caminho."""
from __future__ import annotations

import streamlit as st


def render_whatsapp_placeholder() -> None:
    st.title("Disparos WhatsApp")
    st.info("Disparos WhatsApp ainda não está disponível — em breve.")
