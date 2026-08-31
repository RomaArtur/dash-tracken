"""Marca do produto na sidebar. Usa st.logo() (posiciona nativamente
acima da navegação — a área "user content" da sidebar sempre renderiza
depois do menu, então uma marca via st.markdown ficaria embaixo).

O wordmark completo aparece com a sidebar expandida; `icon_image` (a
marca quadrada) é o que aparece quando ela está recolhida. Ambos têm
elementos pretos (traço do pin, palavra "TRACK"), por isso o CSS
(.assets/styles.css, seletor stLogo) embrulha a logo num chip branco —
garante contraste em qualquer tema, claro ou escuro, sem precisar de
uma segunda versão de arquivo."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
WORDMARK_PATH = _ASSETS_DIR / "logo-wordmark.png"
MARK_PATH = _ASSETS_DIR / "logo-mark.png"


def render_sidebar_brand() -> None:
    if WORDMARK_PATH.exists():
        st.logo(
            str(WORDMARK_PATH),
            size="medium",
            icon_image=str(MARK_PATH) if MARK_PATH.exists() else None,
        )
