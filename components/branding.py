"""Marca do produto na sidebar. Usa st.logo() (posiciona nativamente
acima da navegação — a área "user content" da sidebar sempre renderiza
depois do menu, então uma marca via st.markdown ficaria embaixo).

O wordmark completo aparece com a sidebar expandida; `icon_image` (a
marca quadrada) é o que aparece quando ela está recolhida.

Troca de logo no modo escuro: CSS puro (@media prefers-color-scheme)
só enxerga a preferência do sistema operacional, não o toggle manual
de tema dentro do app (Settings > Tema) — então alguém com o SO em
claro mas o app manualmente em escuro veria a logo errada com CSS
puro. Por isso um pequeno script observa o `color-scheme` real que o
Streamlit aplica no elemento raiz (que reflete o toggle manual E o
"usar do sistema") e troca o src da imagem de acordo — é a única fonte
confiável, já que o Python não tem como saber o tema ativo no
navegador (nem via st.context.theme.type, que a própria documentação
do Streamlit marca como não confiável logo após o toggle)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
WORDMARK_PATH = _ASSETS_DIR / "logo-wordmark.png"
MARK_PATH = _ASSETS_DIR / "logo-mark.png"
DARK_WORDMARK_URL = "app/static/logo-wordmark-dark.png"

_THEME_WATCHER_JS = f"""
<script>
(function() {{
    if (window.__tkLogoThemeWatcher) return;
    window.__tkLogoThemeWatcher = true;
    var DARK_SRC = "{DARK_WORDMARK_URL}";
    var lightSrc = null;

    function apply() {{
        var img = window.parent.document.querySelector('[data-testid="stSidebarLogo"]')
            || document.querySelector('[data-testid="stSidebarLogo"]');
        var app = window.parent.document.querySelector('[data-testid="stApp"]')
            || document.querySelector('[data-testid="stApp"]');
        if (!img || !app) return;
        if (lightSrc === null && img.src.indexOf("logo-wordmark-dark") === -1) {{
            lightSrc = img.src;
        }}
        var scheme = getComputedStyle(app).colorScheme || "";
        var dark = scheme.indexOf("dark") !== -1;
        var want = dark ? DARK_SRC : lightSrc;
        if (want && img.src.indexOf(want) === -1) {{
            img.src = want;
        }}
        img.style.backgroundColor = dark ? "transparent" : "#ffffff";
        img.style.padding = dark ? "0.75rem 0" : "0.75rem 1rem";
    }}
    apply();
    setInterval(apply, 700);
}})();
</script>
"""


def render_sidebar_brand() -> None:
    if WORDMARK_PATH.exists():
        st.logo(
            str(WORDMARK_PATH),
            size="large",
            icon_image=str(MARK_PATH) if MARK_PATH.exists() else None,
        )
        st.iframe(src=_THEME_WATCHER_JS, height=1)
