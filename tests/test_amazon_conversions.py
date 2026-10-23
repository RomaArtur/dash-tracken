"""Conversões Amazon, leitura do Excel e preservação dos indicadores existentes."""
from contextlib import ExitStack
from datetime import date, timedelta
from io import BytesIO
import json
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from components import charts
from metrics import amazon_funnel, amazon_traffic
from repositories import metrics_repository
from services import importer, metrics_service as ms
from services.amazon_conversions import conversion_rates, funnel_counts
from utils.tokens import AMAZON_GREENS
from views import amazon_page


def seller(identifier="demo-1", **changes):
    row = {column: None for column in amazon_funnel._SOURCE_COLUMNS}
    row.update(merchant_customer_id=identifier, source_detail="log - tracken", registration_start_date=date.today())
    row.update(changes)
    return row


def normalized_funnel(rows):
    valid, invalid = amazon_funnel.validate(amazon_funnel.parse(pd.DataFrame(rows)))
    if not invalid.empty:
        raise AssertionError(invalid["_motivo"].tolist())
    return valid


def sample_funnel():
    return normalized_funnel([
        seller("demo-1", registration_complete_date=date.today(), siv_approved_indicator=1,
               rtl_date=date.today(), launch_date=date.today(), is_fba_eligible="Y"),
        seller("demo-2", registration_complete_date=date.today(), siv_approved_indicator=1, rtl_date=date.today()),
        seller("demo-3"), seller("demo-4", source_detail="pop - tracken"),
        seller("demo-5", source_detail="pop - tracken"),
    ])


def sample_traffic():
    return pd.DataFrame([
        {"date": date.today(), "channel": "login", "visits": 300},
        {"date": date.today(), "channel": "popup", "visits": 172},
    ])


class ConversionTests(unittest.TestCase):
    def test_reference_rates_use_each_named_denominator(self):
        rates = conversion_rates(sample_funnel(), sample_traffic()).set_index("key")
        expected = {"traffic_rs": 5 / 472 * 100, "rs_rc": 40, "rc_rv": 100, "rv_rtl": 100,
                    "rtl_launch": 50, "rs_rtl": 40, "rs_launch": 20, "fba": 0}
        self.assertEqual(set(rates.index), set(expected))
        for key, value in expected.items():
            with self.subTest(conversion=key):
                self.assertAlmostEqual(rates.loc[key, "rate"], value)
        self.assertEqual((rates.loc["fba", "base"], rates.loc["fba", "converted"]), (1, 0))

    def test_w30_reference_counts(self):
        funnel = normalized_funnel([
            seller("a", registration_complete_date=date.today(), siv_approved_indicator=1, rtl_date=date.today()),
            seller("b"), seller("c"),
        ])
        traffic = pd.DataFrame([{"visits": 147}])
        rates = conversion_rates(funnel, traffic).set_index("key")
        self.assertAlmostEqual(rates.loc["traffic_rs", "rate"], 3 / 147 * 100)
        self.assertAlmostEqual(rates.loc["rs_rc", "rate"], 100 / 3)
        self.assertEqual(rates.loc["rc_rv", "rate"], 100)
        self.assertEqual(rates.loc["rs_launch", "rate"], 0)

    def test_missing_or_zero_base_does_not_become_zero_percent(self):
        rates = conversion_rates(sample_funnel(), pd.DataFrame()).set_index("key")
        self.assertTrue(pd.isna(rates.loc["traffic_rs", "rate"]))
        self.assertEqual(rates.loc["rs_rc", "rate"], 40)
        zero = normalized_funnel([seller()])
        rates = conversion_rates(zero, pd.DataFrame([{"visits": 0}])).set_index("key")
        self.assertTrue(pd.isna(rates.loc["traffic_rs", "rate"]))
        self.assertTrue(pd.isna(rates.loc["rc_rv", "rate"]))
        self.assertTrue(pd.isna(rates.loc["fba", "rate"]))
        self.assertEqual(rates.loc["rs_rc", "rate"], 0)

    def test_existing_funnel_including_kyc_and_fba_is_preserved(self):
        labels, values = funnel_counts(sample_funnel())
        self.assertEqual(labels, ["Reg Start", "Reg Complete", "Verificado (RV)", "KYC", "Ready to Launch", "Launch", "FBA Launch"])
        self.assertEqual(values, [5, 2, 2, 0, 2, 1, 0])
        self.assertEqual(funnel_counts(pd.DataFrame()), ([], []))

    def test_rv_uses_approval_and_fba_uses_eligibility(self):
        funnel = normalized_funnel([
            seller("a", siv_approved_indicator=0, is_fba_eligible="n"),
            seller("b", siv_approved_indicator=1, is_fba_eligible=" y ", fba_launch_date=date.today()),
        ])
        rates = conversion_rates(funnel, sample_traffic()).set_index("key")
        self.assertEqual(rates.loc["rv_rtl", "base"], 1)
        self.assertEqual((rates.loc["fba", "base"], rates.loc["fba", "converted"], rates.loc["fba", "rate"]), (1, 1, 100))

    def test_non_monotonic_data_is_not_clipped_or_filled_in(self):
        funnel = normalized_funnel([
            seller("a", siv_approved_indicator=1, rtl_date=date.today()),
            seller("b", rtl_date=date.today()),
        ])
        rates = conversion_rates(funnel, sample_traffic())
        self.assertEqual(rates.set_index("key").loc["rv_rtl", "rate"], 200)
        self.assertGreater(charts.conversion_bars(rates).layout.xaxis.range[1], 200)

    def test_calculation_does_not_mutate_imported_data(self):
        funnel, traffic = sample_funnel(), sample_traffic()
        before_funnel, before_traffic = funnel.copy(deep=True), traffic.copy(deep=True)
        conversion_rates(funnel, traffic)
        pd.testing.assert_frame_equal(funnel, before_funnel)
        pd.testing.assert_frame_equal(traffic, before_traffic)

    def test_green_charts_and_default_funnel_contract(self):
        labels, values = funnel_counts(sample_funnel())
        figure = charts.funnel_chart(labels, values, colors=AMAZON_GREENS[:len(labels)])
        self.assertEqual(list(figure.data[0].marker.color), list(AMAZON_GREENS[:len(labels)]))
        self.assertEqual(charts.funnel_chart(labels, values).data[0].marker.color, "#28A828")
        rates = conversion_rates(sample_funnel(), pd.DataFrame())
        figure = charts.conversion_bars(rates)
        self.assertTrue(any(annotation.text == "n/a" for annotation in figure.layout.annotations))


class AmazonImportTests(unittest.TestCase):
    def test_visits_are_numeric_before_aggregation(self):
        raw = pd.DataFrame([
            {"day": "2026-08-29", "source_detail": "pop - tracken", "visits_num": "3"},
            {"day": "2026-08-29", "source_detail": "pop - tracken", "visits_num": "9"},
        ])
        valid, invalid = amazon_traffic.validate(amazon_traffic.parse(raw))
        self.assertTrue(invalid.empty)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid.iloc[0]["visits"], 12)

    def test_bad_visit_rows_are_reported_before_grouping(self):
        for value in ("-1", "1.5", "abc", "inf", "2147483648"):
            with self.subTest(value=value):
                raw = pd.DataFrame([
                    {"day": "2026-08-29", "source_detail": "pop - tracken", "visits_num": "3"},
                    {"day": "2026-08-29", "source_detail": "pop - tracken", "visits_num": value},
                ])
                valid, invalid = amazon_traffic.validate(amazon_traffic.parse(raw))
                self.assertEqual(len(invalid), 1)
                self.assertEqual(valid.iloc[0]["visits"], 3)

    def test_formatted_empty_excel_rows_do_not_become_invalid_records(self):
        raw_funnel = pd.DataFrame([seller(), {column: None for column in amazon_funnel._SOURCE_COLUMNS}])
        raw_traffic = pd.DataFrame([
            {"day": date.today(), "source_detail": "log - tracken", "visits_num": 10},
            {"day": None, "source_detail": None, "visits_num": None},
        ])
        for metric, raw in ((amazon_funnel, raw_funnel), (amazon_traffic, raw_traffic)):
            with self.subTest(metric=metric.KEY):
                valid, invalid = metric.validate(metric.parse(raw))
                self.assertTrue(invalid.empty)
                self.assertEqual(len(valid), 1)

    def test_existing_excel_sheets_and_idempotent_import_remain_supported(self):
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame([seller()]).to_excel(writer, sheet_name="funnel", index=False)
            pd.DataFrame([{"day": date.today(), "source_detail": "log - tracken", "visits_num": 10}]).to_excel(writer, sheet_name="traffic", index=False)
        for module in (amazon_funnel, amazon_traffic):
            with self.subTest(metric=module.KEY):
                metric = module.DEFINITION
                raw = importer.load_xlsx(buffer.getvalue(), metric.xlsx_sheet)
                existing, invalid = metric.validate(metric.parse(raw))
                self.assertTrue(invalid.empty)
                with patch.object(importer, "get_connection", return_value=object()), \
                     patch.object(metrics_repository, "fetch_existing_keys", return_value=existing):
                    preview = importer.build_preview(metric, "amazon.xlsx", raw)
                self.assertEqual((preview.n_new, preview.n_updated, preview.n_unchanged), (0, 0, 1))


class AmazonPageTests(unittest.TestCase):
    def setUp(self):
        self.funnel, self.traffic = sample_funnel(), sample_traffic()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for module in (amazon_page, ms):
            self.stack.enter_context(patch.object(module, "get_connection", return_value=object()))
        self.stack.enter_context(patch.object(metrics_repository, "fetch_metric_df", side_effect=self.fetch))
        self.stack.enter_context(patch.object(ms, "clicks_sent", side_effect=lambda channel, *args: None if channel == "whatsapp" else 1000))

    def fetch(self, conn, metric, date_from=None, date_to=None, filters=None):
        frame = (self.funnel if metric.key == "amazon_funnel" else self.traffic).copy()
        if date_from is not None:
            frame = frame[frame["date"] >= date_from]
        if date_to is not None:
            frame = frame[frame["date"] <= date_to]
        for column, value in (filters or {}).items():
            frame = frame[frame[column] == value]
        return frame

    def page(self):
        return AppTest.from_string("from views.amazon_page import render_amazon_page\nrender_amazon_page()", default_timeout=20).run()

    def test_adds_reference_conversions_and_preserves_existing_sections(self):
        app = self.page()
        self.assertFalse(app.exception)
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Tráfego → Reg Start"], "1,1%")
        self.assertEqual(metrics["Reg Start → RTL"], "40,0%")
        self.assertEqual(metrics["Reg Start → Launch"], "20,0%")
        self.assertTrue(any("Cliques enviados: ainda não disponível" in caption.value for caption in app.caption))
        self.assertTrue(any(expander.label == "Vendedores no período" for expander in app.expander))
        self.assertTrue(any("Taxa de conversão clique → visita" in caption.value for caption in app.caption))
        figures = [json.loads(chart.proto.spec) for chart in app.get("plotly_chart")]
        self.assertEqual(len(figures), 2)
        for figure in figures:
            self.assertTrue(all(color in AMAZON_GREENS for color in figure["data"][0]["marker"]["color"]))

    def test_missing_traffic_only_disables_traffic_conversion(self):
        self.traffic = self.traffic.iloc[:0]
        app = self.page()
        self.assertFalse(app.exception)
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Tráfego → Reg Start"], "—")
        self.assertEqual(metrics["Reg Start → RTL"], "40,0%")

    def test_empty_funnel_keeps_existing_empty_state(self):
        self.funnel = self.funnel.iloc[:0]
        app = self.page()
        self.assertFalse(app.exception)
        self.assertTrue(any("Sem vendedores" in item.value for item in app.info))

    def test_period_uses_registration_start_and_preserves_latest_progress(self):
        old = normalized_funnel([seller("old", registration_start_date=date.today() - timedelta(days=40), launch_date=date.today())])
        self.funnel = pd.concat([self.funnel, old], ignore_index=True)
        app = self.page()
        self.assertFalse(app.exception)
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Reg Start → Launch"], "20,0%")
        app.selectbox(key="amazon_preset").select("Últimos 90 dias").run()
        self.assertFalse(app.exception)
        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertEqual(metrics["Reg Start → Launch"], "33,3%")


if __name__ == "__main__":
    unittest.main()
