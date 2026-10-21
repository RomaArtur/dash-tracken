"""Regras de importação e apresentação dos disparos de WhatsApp."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from metrics import METRICS, detect_metric_from_filename, whatsapp
from repositories import import_repository, metrics_repository
from services import database, importer, metrics_service as ms
from views import import_page, metric_page


def campaign(campaign_id="c1", **changes):
    row = {
        "Campanha": campaign_id,
        "Data de envio": date.today().isoformat(),
        "Total de contatos": "100",
        "Enviados": "100",
        "Entregues": "90",
        "Abertos": "45",
    }
    return {**row, **changes}


def normalized(rows, cliente="cliente_a"):
    valid, invalid = whatsapp.validate(whatsapp.parse(pd.DataFrame(rows), {"cliente": cliente}))
    if not invalid.empty:
        raise AssertionError(invalid.to_dict("records"))
    return valid


class WhatsAppImportTests(unittest.TestCase):
    def test_multiple_campaigns_count_bulk_dispatches(self):
        valid = normalized([campaign("c1"), campaign("c2")])
        summary = whatsapp.summarize(valid)
        self.assertEqual(summary.disparos, 2)
        self.assertEqual(summary.contatos, 200)
        self.assertEqual(summary.taxa_entrega, 90)
        self.assertEqual(summary.taxa_abertura, 50)

    def test_rates_are_weighted_by_message_volume(self):
        valid = normalized([
            campaign("small", **{"Total de contatos": "10", "Enviados": "10", "Entregues": "10", "Abertos": "10"}),
            campaign("large", **{"Entregues": "50", "Abertos": "10"}),
        ])
        summary = whatsapp.summarize(valid)
        self.assertAlmostEqual(summary.taxa_entrega, 60 / 110 * 100)
        self.assertAlmostEqual(summary.taxa_abertura, 20 / 60 * 100)

    def test_empty_and_zero_denominators(self):
        self.assertEqual(whatsapp.summarize(pd.DataFrame()), whatsapp.WhatsAppSummary())
        valid = normalized([campaign(**{"Total de contatos": "0", "Enviados": "0", "Entregues": "0", "Abertos": "0"})])
        self.assertEqual(whatsapp.summarize(valid), whatsapp.WhatsAppSummary(disparos=1))

    def test_campaign_can_come_from_import_metadata(self):
        raw = pd.DataFrame([campaign()]).drop(columns="Campanha")
        valid, invalid = whatsapp.validate(whatsapp.parse(raw, {"cliente": "a", "campaign_id": "123"}))
        self.assertTrue(invalid.empty)
        self.assertEqual(valid.iloc[0]["campaign_id"], "123")

    def test_campaign_column_takes_precedence_over_filename(self):
        parsed = whatsapp.parse(pd.DataFrame([campaign("csv-id")]), {"cliente": "a", "campaign_id": "file-id"})
        self.assertEqual(parsed.iloc[0]["campaign_id"], "csv-id")

    def test_missing_metadata_or_columns_are_actionable(self):
        with self.assertRaisesRegex(ValueError, "Cliente"):
            whatsapp.parse(pd.DataFrame([campaign()]))
        with self.assertRaisesRegex(ValueError, "Enviados"):
            whatsapp.parse(pd.DataFrame([campaign()]).drop(columns="Enviados"), {"cliente": "a"})
        with self.assertRaisesRegex(ValueError, "campanha"):
            whatsapp.parse(pd.DataFrame([campaign()]).drop(columns="Campanha"), {"cliente": "a"})

    def test_invalid_counts_dates_and_missing_campaign_are_rejected(self):
        for changes in (
            {"Campanha": None}, {"Campanha": " "}, {"Data de envio": "2026-02-30"},
            {"Enviados": "1.5"}, {"Enviados": "-1"}, {"Enviados": "inf"},
            {"Total de contatos": None}, {"Total de contatos": "2147483648"},
            {"Enviados": "101"}, {"Entregues": "101"}, {"Abertos": "91"},
        ):
            with self.subTest(changes=changes):
                valid, invalid = whatsapp.validate(whatsapp.parse(pd.DataFrame([campaign(**changes)]), {"cliente": "a"}))
                self.assertTrue(valid.empty)
                self.assertEqual(len(invalid), 1)
                self.assertTrue(invalid.iloc[0]["_motivo"])

    def test_duplicate_campaigns_are_rejected_after_normalization(self):
        raw = pd.DataFrame([campaign("c1"), campaign(" c1 ")])
        valid, invalid = whatsapp.validate(whatsapp.parse(raw, {"cliente": "a"}))
        self.assertTrue(valid.empty)
        self.assertEqual(len(invalid), 2)
        self.assertTrue(invalid["_motivo"].str.contains("repetida").all())

    def test_reimport_updates_changed_totals_and_ignores_identical_data(self):
        existing = normalized([campaign("c1"), campaign("c2")])
        raw = pd.DataFrame([campaign("c1"), campaign("c2", **{"Abertos": "50"}), campaign("c3")])
        with patch.object(importer, "get_connection", return_value=object()), \
             patch.object(metrics_repository, "fetch_existing_keys", return_value=existing):
            preview = importer.build_preview(METRICS["whatsapp"], "whatsapp.csv", raw, {"cliente": "cliente_a"})
        self.assertEqual((preview.n_new, preview.n_updated, preview.n_unchanged, preview.n_invalid), (1, 1, 1, 0))

    def test_campaign_ids_are_scoped_to_client(self):
        existing = normalized([campaign()], cliente="cliente_a")
        with patch.object(importer, "get_connection", return_value=object()), \
             patch.object(metrics_repository, "fetch_existing_keys", return_value=existing):
            preview = importer.build_preview(METRICS["whatsapp"], "whatsapp.csv", pd.DataFrame([campaign()]), {"cliente": "cliente_b"})
        self.assertEqual((preview.n_new, preview.n_updated), (1, 0))

    def test_csv_reading_preserves_campaign_ids(self):
        raw = pd.DataFrame([campaign("001")]).to_csv(index=False, sep=";").encode("utf-8-sig")
        valid = normalized(importer.load_csv(raw).to_dict("records"))
        self.assertEqual(valid.iloc[0]["campaign_id"], "001")
        self.assertEqual(detect_metric_from_filename("wpp_cliente_campanhas.csv"), "whatsapp")
        self.assertEqual(detect_metric_from_filename("whatsapp_cliente_123.csv"), "whatsapp")

    def test_campaigns_are_not_counted_as_amazon_clicks(self):
        with patch.object(ms, "load_daily_series_cached", side_effect=AssertionError("não deve carregar campanhas como cliques")):
            self.assertIsNone(ms.clicks_sent("whatsapp", date.today(), date.today()))
        daily = pd.DataFrame({"date": [date.today()], "value": [7]})
        with patch.object(ms, "load_daily_series_cached", return_value=daily):
            self.assertEqual(ms.clicks_sent("login", date.today(), date.today()), 7)
            self.assertEqual(ms.clicks_sent("popup", date.today(), date.today()), 7)


class WhatsAppPageTests(unittest.TestCase):
    def setUp(self):
        self.frames = pd.concat([
            normalized([campaign("current"), campaign("older", **{"Data de envio": (date.today() - timedelta(days=35)).isoformat()})]),
            normalized([campaign("other", **{"Total de contatos": "30", "Enviados": "30", "Entregues": "15", "Abertos": "3"})], cliente="cliente_b"),
        ], ignore_index=True)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.addCleanup(ms.clear_cache)
        ms.clear_cache()
        for module in (database, ms, importer, whatsapp, metric_page, import_page):
            self.stack.enter_context(patch.object(module, "get_connection", return_value=object()))
        self.stack.enter_context(patch.object(database, "init_schema", return_value=None))
        self.stack.enter_context(patch.object(metrics_repository, "fetch_metric_df", side_effect=self.fetch))
        self.stack.enter_context(patch.object(metrics_repository, "distinct_values", return_value=["cliente_a", "cliente_b"]))
        self.stack.enter_context(patch.object(metrics_repository, "fetch_existing_keys", return_value=pd.DataFrame()))
        self.stack.enter_context(patch.object(import_repository, "list_runs", return_value=pd.DataFrame()))

    def fetch(self, conn, metric, date_from=None, date_to=None, filters=None):
        if metric.key != "whatsapp":
            return pd.DataFrame(columns=list(metric.key_columns) + list(metric.value_columns))
        frame = self.frames.copy()
        if date_from is not None:
            frame = frame[frame["date"] >= date_from]
        if date_to is not None:
            frame = frame[frame["date"] <= date_to]
        for column, value in (filters or {}).items():
            frame = frame[frame[column] == value]
        return frame

    def page(self):
        return AppTest.from_string(
            "from views.metric_page import render_metric_page\nrender_metric_page('whatsapp')",
            default_timeout=20,
        ).run()

    def test_four_cards_respect_period_and_client_filters(self):
        app = self.page()
        self.assertFalse(app.exception)
        self.assertEqual([metric.label for metric in app.metric], [
            "Total de Disparos em Massa", "Total de contatos", "Taxa média de entrega", "Taxa média de abertura",
        ])
        self.assertEqual([metric.value for metric in app.metric], ["2", "130", "80,8%", "45,7%"])
        app.selectbox(key="whatsapp_dim_filter").select("cliente_a").run()
        self.assertFalse(app.exception)
        self.assertEqual([metric.value for metric in app.metric], ["1", "100", "90%", "50%"])
        app.selectbox(key="whatsapp_preset").select("Últimos 90 dias").run()
        self.assertFalse(app.exception)
        self.assertEqual([metric.value for metric in app.metric][:2], ["2", "200"])

    def test_empty_state_has_zero_cards_and_template(self):
        self.frames = self.frames.iloc[:0]
        app = self.page()
        self.assertFalse(app.exception)
        self.assertEqual([metric.value for metric in app.metric], ["0", "0", "0%", "0%"])
        self.assertTrue(any("Sem disparos" in info.value for info in app.info))
        self.assertEqual(len(app.get("download_button")), 1)

    def test_upload_uses_campaign_column(self):
        app = AppTest.from_string("from views.import_page import render_import_page\nrender_import_page()", default_timeout=20).run()
        csv = pd.DataFrame([campaign("c1"), campaign("c2")]).to_csv(index=False, sep=";").encode("utf-8-sig")
        app.file_uploader[0].upload("whatsapp_cliente_a.csv", csv, "text/csv").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertNotIn("Campanha / ID", [widget.label for widget in app.text_input])
        self.assertEqual(app.metric[1].value, "2")
        self.assertFalse(app.button[0].disabled)
        self.assertTrue(any("Campanha" in caption.value for caption in app.caption))

    def test_upload_without_campaign_column_uses_filename(self):
        app = AppTest.from_string("from views.import_page import render_import_page\nrender_import_page()", default_timeout=20).run()
        csv = pd.DataFrame([campaign()]).drop(columns="Campanha").to_csv(index=False, sep=";").encode("utf-8")
        app.file_uploader[0].upload("wpp_cliente_123.csv", csv, "text/csv").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(next(widget.value for widget in app.text_input if widget.label == "Campanha / ID"), "123")
        self.assertEqual(app.metric[1].value, "1")

    def test_email_upload_still_uses_client_and_campaign_metadata(self):
        app = AppTest.from_string("from views.import_page import render_import_page\nrender_import_page()", default_timeout=20).run()
        stamp = date.today().isoformat() + " 09:00:00"
        csv = pd.DataFrame([{
            "Email": "teste@example.test", "Status do envio": "Enviado", "Email Lido": "Lido",
            "Subscrição": "Ativa", "Data de criação": stamp, "Data de envio": stamp,
        }]).to_csv(index=False, sep=";").encode("utf-8-sig")
        app.file_uploader[0].upload("email_cliente_123.csv", csv, "text/csv").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(next(widget.value for widget in app.text_input if widget.label == "Campanha / ID"), "123")
        self.assertEqual(app.metric[1].value, "1")

    def test_application_navigation_accepts_registered_whatsapp_page(self):
        # Os módulos das demais páginas importam suas próprias referências.
        from views import overview, amazon_page, import_history
        for module in (overview, amazon_page, import_history):
            self.stack.enter_context(patch.object(module, "get_connection", return_value=object()))
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=20).run()
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
