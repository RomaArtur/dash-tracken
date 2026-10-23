"""Conversões derivadas do tráfego e do progresso dos cadastros Amazon."""
from __future__ import annotations

import pandas as pd

from metrics.amazon_common import FUNNEL_STAGE_COLUMNS


CONVERSIONS = (
    ("traffic_rs", "Tráfego → Reg Start", "visits", "registration_start_date"),
    ("rs_rc", "Reg Start → Reg Complete", "registration_start_date", "registration_complete_date"),
    ("rc_rv", "Reg Complete → RV", "registration_complete_date", "siv_approved_indicator"),
    ("rv_rtl", "RV → RTL", "siv_approved_indicator", "rtl_date"),
    ("rtl_launch", "RTL → Launch", "rtl_date", "launch_date"),
    ("rs_rtl", "Reg Start → RTL", "registration_start_date", "rtl_date"),
    ("rs_launch", "Reg Start → Launch", "registration_start_date", "launch_date"),
    ("fba", "FBA Eligible → FBA Launch", "fba_eligible", "fba_launch_date"),
)


def stage_counts(funnel: pd.DataFrame) -> dict[str, int]:
    counts = {column: 0 for column, _ in FUNNEL_STAGE_COLUMNS}
    counts["fba_eligible"] = 0
    if funnel.empty:
        return counts
    for column, _ in FUNNEL_STAGE_COLUMNS:
        counts[column] = int(
            funnel[column].eq(1).sum() if column == "siv_approved_indicator"
            else funnel[column].notna().sum()
        )
    counts["fba_eligible"] = int(funnel["is_fba_eligible"].astype("string").str.strip().str.upper().eq("Y").sum())
    return counts


def funnel_counts(funnel: pd.DataFrame) -> tuple[list[str], list[int]]:
    if funnel.empty:
        return [], []
    counts = stage_counts(funnel)
    return [label for _, label in FUNNEL_STAGE_COLUMNS], [counts[column] for column, _ in FUNNEL_STAGE_COLUMNS]


def conversion_rates(funnel: pd.DataFrame, traffic: pd.DataFrame) -> pd.DataFrame:
    """Usa a mesma coorte do funil: cadastros iniciados no período.

    O avanço é o que consta no último arquivo importado. Tráfego vem
    das visitas no mesmo período; ausência de base não vira taxa zero.
    """
    counts = stage_counts(funnel)
    counts["visits"] = int(traffic["visits"].sum()) if not traffic.empty else None
    records = []
    for key, label, origin, destination in CONVERSIONS:
        base, converted = counts[origin], counts[destination]
        records.append({
            "key": key, "label": label, "base": base, "converted": converted,
            "rate": converted / base * 100 if base else None,
        })
    return pd.DataFrame(records)
