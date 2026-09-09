"""Histórico de importações: uma linha por arquivo importado, com as
contagens e o status de cada execução. Selecionar uma linha permite
excluí-la (com confirmação) — remove tanto o registro do histórico
quanto os dados que aquela execução inseriu (ver services/importer.py
delete_import)."""
from __future__ import annotations

import streamlit as st

from metrics import METRICS
from repositories import import_repository
from services import importer
from services.database import get_connection


def render_import_history() -> None:
    st.title("Histórico de Importações")

    deleted_message = st.session_state.pop("_import_deleted_message", None)
    if deleted_message:
        st.success(deleted_message)

    conn = get_connection()
    runs = import_repository.list_runs(conn)

    if runs.empty:
        st.info("Nenhuma importação realizada ainda.", icon=":material/inbox:")
        return

    runs = runs.copy()
    runs["metrica"] = runs["metric_type"].map(lambda k: METRICS[k].label if k in METRICS else k)
    runs["error_message"] = runs["error_message"].fillna("—")

    metric_options = ["Todas"] + sorted(runs["metrica"].unique())
    selected_metric = st.selectbox("Filtrar por métrica", metric_options)
    if selected_metric != "Todas":
        runs = runs[runs["metrica"] == selected_metric]

    display_cols = {
        "imported_at": "Data/Hora",
        "filename": "Arquivo",
        "metrica": "Métrica",
        "records_received": "Recebidos",
        "records_inserted": "Inseridos",
        "records_updated": "Atualizados",
        "records_ignored": "Ignorados",
        "records_invalid": "Inválidos",
        "status": "Status",
        "error_message": "Mensagem",
    }
    st.caption(
        f"{len(runs)} execuç{'ão' if len(runs) == 1 else 'ões'} — role dentro da tabela para ver todas. "
        "Selecione uma linha para excluir aquela importação."
    )
    event = st.dataframe(
        runs[list(display_cols.keys())].rename(columns=display_cols),
        width="stretch",
        height=460,
        hide_index=True,
        column_config={
            "Data/Hora": st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm"),
        },
        on_select="rerun",
        selection_mode="single-row",
        key="import_history_table",
    )

    selected_rows = event.selection.rows if event and event.selection else []
    if not selected_rows:
        return

    selected_run_id = int(runs.iloc[selected_rows[0]]["id"])
    selected = runs.iloc[selected_rows[0]]
    with st.container(border=True):
        st.write(
            f"Selecionado: **{selected['filename']}** ({selected['metrica']}, "
            f"{selected['records_inserted']} inserido(s), {selected['records_updated']} atualizado(s))"
        )
        st.warning(
            "Excluir remove esta execução do histórico e todos os registros que ela inseriu e "
            "ainda não foram sobrescritos por uma importação mais recente. Essa ação não pode ser desfeita.",
            icon=":material/warning:",
        )
        confirm = st.checkbox("Tenho certeza que quero excluir essa importação", key="confirm_delete_import")
        if st.button(
            "Excluir importação", type="primary", icon=":material/delete:", disabled=not confirm
        ):
            # A seleção do st.dataframe é por ÍNDICE de linha, não pelo id
            # da execução: se não limpar o índice selecionado e o checkbox
            # de confirmação ANTES do rerun, a linha que passa a ocupar o
            # mesmo índice após a exclusão (a lista encolheu) apareceria
            # pré-selecionada e já confirmada, arriscando excluir a
            # importação errada em seguida.
            deleted_count = importer.delete_import(selected_run_id)
            st.session_state.pop("import_history_table", None)
            st.session_state.pop("confirm_delete_import", None)
            st.session_state["_import_deleted_message"] = (
                f"Importação excluída — {deleted_count} registro(s) removido(s)."
            )
            st.rerun()
