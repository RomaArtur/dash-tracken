"""Página de importação: upload -> validação -> normalização -> preview
-> confirmação. Nenhuma escrita no banco acontece antes do usuário
clicar em 'Importar dados'.

Métricas JSON (Login, Pop-up) seguem o fluxo original. Métricas CSV
(Disparos E-mail) precisam de dois metadados que não vêm do arquivo —
cliente e campanha — extraídos por convenção do nome do arquivo
(`email_<cliente>_<campanha>.csv`) e sempre editáveis antes do preview,
já que não há garantia de que o nome siga a convenção à risca."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from metrics import METRICS, detect_metric_from_filename
from repositories import metrics_repository
from services import importer
from services.database import get_connection

_NOVO_CLIENTE = "+ Novo cliente"


def _guess_cliente_campanha(filename: str) -> tuple[str, str]:
    """Extrai (cliente, campanha) do nome do arquivo pela convenção
    `email_<cliente>_<campanha>.csv`. Retorna strings vazias se o nome
    não tiver segmentos suficientes — os campos ficam em branco na tela
    para o usuário preencher na mão."""
    stem = Path(filename).stem
    parts = stem.split("_", 2)
    cliente = parts[1].strip() if len(parts) > 1 else ""
    campanha = parts[2].strip() if len(parts) > 2 else ""
    return cliente, campanha


def _render_csv_metadata_inputs(metric, filename: str) -> tuple[str, str] | None:
    """Renderiza os campos de Cliente/Campanha para métricas CSV.
    Retorna (cliente, campanha) só quando ambos estão preenchidos,
    None caso contrário (preview ainda não deve ser gerado)."""
    cliente_guess, campanha_guess = _guess_cliente_campanha(filename)

    existing_clientes = metrics_repository.distinct_values(get_connection(), metric.table_name, "cliente")

    col1, col2 = st.columns(2)
    with col1:
        options = existing_clientes + [_NOVO_CLIENTE]
        default_index = options.index(cliente_guess) if cliente_guess in existing_clientes else len(options) - 1
        selected = st.selectbox("Cliente", options, index=default_index)
        if selected == _NOVO_CLIENTE:
            cliente = st.text_input("Nome do novo cliente", value=cliente_guess)
        else:
            cliente = selected
    with col2:
        campanha = st.text_input("Campanha / ID", value=campanha_guess)

    if not cliente.strip() or not campanha.strip():
        st.info("Preencha cliente e campanha para gerar a prévia da importação.")
        return None
    return cliente.strip(), campanha.strip()


def render_import_page() -> None:
    st.title("Importar Dados")
    st.caption("Envie um arquivo JSON ou CSV de métricas para atualizar o histórico do dashboard.")

    metric_keys = list(METRICS.keys())
    metric_labels = [METRICS[k].label for k in metric_keys]

    uploaded_file = st.file_uploader("Selecione o arquivo", type=["json", "csv"])

    if uploaded_file is None:
        return

    default_index = 0
    detected = detect_metric_from_filename(uploaded_file.name)
    if detected in metric_keys:
        default_index = metric_keys.index(detected)

    selected_label = st.selectbox("Tipo de métrica", metric_labels, index=default_index)
    selected_key = metric_keys[metric_labels.index(selected_label)]
    metric = METRICS[selected_key]

    filename_lower = uploaded_file.name.lower()
    if not filename_lower.endswith(f".{metric.file_format}"):
        st.error(f"Selecione um arquivo .{metric.file_format} para a métrica '{metric.label}'.")
        return

    context: dict | None = None
    if metric.file_format == "csv":
        metadata = _render_csv_metadata_inputs(metric, uploaded_file.name)
        if metadata is None:
            return
        cliente, campanha = metadata
        context = {"cliente": cliente, "campaign_id": campanha}

    try:
        raw = importer.load_csv(uploaded_file.getvalue()) if metric.file_format == "csv" else importer.load_json(uploaded_file.getvalue())
        preview = importer.build_preview(metric, uploaded_file.name, raw, context=context)
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
