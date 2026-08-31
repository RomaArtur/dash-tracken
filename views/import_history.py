"""Histórico de importações: uma linha por arquivo importado, com as
contagens e o status de cada execução."""
from __future__ import annotations

import streamlit as st

from metrics import METRICS
from repositories import import_repository
from services.database import get_connection


def render_import_history() -> None:
    st.title("🕘 Histórico de Importações")

    conn = get_connection()
    runs = import_repository.list_runs(conn)

    if runs.empty:
        st.info("Nenhuma importação realizada ainda.")
        return

    runs = runs.copy()
    runs["metrica"] = runs["metric_type"].map(lambda k: METRICS[k].label if k in METRICS else k)
    runs["error_message"] = runs["error_message"].fillna("—")

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
    st.dataframe(
        runs[list(display_cols.keys())].rename(columns=display_cols),
        width="stretch",
        hide_index=True,
    )
