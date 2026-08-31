"""Página de importação: upload -> validação -> normalização -> preview
-> confirmação. Nenhuma escrita no banco acontece antes do usuário
clicar em 'Importar dados'."""
from __future__ import annotations

import streamlit as st

from metrics import METRICS, detect_metric_from_filename
from services import importer


def render_import_page() -> None:
    st.title("Importar Dados")
    st.caption("Envie um arquivo JSON de métricas para atualizar o histórico do dashboard.")

    metric_keys = list(METRICS.keys())
    metric_labels = [METRICS[k].label for k in metric_keys]

    uploaded_file = st.file_uploader("Selecione o arquivo JSON", type=["json"])

    if uploaded_file is None:
        return

    default_index = 0
    detected = detect_metric_from_filename(uploaded_file.name)
    if detected in metric_keys:
        default_index = metric_keys.index(detected)

    selected_label = st.selectbox("Tipo de métrica", metric_labels, index=default_index)
    selected_key = metric_keys[metric_labels.index(selected_label)]
    metric = METRICS[selected_key]

    try:
        raw = importer.load_json(uploaded_file.getvalue())
        preview = importer.build_preview(metric, uploaded_file.name, raw)
    except importer.ImportValidationError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # proteção genérica contra erros inesperados de leitura
        st.error(f"Erro inesperado ao processar o arquivo: {exc}")
        return

    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        with st.container(key="tk-accent-navy-0"):
            st.metric("Registros encontrados", preview.total_parsed, icon=":material/description:", border=True)
    with col2:
        with st.container(key="tk-accent-green-1"):
            st.metric("Registros novos", preview.n_new, icon=":material/add_circle:", border=True)
    with col3:
        with st.container(key="tk-accent-navy-2"):
            st.metric("Registros existentes", preview.n_existing, icon=":material/check_circle:", border=True)
    with col4:
        invalid_key = "tk-accent-negative-3" if preview.n_invalid else "tk-accent-navy-3"
        with st.container(key=invalid_key):
            st.metric("Registros inválidos", preview.n_invalid, icon=":material/error:", border=True)

    with st.expander("Detalhes da importação", icon=":material/info:"):
        st.write(f"Serão inseridos: **{preview.n_new}**")
        st.write(f"Serão atualizados (valor mudou): **{preview.n_updated}**")
        st.write(f"Sem alteração (ignorados): **{preview.n_unchanged}**")
        if preview.n_invalid:
            st.write(f"Inválidos (não serão importados): **{preview.n_invalid}**")
            st.dataframe(preview.invalid_df, width="stretch", hide_index=True)

    st.subheader("Prévia dos dados")
    st.dataframe(preview.valid_df.head(100), width="stretch", hide_index=True)

    nothing_to_do = preview.n_new == 0 and preview.n_updated == 0
    if nothing_to_do:
        st.info("Nenhum registro novo ou alterado neste arquivo — nada a importar.")

    if st.button("Importar dados", type="primary", icon=":material/database_upload:", disabled=nothing_to_do):
        try:
            run_id = importer.commit_import(preview)
        except Exception as exc:
            st.error(f"Falha ao salvar a importação: {exc}")
        else:
            st.success(
                f"Importação concluída (execução #{run_id}): "
                f"{preview.n_new} novo(s), {preview.n_updated} atualizado(s), "
                f"{preview.n_unchanged} ignorado(s)."
            )
            st.balloons()
