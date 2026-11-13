"""Busca por tags/telefone e histórico, usando exclusivamente contatos sintéticos."""
from datetime import date
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from metrics import METRICS, whatsapp
from metrics.whatsapp_contacts import CONTACT_COLUMNS, contacts_from_campaigns
from repositories import metrics_repository
from services import metrics_service as ms, seller_search as search
from views import seller_search as page


def sample_campaigns():
    frames = []
    for campaign, dispatch, tags, number, status in (
        ("old", date(2026, 1, 1), "Flexboys | Amazon | seller: João [1]", "+5511000000001", "Sent"),
        ("new", date(2026, 11, 12), "Jadlog | Shopee | seller: João [1]", "+5511000000001", "Read"),
        ("new", date(2026, 11, 12), "Flexboys | Mercado Livre | seller_id: A-02", "+5511000000002", "Delivered"),
        ("other", date(2026, 11, 12), "Nova Rota | Loja Nova | seller: Exemplo", "+5511000000003", "Failed"),
    ):
        raw = pd.DataFrame([{"Tags": tags, "Whatsapp numbers": number, "Broadcast Status": status}])
        valid, invalid = whatsapp.validate(whatsapp.parse(raw, {"campaign_id": campaign, "date": dispatch}))
        assert invalid.empty
        frames.append(valid)
    return pd.concat(frames, ignore_index=True)


class SellerSearchTests(unittest.TestCase):
    def setUp(self):
        self.contacts = contacts_from_campaigns(sample_campaigns())

    def test_filters_combine_carrier_tag_and_phone(self):
        found = search.filter_contacts(
            self.contacts, carriers=["flexboys"], marketplace_tags=["AMAZON"], phone_query="(11) 00000-0001",
        )
        self.assertEqual(found["campaign_id"].tolist(), ["old"])

    def test_filters_do_not_cross_unrelated_campaigns_for_the_same_phone(self):
        found = search.filter_contacts(self.contacts, carriers=["Flexboys"], marketplace_tags=["Shopee"])
        self.assertTrue(found.empty)

    def test_multiselect_uses_or_within_each_filter(self):
        found = search.filter_contacts(
            self.contacts, carriers=["Flexboys", "Jadlog"], marketplace_tags=["Amazon", "Mercado Livre"],
        )
        self.assertEqual(set(found["whatsapp_number"]), {"+5511000000001", "+5511000000002"})
        self.assertEqual(len(found), 2)

    def test_tag_match_is_exact_and_seller_text_is_literal_and_accent_insensitive(self):
        extra = self.contacts.iloc[:1].copy().assign(tags="Flexboys | Amazonas")
        found = search.filter_contacts(pd.concat([self.contacts, extra]), marketplace_tags=[" Amazon "])
        self.assertEqual(len(found), 1)
        found = search.filter_contacts(self.contacts, seller_query="JOAO [1]")
        self.assertEqual(len(found), 2)
        found = search.filter_contacts(self.contacts, seller_query="A-02")
        self.assertEqual(found["whatsapp_number"].tolist(), ["+5511000000002"])

    def test_phone_accepts_formatting_partial_numbers_and_country_code(self):
        for value in ("+55 (11) 00000-0001", "11000000001", "0000-0001"):
            with self.subTest(value=value):
                self.assertEqual(len(search.filter_contacts(self.contacts, phone_query=value)), 2)
        self.assertTrue(search.filter_contacts(self.contacts, phone_query="abc()").empty)

    def test_new_marketplace_tags_need_no_code_or_import_changes(self):
        carriers, tags = search.filter_options(self.contacts)
        self.assertIn("Nova Rota", carriers)
        self.assertIn("Loja Nova", tags)
        self.assertEqual(len(search.filter_contacts(self.contacts, marketplace_tags=["Loja Nova"])), 1)

    def test_one_result_per_phone_preserves_all_matching_links(self):
        results = search.summarize_contacts(self.contacts)
        self.assertEqual(len(results), 3)
        first = results.set_index("Telefone").loc["+5511000000001"]
        self.assertEqual(first["Transportadoras"], "Flexboys | Jadlog")
        self.assertIn("Amazon", first["Tags"])
        self.assertIn("Shopee", first["Tags"])
        self.assertEqual(first["Disparos encontrados"], 2)
        self.assertEqual(first["Último disparo"], date(2026, 11, 12))

    def test_history_preserves_each_campaign_and_status(self):
        history = search.contact_history(self.contacts, "+5511000000001")
        self.assertEqual(history["campaign_id"].tolist(), ["new", "old"])
        self.assertEqual(history["broadcast_status"].tolist(), ["Read", "Sent"])

    def test_filters_and_summary_do_not_mutate_imported_data(self):
        before = self.contacts.copy(deep=True)
        pd.testing.assert_frame_equal(search.filter_contacts(self.contacts), before)
        search.summarize_contacts(self.contacts)
        search.contact_history(self.contacts, "+5511000000001")
        pd.testing.assert_frame_equal(self.contacts, before)
        empty = self.contacts.iloc[:0]
        self.assertEqual(search.filter_options(empty), ([], []))
        self.assertTrue(search.filter_contacts(empty).empty)
        self.assertTrue(search.summarize_contacts(empty).empty)


class SellerSearchLoadingTests(unittest.TestCase):
    def setUp(self):
        search.load_contacts_cached.clear()
        self.addCleanup(search.load_contacts_cached.clear)

    def test_loader_reads_all_history_and_counts_legacy_summaries(self):
        campaigns = sample_campaigns()
        legacy = campaigns.iloc[:1].copy().assign(contacts_json=None, campaign_id="legacy")
        connection = object()
        with patch.object(search, "get_connection", return_value=connection), \
             patch.object(metrics_repository, "fetch_metric_df", return_value=pd.concat([campaigns, legacy])) as fetch:
            contacts, without_details = search.load_contacts_cached()
        fetch.assert_called_once_with(connection, METRICS["whatsapp"])
        self.assertEqual(len(contacts), 4)
        self.assertEqual(without_details, 1)
        self.assertIn(date(2026, 1, 1), contacts["date"].tolist())

    def test_existing_import_cache_invalidation_refreshes_search(self):
        campaigns = sample_campaigns()
        with patch.object(search, "get_connection", return_value=object()), \
             patch.object(metrics_repository, "fetch_metric_df", return_value=campaigns) as fetch:
            self.assertEqual(len(search.load_contacts_cached()[0]), 4)
            fetch.return_value = campaigns.iloc[:1]
            self.assertEqual(len(search.load_contacts_cached()[0]), 4)
            ms.clear_cache()
            self.assertEqual(len(search.load_contacts_cached()[0]), 1)
            self.assertEqual(fetch.call_count, 2)


class SellerSearchPageTests(unittest.TestCase):
    def setUp(self):
        self.contacts = contacts_from_campaigns(sample_campaigns())
        self.loader = patch.object(search, "load_contacts_cached", return_value=(self.contacts, 0))
        self.load = self.loader.start()
        self.addCleanup(self.loader.stop)

    def page(self):
        return AppTest.from_string(
            "from views.seller_search import render_seller_search\nrender_seller_search()", default_timeout=20,
        ).run()

    def test_page_searches_all_history_and_combines_filters(self):
        app = self.page()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.dataframe[0].value), 3)
        app.multiselect(key="seller_carriers").set_value(["Flexboys"]).run()
        app.multiselect(key="seller_marketplaces").set_value(["Amazon"]).run()
        app.text_input(key="seller_phone").set_value("(11) 00000-0001").run()
        app.text_input(key="seller_query").set_value("Joao [1]").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[0].value["Telefone"].tolist(), ["+5511000000001"])

    def test_selected_contact_shows_complete_history(self):
        app = self.page()
        app.multiselect(key="seller_marketplaces").set_value(["Amazon"]).run()
        app.selectbox(key="seller_contact").select("+5511000000001").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.dataframe[1].value["Campanha"].tolist(), ["new", "old"])
        self.assertEqual(app.dataframe[1].value["Broadcast Status"].tolist(), ["Read", "Sent"])

    def test_changing_results_resets_history_selection_and_clear_restores_results(self):
        app = self.page()
        app.selectbox(key="seller_contact").select("+5511000000001").run()
        app.text_input(key="seller_phone").set_value("000000003").run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.selectbox(key="seller_contact").value)
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.text_input(key="seller_phone").value, "")
        self.assertEqual(len(app.dataframe[0].value), 3)

    def test_removed_tags_are_discarded_after_data_refresh(self):
        app = self.page()
        app.multiselect(key="seller_marketplaces").set_value(["Amazon"]).run()
        self.load.return_value = (self.contacts.iloc[-1:], 0)
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.multiselect(key="seller_marketplaces").value, [])
        self.assertEqual(app.dataframe[0].value["Telefone"].tolist(), ["+5511000000003"])

    def test_invalid_phone_and_no_matches_are_explicit(self):
        app = self.page()
        app.text_input(key="seller_phone").set_value("abc").run()
        self.assertFalse(app.exception)
        self.assertTrue(app.warning)
        self.assertFalse(app.dataframe)
        self.assertTrue(any("Nenhum contato" in info.value for info in app.info))

    def test_empty_contacts_and_legacy_imports_have_clear_guidance(self):
        self.load.return_value = (pd.DataFrame(columns=CONTACT_COLUMNS), 2)
        app = self.page()
        self.assertFalse(app.exception)
        self.assertTrue(any("Importe um CSV" in info.value for info in app.info))
        self.assertTrue(any("2 disparo(s)" in item.value for item in app.caption))

    def test_database_error_is_shown_without_breaking_the_page(self):
        self.load.side_effect = RuntimeError("test database unavailable")
        app = self.page()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)


if __name__ == "__main__":
    unittest.main()
