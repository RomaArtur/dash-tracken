"""Normalização do CSV de contatos e consolidação por transportadora/disparo."""
from __future__ import annotations

from datetime import date
import json
import re

import pandas as pd


CONTACT_COLUMNS = ["cliente", "campaign_id", "date", "tags", "whatsapp_number", "broadcast_status"]
SUMMARY_COLUMNS = [
    "cliente", "campaign_id", "date", "disparos", "total_contatos",
    "enviados", "entregues", "abertos", "falhas", "contacts_json",
]
CONTACT_LABELS = {
    "tags": "Tags", "whatsapp_number": "Whatsapp numbers", "broadcast_status": "Broadcast Status",
    "cliente": "Transportadora", "campaign_id": "Campanha", "date": "Data do disparo",
}
STATUSES = ("Sent", "Delivered", "Read", "Failed")


def _text(value) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _headers(raw: pd.DataFrame) -> dict[str, str]:
    return {re.sub(r"[^a-z]", "", str(column).lower()): column for column in raw.columns}


def is_contacts_export(raw: pd.DataFrame) -> bool:
    headers = _headers(raw)
    return "whatsappnumbers" in headers or "broadcaststatus" in headers or "boadcaststatus" in headers


def carrier_from_tags(tags: str) -> str:
    """Remove segmentos de falha/backup, preservando nomes compostos."""
    carriers = set()
    for tag in tags.split("|"):
        base = tag.strip()
        previous = None
        while base != previous:
            previous = base
            base = re.sub(r"[\s_-]+(?:falhas?|bkp|backup)\s*\d*$", "", base, flags=re.IGNORECASE).strip()
        if base:
            carriers.add(re.sub(r"[\s_]+", " ", base).strip().title())
    if len(carriers) != 1:
        raise ValueError("Tags deve identificar uma única transportadora, com ou sem segmentos de falha/backup.")
    return carriers.pop()


def aggregate_contacts(contacts: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (carrier, campaign, dispatch_date), group in contacts.groupby(["cliente", "campaign_id", "date"], sort=True):
        statuses = group["broadcast_status"]
        snapshot = group.sort_values("whatsapp_number")[["tags", "whatsapp_number", "broadcast_status"]]
        records.append({
            "cliente": carrier, "campaign_id": campaign, "date": dispatch_date, "disparos": 1,
            "total_contatos": len(group), "enviados": int(statuses.isin(["Sent", "Delivered", "Read"]).sum()),
            "entregues": int(statuses.isin(["Delivered", "Read"]).sum()),
            "abertos": int(statuses.eq("Read").sum()), "falhas": int(statuses.eq("Failed").sum()),
            "contacts_json": json.dumps(snapshot.to_dict("records"), ensure_ascii=False, separators=(",", ":")),
        })
    return pd.DataFrame(records, columns=SUMMARY_COLUMNS)


def parse_contacts(raw: pd.DataFrame, context: dict) -> pd.DataFrame:
    headers = _headers(raw)
    if "boadcaststatus" in headers and "broadcaststatus" not in headers:
        headers["broadcaststatus"] = headers["boadcaststatus"]
    required = {"tags": "Tags", "whatsappnumbers": "Whatsapp numbers", "broadcaststatus": "Broadcast Status"}
    missing = [label for key, label in required.items() if key not in headers]
    if missing:
        raise ValueError(f"Colunas ausentes no CSV de contatos: {', '.join(missing)}")
    campaign = _text(context.get("campaign_id"))
    if not campaign:
        raise ValueError("Informe a campanha / ID deste disparo na importação.")
    try:
        dispatch_date = date.fromisoformat(str(context.get("date") or ""))
    except ValueError as exc:
        raise ValueError("Informe a data do disparo. Created On é a data de cadastro do contato.") from exc

    records = []
    seen = set()
    for line, (_, row) in enumerate(raw.iterrows(), start=2):
        tags = " | ".join(tag.strip() for tag in _text(row[headers["tags"]]).split("|") if tag.strip())
        try:
            carrier = carrier_from_tags(tags)
        except ValueError as exc:
            raise ValueError(f"Linha {line}: {exc}") from exc
        number = re.sub(r"[\s().-]", "", _text(row[headers["whatsappnumbers"]]))
        if not re.fullmatch(r"\+?[0-9]{8,15}", number):
            raise ValueError(f"Linha {line}: Whatsapp numbers deve conter um telefone válido com DDI.")
        number = "+" + number.lstrip("+")
        if number in seen:
            raise ValueError(f"Linha {line}: Whatsapp numbers repetido no mesmo disparo; revise o CSV.")
        seen.add(number)
        status = _text(row[headers["broadcaststatus"]]).title()
        if status not in STATUSES:
            raise ValueError(f"Linha {line}: Broadcast Status inválido. Use Sent, Delivered, Read ou Failed.")
        records.append({
            "cliente": carrier, "campaign_id": campaign, "date": dispatch_date,
            "tags": tags, "whatsapp_number": number, "broadcast_status": status,
        })
    return aggregate_contacts(pd.DataFrame(records, columns=CONTACT_COLUMNS))


def contacts_from_campaigns(campaigns: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, campaign in campaigns.iterrows():
        snapshot = campaign.get("contacts_json")
        if not isinstance(snapshot, str) or not snapshot:
            continue
        for contact in json.loads(snapshot):
            records.append({
                **contact, "cliente": campaign["cliente"],
                "campaign_id": campaign["campaign_id"], "date": campaign["date"],
            })
    return pd.DataFrame(records, columns=CONTACT_COLUMNS)
