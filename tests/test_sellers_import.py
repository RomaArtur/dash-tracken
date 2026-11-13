"""Importação do cadastro de sellers a partir de CSV e Excel sintéticos."""
from io import BytesIO
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from metrics import sellers, whatsapp
from repositories import metrics_repository
from services import importer
from utils.phones import normalize_phone
from views import import_page
from test_seller_search import sample_directory


def raw_directory():
    return sample_directory()[list(sellers.LABELS)].rename(columns=sellers.LABELS)


def workbook_bytes(sheets):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return buffer.getvalue()


class PhoneTests(unittest.TestCase):
    def test_text_and_numeric_excel_phones_keep_the_same_digits(self):
        for value in ("5511000000001", "+55 (11) 00000-0001", 5511000000001, 5511000000001.0, "5511000000001.0", "+5511000000001.0"):
            with self.subTest(value=value):
                self.assertEqual(normalize_phone(value), "+5511000000001")

    def test_missing_zero_malformed_fractional_and_scientific_strings_are_not_phones(self):
        for value in (None, pd.NA, "", 0, "0", "00000000", "551.1e12", "5.511e12", 5511000000001.5, "5511000000001.5", "+5511000000001.5", "5511000000001/5511000000002", "9" * 16):
            with self.subTest(value=str(value)):
                self.assertIsNone(normalize_phone(value))

    def test_whatsapp_does_not_append_a_decimal_zero(self):
        raw = pd.DataFrame([{"Tags": "Exemplo", "Whatsapp numbers": "5511000000001.0", "Broadcast Status": "Sent"}])
        parsed = whatsapp.parse(raw, {"campaign_id": "demo", "date": "2026-11-13"})
        self.assertIn('"whatsapp_number":"+5511000000001"', parsed.iloc[0]["contacts_json"])


class SellerImportTests(unittest.TestCase):
    def test_explicit_columns_need_no_campaign_status_or_date(self):
        raw = raw_directory()
        self.assertTrue(sellers.is_seller_directory(raw))
        valid, invalid = sellers.validate(sellers.parse(raw))
        self.assertTrue(invalid.empty)
        self.assertEqual(len(valid), 5)
        self.assertNotIn("campaign_id", valid)
        self.assertNotIn("date", valid)

    def test_header_variants_and_missing_columns(self):
        raw = raw_directory().rename(columns={"Telefone": " TELEFONE ", "Nome do seller": "Nome do Seller"})
        self.assertTrue(sellers.is_seller_directory(raw))
        self.assertEqual(len(sellers.validate(sellers.parse(raw))[0]), 5)
        with self.assertRaisesRegex(ValueError, "Marketplace"):
            sellers.parse(raw.drop(columns="Marketplace"))

    def test_shared_phones_and_multiple_marketplaces_preserve_each_link(self):
        raw = raw_directory()
        raw.loc[0, "Marketplace"] = "Amazon | Mercado Livre"
        valid, invalid = sellers.validate(sellers.parse(raw))
        self.assertTrue(invalid.empty)
        self.assertEqual((len(valid), valid["phone"].nunique()), (5, 3))
        self.assertEqual(valid.iloc[0]["marketplace"], "Amazon | Mercado Livre")

    def test_only_identical_canonical_links_are_deduplicated(self):
        raw = raw_directory()
        duplicate = raw.iloc[:1].copy().assign(Telefone="55 (11) 00000-0001")
        valid, invalid = sellers.validate(sellers.parse(pd.concat([raw, duplicate])))
        self.assertTrue(invalid.empty)
        self.assertEqual(len(valid), 5)

    def test_zero_phones_are_reported_without_blocking_valid_links(self):
        raw = raw_directory()
        extra = raw.iloc[:1].copy().assign(Telefone="0")
        valid, invalid = sellers.validate(sellers.parse(pd.concat([raw, extra], ignore_index=True)))
        self.assertEqual((len(valid), len(invalid)), (5, 1))
        self.assertIn("valor 0", invalid.iloc[0]["_motivo"])

    def test_missing_descriptions_and_blank_rows(self):
        raw = raw_directory().iloc[:1].copy()
        raw["Marketplace"] = None
        raw["Nome do seller"] = ""
        raw = pd.concat([raw, pd.DataFrame([{column: None for column in raw.columns}])], ignore_index=True)
        valid, invalid = sellers.validate(sellers.parse(raw))
        self.assertTrue(invalid.empty)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid.iloc[0]["marketplace"], "Não informado")
        self.assertEqual(valid.iloc[0]["seller_name"], "Não informado")

    def test_reimport_is_idempotent(self):
        with patch.object(importer, "get_connection", return_value=object()), \
             patch.object(metrics_repository, "fetch_existing_keys", return_value=sample_directory()):
            preview = importer.build_preview(sellers.DEFINITION, "sellers.csv", raw_directory())
        self.assertEqual((preview.n_new, preview.n_updated, preview.n_unchanged), (0, 0, 5))

    def test_excel_phone_text_and_sheets_are_preserved(self):
        raw = raw_directory()
        raw["Telefone"] = raw["Telefone"].str.lstrip("+")
        content = workbook_bytes({"Contatos únicos": raw.iloc[:1], "Vínculos por seller": raw})
        self.assertEqual(importer.xlsx_sheet_names(content), ["Contatos únicos", "Vínculos por seller"])
        valid, invalid = sellers.validate(sellers.parse(importer.load_xlsx(content, "Vínculos por seller", dtype=object)))
        self.assertTrue(invalid.empty)
        self.assertEqual(valid["phone"].tolist(), sample_directory()["phone"].tolist())


class SellerImportPageTests(unittest.TestCase):
    def setUp(self):
        patchers = [patch.object(module, "get_connection", return_value=object()) for module in (importer, import_page)]
        patchers.append(patch.object(metrics_repository, "fetch_existing_keys", return_value=pd.DataFrame()))
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def page(self):
        return AppTest.from_string("from views.import_page import render_import_page\nrender_import_page()", default_timeout=20).run()

    def test_csv_detects_columns_without_campaign_or_status_inputs(self):
        app = self.page()
        app.file_uploader[0].upload("base.csv", raw_directory().to_csv(index=False, sep=";").encode("utf-8-sig"), "text/csv").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.selectbox[0].value, "Cadastro de sellers")
        self.assertFalse(app.text_input)
        self.assertFalse(app.date_input)
        self.assertEqual(len(app.dataframe[0].value), 5)
        with patch.object(importer, "commit_import", return_value=7) as commit:
            app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.success)
        self.assertEqual(len(commit.call_args.args[0].valid_df), 5)

    def test_excel_defaults_to_links_instead_of_unique_phones(self):
        raw = raw_directory()
        content = workbook_bytes({"Contatos únicos": raw.iloc[:1], "Vínculos por seller": raw,
                                  "Sem telefone": raw.iloc[:1].copy().assign(Telefone="0")})
        app = self.page()
        app.file_uploader[0].upload("sellers_base.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(app.selectbox[1].value, "Vínculos por seller")
        self.assertEqual(len(app.dataframe[0].value), 5)
        app.selectbox[1].select("Sem telefone").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[-1].value, "1")
        self.assertTrue(app.button[0].disabled)

    def test_single_sheet_excel(self):
        app = self.page()
        content = workbook_bytes({"Sheet1": raw_directory()})
        app.file_uploader[0].upload("sellers.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet").run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(len(app.dataframe[0].value), 5)


if __name__ == "__main__":
    unittest.main()
