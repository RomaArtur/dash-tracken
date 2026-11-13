"""Normalização de telefones com DDI, sem completar dígitos ausentes."""
from __future__ import annotations

import math
import re
from numbers import Integral, Real

import pandas as pd


def normalize_phone(value) -> str | None:
    if pd.isna(value):
        return None
    if isinstance(value, Integral):
        text = str(int(value))
    elif isinstance(value, Real):
        if not math.isfinite(value) or not float(value).is_integer():
            return None
        text = str(int(value))
    else:
        text = str(value).strip()
        # Um inteiro exportado pelo Excel pode terminar com .0 no CSV.
        decimal = re.fullmatch(r"(\+?[0-9]{8,15})\.([0-9]+)", text)
        if decimal:
            if any(digit != "0" for digit in decimal[2]):
                return None
            text = decimal[1]
    text = re.sub(r"[\s().-]", "", text)
    if not re.fullmatch(r"\+?[1-9][0-9]{7,14}", text):
        return None
    return "+" + text.lstrip("+")
