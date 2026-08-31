"""Helper para os poucos lugares que precisam do NOME de um ícone
Material Symbols (ex.: HTML customizado do hero card via `.tk-icon`).

Em todo o resto da aplicação, o token completo (':material/nome:') é
passado direto para os parâmetros `icon=` nativos do Streamlit
(st.Page, st.metric, st.page_link, st.expander, st.button...), que já
entendem esse formato sem nenhum helper.
"""
from __future__ import annotations

_PREFIX = ":material/"
_SUFFIX = ":"


def material_name(token: str) -> str:
    """Extrai 'database' de ':material/database:'. Retorna o valor como
    veio se não estiver nesse formato (ex.: já é só o nome)."""
    name = token.strip()
    if name.startswith(_PREFIX) and name.endswith(_SUFFIX):
        return name[len(_PREFIX):-len(_SUFFIX)]
    return name
