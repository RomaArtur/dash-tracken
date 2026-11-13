"""Busca no cadastro e histórico por telefone, somente com dados sintéticos."""
from datetime import date
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from metrics import METRICS, sellers, whatsapp
from metrics.whatsapp_contacts import contacts_from_campaigns
from repositories import metrics_repository
from services import metrics_service as ms, seller_search as search


def sample_campaigns():
    frames = []
    for campaign, dispatch, tags, status in (
        ("old", date(2026, 1, 1), "Flexboys | Amazon", "Sent"),
        ("new", date(2026, 11, 12), "Jadlog | Shopee", "Read"),
    ):
        raw = pd.DataFrame([{"Tags": tags, "Whatsapp numbers": "+5511000000001", "Broadcast Status": status}])
        valid, invalid = whatsapp.validate(whatsapp.parse(raw, {"campaign_id": campaign, "date": dispatch}))
        assert invalid.empty
        frames.append(valid)
    return pd.concat(frames, ignore_index=True)


def sample_directory():
    raw = pd.DataFrame([
        ["5511000000001", "Amazon", "Flexboys", "João [1]"],
        ["5511000000001", "Shopee", "Jadlog", "João [1]"],
        ["5511000000001", "Amazon", "Flexboys", "Outro seller"],
        ["5511000000002", "Mercado Livre", "Flexboys", "Loja A-02"],
        ["5511000000003", "Loja Nova", "Nova Rota", "Exemplo"],
    ], columns=list(sellers.LABELS.values()))
    valid, invalid = sellers.validate(sellers.parse(raw))
    assert invalid.empty
    return valid


class SellerSearchTests(unittest.TestCase):
    def setUp(self):
        self.contacts = sample_directory()

    def test_combined_filters_match_the_same_link(self):
        found = search.filter_contacts(self.contacts, carriers=["flexboys"], marketplaces=["AMAZON"],
                                       seller_query="joao [1]", phone_query="(11) 00000-0001")
        self.assertEqual(found["seller_name"].tolist(), ["João [1]"])
        self.assertTrue(search.filter_contacts(self.contacts, carriers=["Flexboys"], marketplaces=["Shopee"]).empty)

    def test_multiselect_uses_or_within_each_field(self):
        found = search.filter_contacts(self.contacts, carriers=["Flexboys", "Jadlog"], marketplaces=["Amazon", "Mercado Livre"])
        self.assertEqual(len(found), 3)
        self.assertEqual(set(found["phone"]), {"+5511000000001", "+5511000000002"})

    def test_marketplace_uses_its_own_column_and_multiple_markets_are_preserved(self):
        extra = self.contacts.iloc[:1].copy().assign(marketplace="Amazon | Mercado Livre")
        found = search.filter_contacts(extra, marketplaces=["mercado livre"])
        self.assertEqual(found.iloc[0]["marketplace"], "Amazon | Mercado Livre")
        extra["marketplace"] = "Amazonas"
        self.assertTrue(search.filter_contacts(extra, marketplaces=["Amazon"]).empty)

    def test_seller_query_is_literal_accent_insensitive_and_only_searches_names(self):
        self.assertEqual(len(search.filter_contacts(self.contacts, seller_query="JOAO [1]")), 2)
        self.assertEqual(len(search.filter_contacts(self.contacts, seller_query="A-02")), 1)
        self.assertTrue(search.filter_contacts(self.contacts, seller_query="Flexboys").empty)

    def test_phone_supports_formatting_and_partial_digits(self):
        for value in ("+55 (11) 00000-0001", "11000000001", "0000-0001"):
            self.assertEqual(len(search.filter_contacts(self.contacts, phone_query=value)), 3)
        self.assertTrue(search.filter_contacts(self.contacts, phone_query="abc()").empty)

    def test_options_use_carriers_and_marketplaces_without_seller_names(self):
        carriers, marketplaces = search.filter_options(self.contacts)
        self.assertIn("Nova Rota", carriers)
        self.assertIn("Loja Nova", marketplaces)
        self.assertNotIn("João [1]", marketplaces)

    def test_results_do_not_merge_distinct_sellers_sharing_a_phone(self):
        results = search.summarize_contacts(self.contacts)
        self.assertEqual(list(results.columns), list(sellers.LABELS.values()))
        self.assertEqual(len(results), 5)
        same_phone = results[results["Telefone"].eq("+5511000000001")]
        self.assertEqual(len(same_phone), 3)
        self.assertEqual(set(same_phone["Nome do seller"]), {"João [1]", "Outro seller"})

    def test_history_matches_phone_without_assigning_seller_identity(self):
        history = search.contact_history(contacts_from_campaigns(sample_campaigns()), "55 (11) 00000-0001")
        self.assertEqual(history["campaign_id"].tolist(), ["new", "old"])
        self.assertEqual(history["broadcast_status"].tolist(), ["Read", "Sent"])

    def test_no_mutation_and_empty_results(self):
        before = self.contacts.copy(deep=True)
        pd.testing.assert_frame_equal(search.filter_contacts(self.contacts), before)
        search.summarize_contacts(self.contacts)
        pd.testing.assert_frame_equal(self.contacts, before)
        empty = self.contacts.iloc[:0]
        self.assertEqual(search.filter_options(empty), ([], []))
        self.assertTrue(search.summarize_contacts(empty).empty)


class SellerSearchLoadingTests(unittest.TestCase):
    def setUp(self):
        ms.clear_cache()
        self.addCleanup(ms.clear_cache)

    def test_search_loads_the_directory_and_not_whatsapp_as_its_base(self):
        connection = object()
        with patch.object(search, "get_connection", return_value=connection), \
             patch.object(metrics_repository, "fetch_metric_df", return_value=sample_directory()) as fetch:
            self.assertEqual(len(search.load_sellers_cached()), 5)
        fetch.assert_called_once_with(connection, METRICS["sellers"])

    def test_import_cache_invalidation_refreshes_directory_and_history(self):
        with patch.object(search, "get_connection", return_value=object()), \
             patch.object(metrics_repository, "fetch_metric_df", return_value=sample_directory()) as fetch:
            self.assertEqual(len(search.load_sellers_cached()), 5)
            fetch.return_value = sample_directory().iloc[:1]
            self.assertEqual(len(search.load_sellers_cached()), 5)
            ms.clear_cache()
            self.assertEqual(len(search.load_sellers_cached()), 1)
            fetch.return_value = sample_campaigns()
            self.assertEqual(len(search.load_contacts_cached()[0]), 2)
            fetch.return_value = sample_campaigns().iloc[:1]
            self.assertEqual(len(search.load_contacts_cached()[0]), 2)
            ms.clear_cache()
            self.assertEqual(len(search.load_contacts_cached()[0]), 1)


class SellerSearchPageTests(unittest.TestCase):
    def setUp(self):
        self.contacts = sample_directory()
        for name, value in (("load_sellers_cached", self.contacts),
                            ("load_contacts_cached", (contacts_from_campaigns(sample_campaigns()), 0))):
            patcher = patch.object(search, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def page(self):
        return AppTest.from_string("from views.seller_search import render_seller_search\nrender_seller_search()", default_timeout=20).run()

    def test_four_column_filters_and_history(self):
        app = self.page()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 5)
        self.load_contacts_cached.assert_not_called()
        app.multiselect(key="seller_carriers").set_value(["Flexboys"]).run()
        app.multiselect(key="seller_marketplaces").set_value(["Amazon"]).run()
        app.text_input(key="seller_phone").set_value("(11) 00000-0001").run()
        app.text_input(key="seller_query").set_value("Joao [1]").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value["Nome do seller"].tolist(), ["João [1]"])
        app.selectbox(key="seller_contact").select("+5511000000001").run()
        self.assertEqual(app.dataframe[1].value["Campanha"].tolist(), ["new", "old"])

    def test_no_whatsapp_history_is_explicit(self):
        app = self.page()
        app.selectbox(key="seller_contact").select("+5511000000003").run()
        self.assertFalse(app.exception)
        self.assertTrue(any("Nenhum disparo" in info.value for info in app.info))

    def test_filters_reset_history_and_clear_restores_all_links(self):
        app = self.page()
        app.selectbox(key="seller_contact").select("+5511000000001").run()
        app.text_input(key="seller_phone").set_value("000000003").run()
        self.assertIsNone(app.selectbox(key="seller_contact").value)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 5)

    def test_removed_options_are_discarded_after_refresh(self):
        app = self.page()
        app.multiselect(key="seller_marketplaces").set_value(["Amazon"]).run()
        self.load_sellers_cached.return_value = self.contacts.iloc[-1:]
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.multiselect(key="seller_marketplaces").value, [])

    def test_invalid_phone_and_empty_directory_have_guidance(self):
        app = self.page()
        app.text_input(key="seller_phone").set_value("abc").run()
        self.assertTrue(app.warning)
        self.assertFalse(app.dataframe)
        self.load_sellers_cached.return_value = self.contacts.iloc[:0]
        app = self.page()
        self.assertTrue(any("Cadastro de sellers" in info.value for info in app.info))

    def test_database_errors_do_not_break_the_page_or_erase_results(self):
        self.load_sellers_cached.side_effect = RuntimeError("test directory unavailable")
        app = self.page()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.load_sellers_cached.side_effect = None
        self.load_contacts_cached.side_effect = RuntimeError("test history unavailable")
        app = self.page()
        app.selectbox(key="seller_contact").select("+5511000000001").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.warning)
        self.assertEqual(len(app.dataframe[0].value), 5)


if __name__ == "__main__":
    unittest.main()
