"""Importação do formato de contatos usando apenas dados sintéticos."""
from datetime import date
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from metrics import whatsapp
from metrics.whatsapp_contacts import carrier_from_tags, contacts_from_campaigns, is_contacts_export
from repositories import metrics_repository
from services import importer
import test_whatsapp as legacy


def contacts():
    return pd.DataFrame([
        {"Tags": " flexboys | flexboys_falha", "Whatsapp numbers": " +55 (11) 00000-0001", "Broadcast Status": " Read"},
        {"Tags": " flexboys_falha | flexboys_bkp2", "Whatsapp numbers": "+5511000000002", "Broadcast Status": " Delivered"},
        {"Tags": " Flexboys falha", "Whatsapp numbers": "+5511000000003", "Broadcast Status": " Sent"},
        {"Tags": "flexboys_bkp", "Whatsapp numbers": "+5511000000004", "Broadcast Status": " Failed"},
    ])


CONTEXT = {"campaign_id": "campanha-001", "date": date.today()}


def normalized(raw=None):
    valid, invalid = whatsapp.validate(whatsapp.parse(contacts() if raw is None else raw, CONTEXT))
    if not invalid.empty:
        raise AssertionError(invalid.to_dict("records"))
    return valid


class ContactImportTests(unittest.TestCase):
    def preview(self, raw, existing):
        with patch.object(importer, "get_connection", return_value=object()), \
             patch.object(metrics_repository, "fetch_existing_keys", return_value=existing):
            return importer.build_preview(whatsapp.DEFINITION, "contacts.csv", raw, CONTEXT)

    def test_statuses_are_cumulative_and_tags_do_not_determine_failure(self):
        frame = normalized()
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0][["cliente", "disparos", "total_contatos", "enviados", "entregues", "abertos", "falhas"]].tolist(),
                         ["Flexboys", 1, 4, 3, 2, 1, 1])
        summary = whatsapp.summarize(frame)
        self.assertEqual((summary.taxa_entrega, summary.taxa_abertura, summary.taxa_falha), (50, 25, 25))

    def test_grouping_removes_segments_and_preserves_compound_carrier_names(self):
        for tag in ("flexboys", "Flexboys falha", "FLEXBOYS_FALHA", "flexboys_bkp2", "flexboys-falha-bkp3"):
            with self.subTest(tag=tag):
                self.assertEqual(carrier_from_tags(tag), "Flexboys")
        self.assertEqual(carrier_from_tags("expresso_do_sul_falha | expresso_do_sul_bkp"), "Expresso Do Sul")

    def test_dot_separated_segments_group_with_the_carrier(self):
        for tags in (
            "MBFLEX | mbflex.bkp", "mbflex.bkp", "MBFLEX.FALHA | mbflex.backup2",
            "mbflex.bkp.2", "mbflex_bkp_2", "mbflex.bkp.falha",
            "outros.bkp | MBFLEX | mbflex.bkp", "bkp.2 | mbflex",
        ):
            with self.subTest(tags=tags):
                self.assertEqual(carrier_from_tags(tags), "Mbflex")
        self.assertEqual(carrier_from_tags("expresso.do.sul | expresso.do.sul.bkp"), "Expresso.Do.Sul")
        with self.assertRaisesRegex(ValueError, "transportadora"):
            carrier_from_tags("mbflex | jadlog.bkp")

    def test_dot_separated_tags_preserve_contacts_statuses_and_original_tags(self):
        raw = contacts()
        raw["Tags"] = ["MBFLEX", "MBFLEX | mbflex.bkp", "MBFLEX", "mbflex.bkp"]
        valid = normalized(raw)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid.iloc[0]["cliente"], "Mbflex")
        self.assertEqual(valid.iloc[0][["total_contatos", "enviados", "entregues", "abertos", "falhas"]].tolist(), [4, 3, 2, 1, 1])
        details = contacts_from_campaigns(valid)
        self.assertEqual(details["tags"].tolist(), raw["Tags"].tolist())
        preview = self.preview(raw.iloc[::-1], valid)
        self.assertEqual((preview.n_new, preview.n_updated, preview.n_unchanged), (0, 0, 1))

    def test_auxiliary_tags_are_not_counted_as_additional_carriers(self):
        for tags, expected in (
            ("buddylog | buddylog_bkp | outros_bkp", "Buddylog"),
            ("buddylog | outros_bkp", "Buddylog"),
            ("TopExpress | outros_bkp", "Topexpress"),
            ("MBI | outros_bkp", "Mbi"),
            ("outros_bkp | buddylog_bkp", "Buddylog"),
            (" OUTROS_BKP2 | falha | backup3 | flexboys_falha", "Flexboys"),
        ):
            with self.subTest(tags=tags):
                self.assertEqual(carrier_from_tags(tags), expected)

    def test_auxiliary_tags_cannot_invent_or_disambiguate_a_carrier(self):
        for tags in ("outros_bkp", "falha | bkp2 | backup", "buddylog | TopExpress | outros_bkp"):
            with self.subTest(tags=tags), self.assertRaisesRegex(ValueError, "transportadora"):
                carrier_from_tags(tags)

    def test_auxiliary_tags_are_preserved_without_changing_contact_totals(self):
        raw = contacts()
        raw.loc[0, "Tags"] = "buddylog | buddylog_bkp | outros_bkp"
        raw.loc[1, "Tags"] = "buddylog | outros_bkp"
        raw.loc[2, "Tags"] = "TopExpress | outros_bkp"
        raw.loc[3, "Tags"] = "MBI | outros_bkp"
        valid = normalized(raw)
        grouped = valid.set_index("cliente")
        self.assertEqual(grouped.loc["Buddylog", "total_contatos"], 2)
        self.assertEqual(grouped.loc["Topexpress", "total_contatos"], 1)
        self.assertEqual(grouped.loc["Mbi", "total_contatos"], 1)
        self.assertEqual(whatsapp.summarize(valid).contatos, 4)
        self.assertEqual(whatsapp.summarize(valid).falhas, 1)
        details = contacts_from_campaigns(valid)
        self.assertTrue(details["tags"].str.contains("outros_bkp").all())

    def test_original_tags_and_phone_are_saved_without_other_contact_fields(self):
        raw = contacts().assign(**{"First name": "Pessoa exemplo", "Emails": "exemplo@example.test"})
        frame = normalized(raw)
        details = contacts_from_campaigns(frame)
        self.assertEqual(details.iloc[0]["tags"], "flexboys | flexboys_falha")
        self.assertEqual(details.iloc[0]["whatsapp_number"], "+5511000000001")
        self.assertNotIn("Pessoa exemplo", frame.iloc[0]["contacts_json"])
        self.assertNotIn("example.test", frame.iloc[0]["contacts_json"])

    def test_comma_semicolon_bom_and_header_variants(self):
        for separator in (",", ";", "\t"):
            with self.subTest(separator=separator):
                raw = contacts().rename(columns={"Whatsapp numbers": " WHATSAPP Numbers ", "Broadcast Status": " Boadcast Status "})
                loaded = importer.load_csv(raw.to_csv(index=False, sep=separator).encode("utf-8-sig"))
                self.assertTrue(is_contacts_export(loaded))
                self.assertEqual(normalized(loaded).iloc[0]["total_contatos"], 4)

    def test_created_on_is_never_used_as_dispatch_date(self):
        raw = contacts().assign(**{"Created On": "2001-01-01 00:00:00"})
        self.assertEqual(normalized(raw).iloc[0]["date"], date.today())
        for context, message in (({"date": date.today()}, "campanha"), ({"campaign_id": "001"}, "data do disparo")):
            with self.subTest(context=context), self.assertRaisesRegex(ValueError, message):
                whatsapp.parse(raw, context)

    def test_missing_headers_are_actionable(self):
        for column in ("Tags", "Whatsapp numbers", "Broadcast Status"):
            with self.subTest(column=column), self.assertRaisesRegex(ValueError, column):
                whatsapp.parse(contacts().drop(columns=column), CONTEXT)

    def test_missing_or_invalid_contact_values_reject_the_export(self):
        for column, value, reason in (
            ("Tags", "", "Tags"), ("Tags", "flexboys | jadlog", "transportadora"),
            ("Whatsapp numbers", "551.1e12", "Whatsapp numbers"), ("Whatsapp numbers", None, "Whatsapp numbers"),
            ("Broadcast Status", "Queued", "Broadcast Status"), ("Broadcast Status", None, "Broadcast Status"),
        ):
            raw = contacts()
            raw.loc[0, column] = value
            with self.subTest(column=column, value=value), self.assertRaisesRegex(ValueError, f"Linha 2:.*{reason}"):
                whatsapp.parse(raw, CONTEXT)

    def test_duplicate_number_is_detected_after_normalizing_punctuation(self):
        raw = contacts()
        raw.loc[1, "Whatsapp numbers"] = "5511000000001"
        with self.assertRaisesRegex(ValueError, "Linha 3:.*repetido"):
            whatsapp.parse(raw, CONTEXT)

    def test_multiple_carriers_are_grouped_without_counting_each_tag(self):
        raw = contacts()
        raw.loc[3, "Tags"] = "Jadlog falha | jadlog_bkp"
        frame = normalized(raw).set_index("cliente")
        self.assertEqual(frame.loc["Flexboys", "total_contatos"], 3)
        self.assertEqual(frame.loc["Jadlog", "total_contatos"], 1)
        self.assertEqual(frame["disparos"].sum(), 2)

    def test_reordering_contacts_is_idempotent(self):
        preview = self.preview(contacts().iloc[::-1], normalized())
        self.assertEqual((preview.n_new, preview.n_updated, preview.n_unchanged), (0, 0, 1))

    def test_status_update_replaces_same_campaign_snapshot(self):
        raw = contacts()
        raw.loc[3, "Broadcast Status"] = "Read"
        preview = self.preview(raw, normalized())
        self.assertEqual((preview.n_new, preview.n_updated, preview.n_unchanged), (0, 1, 0))
        updated = preview.updated_df.iloc[0]
        self.assertEqual((updated["disparos"], updated["abertos"], updated["falhas"]), (1, 2, 0))
        self.assertEqual(len(contacts_from_campaigns(preview.updated_df)), 4)

    def test_changed_contact_details_are_updated_even_if_totals_are_equal(self):
        raw = contacts()
        raw.loc[0, "Whatsapp numbers"] = "+5511000000099"
        preview = self.preview(raw, normalized())
        self.assertEqual(preview.n_updated, 1)

    def test_legacy_campaign_has_no_invented_contact_details(self):
        self.assertTrue(contacts_from_campaigns(legacy.normalized([legacy.campaign()])).empty)
        self.assertTrue(contacts_from_campaigns(pd.DataFrame()).empty)

    def test_empty_contacts_export_has_no_campaign(self):
        self.assertTrue(normalized(contacts().iloc[:0]).empty)


class ContactPageTests(unittest.TestCase):
    # Reutiliza somente o isolamento de banco, sem repetir os testes legados.
    setUp = legacy.WhatsAppPageTests.setUp
    fetch = legacy.WhatsAppPageTests.fetch
    page = legacy.WhatsAppPageTests.page

    def test_upload_with_dot_separated_backup_tag(self):
        raw = contacts()
        raw["Tags"] = ["MBFLEX", "MBFLEX", "MBFLEX | mbflex.bkp", "mbflex.bkp"]
        app = AppTest.from_string("from views.import_page import render_import_page\nrender_import_page()", default_timeout=20).run()
        app.file_uploader[0].upload("contacts.csv", raw.to_csv(index=False).encode("utf-8-sig"), "text/csv").run()
        app.text_input[0].set_value("Controle interno Mbflex").run()
        app.date_input[0].set_value(date.today()).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.metric[1].value, "1")
        details = app.dataframe[0].value
        self.assertEqual(len(details), 4)
        self.assertEqual(set(details["Transportadora"]), {"Mbflex"})
        self.assertIn("MBFLEX | mbflex.bkp", details["Tags"].tolist())
        self.assertFalse(app.button[0].disabled)

    def test_upload_with_auxiliary_tags_generates_preview_for_each_carrier(self):
        raw = contacts()
        raw["Tags"] = [
            "buddylog | buddylog_bkp | outros_bkp", "TopExpress | outros_bkp",
            "MBI | outros_bkp", "mapspremium",
        ]
        app = AppTest.from_string("from views.import_page import render_import_page\nrender_import_page()", default_timeout=20).run()
        app.file_uploader[0].upload("contacts.csv", raw.to_csv(index=False).encode("utf-8-sig"), "text/csv").run()
        app.text_input[0].set_value("Buddylog_TopExpress_MBI_mapspremium").run()
        app.date_input[0].set_value(date.today()).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.metric[1].value, "4")
        details = app.dataframe[0].value
        self.assertEqual(set(details["Transportadora"]), {"Buddylog", "Topexpress", "Mbi", "Mapspremium"})
        self.assertEqual(len(details), 4)
        self.assertIn("outros_bkp", details.iloc[0]["Tags"])
        self.assertFalse(app.button[0].disabled)

    def test_contact_export_is_detected_without_filename_prefix_and_requires_metadata(self):
        app = AppTest.from_string("from views.import_page import render_import_page\nrender_import_page()", default_timeout=20).run()
        csv = contacts().to_csv(index=False).encode("utf-8-sig")
        app.file_uploader[0].upload("123_contacts.csv", csv, "text/csv").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.selectbox[0].value, "Disparos WhatsApp")
        self.assertEqual(len(app.selectbox), 1)  # transportadoras são extraídas de Tags
        self.assertFalse(app.metric)
        self.assertIsNone(app.date_input[0].value)
        app.text_input[0].set_value("campanha-001").run()
        self.assertFalse(app.metric)
        app.date_input[0].set_value(date.today()).run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.metric[1].value, "1")
        details = app.dataframe[0].value
        self.assertEqual(list(details.columns)[:3], ["Tags", "Whatsapp numbers", "Broadcast Status"])
        self.assertEqual(set(details["Transportadora"]), {"Flexboys"})
        self.assertEqual(len(details), 4)
        with patch.object(importer, "commit_import", return_value=8) as commit:
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.success)
        self.assertEqual(len(contacts_from_campaigns(commit.call_args.args[0].valid_df)), 4)

    def test_contact_details_follow_carrier_and_period_filters(self):
        first = normalized()
        second_raw = contacts().iloc[:1].copy()
        second_raw["Tags"] = "jadlog_falha"
        self.frames = pd.concat([first, normalized(second_raw)], ignore_index=True)
        with patch.object(metrics_repository, "distinct_values", return_value=["Flexboys", "Jadlog"]):
            app = self.page()
            self.assertFalse(app.exception)
            details = next(item.value for item in app.dataframe if "Whatsapp numbers" in item.value.columns)
            self.assertEqual(len(details), 5)
            app.selectbox(key="whatsapp_dim_filter").select("Flexboys").run()
        self.assertFalse(app.exception)
        self.assertEqual([metric.value for metric in app.metric], ["1", "4", "50%", "25%", "1"])
        details = next(item.value for item in app.dataframe if "Whatsapp numbers" in item.value.columns)
        self.assertEqual(set(details["Transportadora"]), {"Flexboys"})


if __name__ == "__main__":
    unittest.main()
