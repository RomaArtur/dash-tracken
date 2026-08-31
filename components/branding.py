"""Marca do produto na sidebar. Usa st.logo() (posiciona nativamente
acima da navegação — a área "user content" da sidebar sempre renderiza
depois do menu, então uma marca via st.markdown ficaria embaixo)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.svg"


def render_sidebar_brand() -> None:
    if LOGO_PATH.exists():
        st.logo(str(LOGO_PATH))
