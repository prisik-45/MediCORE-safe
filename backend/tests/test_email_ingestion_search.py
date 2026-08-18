import unittest
from email.message import EmailMessage
from datetime import UTC, datetime
from types import SimpleNamespace

from backend.app.models import CatalogItem
from backend.app.schemas import ExtractedCatalogItem
from backend.app.services.catalog_table_parser import parse_catalog_table_text
from backend.app.services.country_detection import detect_supplier_country
from backend.app.services.document_classifier import CATALOGUE, CERTIFICATE, OTHER, classify_document
from backend.app.services.email_ingestion import (
    EmailIngestionService,
    filter_trusted_pending_approvals,
    public_processing_failure,
    trusted_sender_matches,
)
from backend.app.services.llm import TokenLimitReachedError
from backend.app.services.nl_query import NaturalLanguageQueryEngine
from backend.app.services.ranking import SupplierRanker


class EmailIngestionSearchCriteriaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = EmailIngestionService(db=SimpleNamespace())

    def test_approach_1_supplier_label_includes_seen_messages(self) -> None:
        account = SimpleNamespace(created_at=datetime(2026, 7, 17, tzinfo=UTC))

        args = self.service._imap_search_args_for_approach("approach_1", account)

        self.assertEqual(args, ("UNDELETED", "ALL"))
        self.assertNotIn("UNSEEN", args)
        self.assertIn("UNDELETED", args)

    def test_trusted_supplier_matches_exact_email_or_domain(self) -> None:
        trusted = "prisik.da45@gmail.com, example.com"

        self.assertTrue(trusted_sender_matches("Prince <PRISIK.DA45@gmail.com>", trusted))
        self.assertTrue(trusted_sender_matches("sales@example.com", trusted))
        self.assertFalse(trusted_sender_matches("other@gmail.com", trusted))

    def test_trusted_supplier_is_removed_from_pending_approvals(self) -> None:
        pending = (
            '[{"email_id":"1","sender":"princesikotra.05@gmail.com","ignored":false},'
            '{"email_id":"2","sender":"new@supplier.com","ignored":false}]'
        )

        cleaned = filter_trusted_pending_approvals(
            pending,
            "princesikotra.05@gmail.com",
        )

        self.assertNotIn("princesikotra.05@gmail.com", cleaned)
        self.assertIn("new@supplier.com", cleaned)

    def test_database_exception_is_never_stored_as_public_failure(self) -> None:
        public_message = public_processing_failure(
            'Failed: (psycopg.errors.InvalidSqlStatementName) prepared statement "_pg3_1" does not exist'
        )

        self.assertEqual(public_message, "email extraction could not be completed")
        self.assertNotIn("psycopg", public_message)

    def test_approach_2_new_to_system_is_not_based_on_seen_state(self) -> None:
        account = SimpleNamespace(created_at=datetime(2026, 7, 17, tzinfo=UTC))

        args = self.service._imap_search_args_for_approach("approach_2", account)

        self.assertEqual(args, ("UNDELETED", "SINCE", "17-Jul-2026"))
        self.assertNotIn("UNSEEN", args)
        self.assertIn("UNDELETED", args)

    def test_email_retry_status_rules_skip_success_but_retry_failed_and_partial(self) -> None:
        self.assertTrue(self.service._should_skip_logged_email("completed"))
        self.assertTrue(self.service._should_skip_logged_email("skipped: newsletter or promotional email"))
        self.assertTrue(self.service._should_skip_logged_email("deleted"))
        self.assertFalse(self.service._should_skip_logged_email("failed: OCR error"))
        self.assertFalse(self.service._should_skip_logged_email("partial"))

    def test_supplier_catalogue_intent_accepts_image_attachments(self) -> None:
        attachments = [{"filename": "supplier-catalogue.jpeg", "ext": ".jpeg"}]

        self.assertTrue(self.service._has_supplier_catalogue_intent("", "", attachments))

    def test_store_catalog_items_counts_duplicate_rows_in_same_document(self) -> None:
        added = []
        service = object.__new__(EmailIngestionService)
        service.db = SimpleNamespace(add=lambda item: added.append(item))
        service._existing_supplier_items_by_identity = lambda *args, **kwargs: {}
        catalog_email = SimpleNamespace(id="email-id", tenant_id="tenant-id", duplicate_count=0, received_at=datetime(2026, 8, 8, tzinfo=UTC))
        supplier = SimpleNamespace(id="supplier-id", tenant_id="tenant-id", email_domain="supplier.test")
        item = ExtractedCatalogItem(
            ingredient_name="Vitamin C",
            price_per_unit=5.0,
            currency="USD",
            available_qty=100.0,
            unit="kg",
            notes="source=Vitamin C 100 kg USD 5/kg",
        )

        stored = service._store_catalog_items(
            catalog_email,
            supplier,
            [item, item.model_copy()],
            "Vitamin C 100 kg USD 5/kg",
            tenant_id="tenant-id",
        )

        self.assertEqual(stored, 1)
        self.assertEqual(catalog_email.duplicate_count, 1)
        self.assertEqual(len(added), 1)

    def test_store_catalog_items_clears_price_without_price_evidence(self) -> None:
        added = []
        service = object.__new__(EmailIngestionService)
        service.db = SimpleNamespace(add=lambda item: added.append(item))
        service._existing_supplier_items_by_identity = lambda *args, **kwargs: {}
        catalog_email = SimpleNamespace(id="email-id", tenant_id="tenant-id", duplicate_count=0, received_at=datetime(2026, 8, 19, tzinfo=UTC))
        supplier = SimpleNamespace(id="supplier-id", tenant_id="tenant-id", email_domain="supplier.test")
        text = "RM | Volum (KG)\nBiotin (Chemical Substance) Biotin | 0.05"
        item = ExtractedCatalogItem(
            ingredient_name="Biotin",
            price_per_unit=0.05,
            currency="INR",
            available_qty=0.05,
            unit="kg",
            notes="source='Biotin (Chemical Substance) Biotin | 0.05'",
        )

        stored = service._store_catalog_items(
            catalog_email,
            supplier,
            [item],
            text,
            tenant_id="tenant-id",
        )

        self.assertEqual(stored, 1)
        self.assertIsNone(added[0].price_per_unit)
        self.assertEqual(added[0].currency, "")
        self.assertEqual(float(added[0].available_qty), 0.05)

    def test_email_body_preview_prefers_clean_plain_text_without_duplicate_html(self) -> None:
        message = EmailMessage()
        message["Subject"] = "LinkedIn update"
        plain = (
            "Bharath R shared a post: Can someone please refer me?\n"
            "Read more: https://www.linkedin.com/tracking/example\n"
            "Thanks,\nBharath\n"
        )
        html = (
            "<html><body><p>Bharath R shared a post: Can someone please refer me?</p>"
            "<a href='https://www.linkedin.com/tracking/example'>Read more</a>"
            "<script>track()</script></body></html>"
        )
        message.set_content(plain)
        message.add_alternative(html, subtype="html")

        body = self.service._get_email_body_text(message)
        preview = self.service._body_preview(body)

        self.assertEqual(body, "Bharath R shared a post: Can someone please refer me?")
        self.assertEqual(preview, "Bharath R shared a post: Can someone please refer me?")

    def test_email_body_cleaning_keeps_thank_you_offer_content_before_signature(self) -> None:
        body = self.service._clean_email_body(
            "Dear Mr.Karim,\n\n"
            "Thank you for your interest in our L-Carnitine.\n\n"
            "Please find our offer below:\n\n"
            "Price: USD22.7/kg CIF by sea\n\n"
            "The COA is attached for your reference.\n"
            "Best regards,\nSupplier\n"
        )

        self.assertIn("Thank you for your interest in our L-Carnitine.", body)
        self.assertIn("Price: USD22.7/kg CIF by sea", body)
        self.assertNotIn("Best regards", body)

    def test_item_identity_uses_ingredient_and_specification_only(self) -> None:
        previous = SimpleNamespace(
            ingredient_name="Ashwagandha Extract",
            price_per_unit=20,
            currency="USD",
            available_qty=25,
            unit="kg",
            lead_time_days=None,
            moq=10,
            raw_payload={"specification": "KSM-66"},
        )
        updated = ExtractedCatalogItem(
            ingredient_name="Ashwagandha Extract",
            specification="KSM-66",
            price_per_unit=18,
            currency="USD",
            available_qty=100,
            unit="kg",
            moq=25,
            notes="source='Updated Price: Ashwagandha Extract KSM-66 $18/kg'",
        )

        self.assertEqual(self.service._item_identity_key(previous), self.service._item_identity_key(updated))
        self.assertTrue(self.service._catalog_item_values_changed(previous, updated))

    def test_commercial_reply_update_extracts_price_moq_and_lead_time(self) -> None:
        updates = self.service._commercial_updates_from_text(
            "Updated Price: $18/kg\nMOQ: 25 kg\nLead Time: 14 days"
        )

        self.assertEqual(updates["price_per_unit"], 18.0)
        self.assertEqual(updates["currency"], "USD")
        self.assertEqual(updates["moq"], 25.0)
        self.assertEqual(updates["lead_time_days"], 14)

    def test_commercial_reply_update_extracts_inline_usd_cif_price(self) -> None:
        updates = self.service._commercial_updates_from_text(
            "Please find our offer below:\n\nPrice: USD22.7/kg CIF by sea\n\nThe COA is attached."
        )

        self.assertEqual(updates["price_per_unit"], 22.7)
        self.assertEqual(updates["currency"], "USD")

    def test_thread_reply_update_matches_recent_supplier_item_mentioned_in_body(self) -> None:
        tenant_id = "tenant-id"
        supplier = SimpleNamespace(id="supplier-id", email_domain="supplier.example")
        previous_item = SimpleNamespace(
            id="item-id",
            tenant_id=tenant_id,
            supplier_id=supplier.id,
            catalog_email_id="previous-email-id",
            ingredient_name="L-Carnitine",
            price_per_unit=25.0,
            currency="USD",
            moq=None,
            lead_time_days=None,
            raw_payload={},
        )
        catalog_email = SimpleNamespace(
            id="current-email-id",
            tenant_id=tenant_id,
            supplier_id=supplier.id,
            subject="Offer",
            raw_email_id="email-id",
            received_at=datetime(2026, 8, 9, tzinfo=UTC),
        )

        class FakeQuery:
            def __init__(self, *models):
                self.models = models

            def join(self, *args, **kwargs):
                return self

            def filter(self, *args, **kwargs):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def limit(self, *args, **kwargs):
                return self

            def all(self):
                if self.models and self.models[0] is CatalogItem:
                    return [previous_item]
                return []

        service = object.__new__(EmailIngestionService)
        service.db = SimpleNamespace(query=lambda *models: FakeQuery(*models), add=lambda item: None)

        updated = service._apply_thread_reply_update(
            catalog_email,
            supplier,
            "Thank you for your interest in our L-Carnitine.\nPrice: USD22.7/kg CIF by sea",
            tenant_id,
        )

        self.assertEqual(updated, 1)
        self.assertEqual(previous_item.price_per_unit, 22.7)
        self.assertEqual(previous_item.catalog_email_id, "current-email-id")
        self.assertTrue(previous_item.raw_payload["conversation_update"])

    def test_parser_preserves_lead_time_range_text(self) -> None:
        rows = parse_catalog_table_text(
            "Product | Qty | Unit | Price | Currency | Lead\n"
            "Citric Acid | 3.88 | kg | 12.75 | USD | 40-50 days\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].lead_time_days)
        self.assertEqual(rows[0].lead_time_text, "40-50 days")
        self.assertEqual(rows[0].available_qty, 3.88)

    def test_structured_parser_rows_do_not_block_llm_unstructured_rows(self) -> None:
        service = object.__new__(EmailIngestionService)
        service.llm = SimpleNamespace(
            extract_catalog_items=lambda text, reference_date=None: [
                ExtractedCatalogItem(
                    ingredient_name="Aspirin USP",
                    price_per_unit=9.25,
                    currency="USD",
                    available_qty=7.5,
                    unit="kg",
                    notes="source='Aspirin USP stock 7.5 kg price USD 9.25/kg'",
                )
            ]
        )

        rows = service._extract_items_from_text(
            "Product | Qty | Unit | Price | Currency | Lead\n"
            "Citric Acid | 3.88 | kg | 12.75 | USD | 40-50 days\n"
            "Aspirin USP stock 7.5 kg price USD 9.25/kg\n",
            "catalog.pdf",
            reference_date=datetime(2026, 7, 17, tzinfo=UTC),
        )

        names = {row.ingredient_name.lower() for row in rows}
        self.assertIn("citric acid", names)
        self.assertIn("aspirin usp", names)

    def test_parser_keeps_rows_with_na_price_as_incomplete_items(self) -> None:
        rows = parse_catalog_table_text(
            "Product | Qty | Unit | Price | Currency | Lead\n"
            "Sodium Chloride | 399.42 | kg | NA | USD |\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ingredient_name, "Sodium Chloride")
        self.assertIsNone(rows[0].price_per_unit)
        self.assertEqual(rows[0].available_qty, 399.42)
        self.assertEqual(rows[0].unit, "kg")

    def test_parser_preserves_currency_and_quantity_unit_from_cells(self) -> None:
        rows = parse_catalog_table_text(
            "Product | Quantity | Price\n"
            "Vitamin C | 8400 kg | INR 99.02\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].price_per_unit, 99.02)
        self.assertEqual(rows[0].currency, "INR")
        self.assertEqual(rows[0].available_qty, 8400.0)
        self.assertEqual(rows[0].unit, "kg")
        self.assertIn("original_price=INR 99.02", rows[0].notes or "")
        self.assertIn("original_quantity=8400 kg", rows[0].notes or "")

    def test_vertical_product_code_catalog_extracts_rows_and_usd_fob_price(self) -> None:
        rows = parse_catalog_table_text(
            "Jinrui Product Code\n"
            "Product Name\n"
            "Product Specification Description\n"
            "FOB($/kg)\n"
            "JRG1287-A319\n"
            "3,3'-Diindolylmethane\n"
            "Assay: >=99.0%\n"
            "30\n"
            "JRG1291-A322\n"
            "5-Amino-1-methylquinolinium Chloride\n"
            "Purity: >=98.0%\n"
            "1477\n"
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].ingredient_name, "3,3'-Diindolylmethane")
        self.assertEqual(rows[0].price_per_unit, 30.0)
        self.assertEqual(rows[0].currency, "USD")
        self.assertEqual(rows[0].unit, "kg")
        self.assertIn("supplier_sku=JRG1287-A319", rows[0].notes or "")
        self.assertEqual(rows[0].specification, "Assay: >=99.0%")
        self.assertIn("original_price=$30/kg", rows[0].notes or "")

    def test_pdf_table_header_fob_usd_per_kg_maps_numeric_column_to_price(self) -> None:
        rows = parse_catalog_table_text(
            "Jinrui Product Code | Product Name | Product Specification Description | FOB($/kg)\n"
            "JRG1287-A319 | 3,3'-Diindolylmethane | Assay: ≥99.0% | 30\n"
            "JRG1291-A322 | 5-Amino-1-methylquinolinium Chloride | Purity: ≥98.0% | 1477\n"
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].ingredient_name, "3,3'-Diindolylmethane")
        self.assertEqual(rows[0].specification, "Assay: ≥99.0%")
        self.assertEqual(rows[0].price_per_unit, 30.0)
        self.assertEqual(rows[0].currency, "USD")
        self.assertEqual(rows[0].unit, "kg")
        self.assertIn("original_price=$30/kg", rows[0].notes or "")
        self.assertEqual(rows[1].price_per_unit, 1477.0)
        self.assertIn("original_price=$1477/kg", rows[1].notes or "")

    def test_adaptive_headers_extract_qty_moq_and_lead_time_units(self) -> None:
        rows = parse_catalog_table_text(
            "Material | Grade / Assay | Offer Qty (KG) | Min Order (KG) | Dispatch Time (Days) | CIF USD/kg\n"
            "Vitamin C | USP 99% | 8400 | 25 | 14 | 5\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ingredient_name, "Vitamin C")
        self.assertEqual(rows[0].specification, "USP 99%")
        self.assertEqual(rows[0].available_qty, 8400.0)
        self.assertEqual(rows[0].unit, "kg")
        self.assertEqual(rows[0].moq, 25.0)
        self.assertEqual(rows[0].lead_time_days, 14)
        self.assertEqual(rows[0].lead_time_text, "14 days")
        self.assertEqual(rows[0].price_per_unit, 5.0)
        self.assertEqual(rows[0].currency, "USD")
        self.assertIn("original_price=$5/kg", rows[0].notes or "")

    def test_post_table_statement_is_not_appended_to_last_price_cell(self) -> None:
        rows = parse_catalog_table_text(
            "Jinrui Product Code | Product Name | Product Specification Description | FOB($/kg)\n"
            "JRG0771-F146 | β-Carotene | β-Carotene: ≥10.0%, Complies with USP standards | "
            "43 Statement: This quotation is provided for informational and reference purposes only.\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ingredient_name, "β-Carotene")
        self.assertEqual(rows[0].specification, "β-Carotene: ≥10.0%, Complies with USP standards")
        self.assertEqual(rows[0].price_per_unit, 43.0)
        self.assertEqual(rows[0].currency, "USD")
        self.assertEqual(rows[0].unit, "kg")
        self.assertIn("original_price=$43/kg", rows[0].notes or "")
        self.assertNotIn("Statement", rows[0].notes or "")

    def test_email_body_price_update_sentence_extracts_catalogue_item(self) -> None:
        rows = parse_catalog_table_text(
            "hi abhishek,\n\n"
            "the price of Zinc Sulfate is updated to $6/kg.\n\n"
            "thanks,\nPrince\n"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ingredient_name, "Zinc Sulfate")
        self.assertEqual(rows[0].price_per_unit, 6.0)
        self.assertEqual(rows[0].currency, "USD")
        self.assertEqual(rows[0].unit, "kg")
        self.assertIn("original_price=$6/kg", rows[0].notes or "")

    def test_email_body_direct_price_sentence_extracts_catalogue_item_with_moq(self) -> None:
        rows = parse_catalog_table_text(
            "Price of Ashwagandha 20% Content is $60/kg with MOQ 20kg"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].ingredient_name, "Ashwagandha")
        self.assertEqual(rows[0].specification, "20% Content")
        self.assertEqual(rows[0].price_per_unit, 60.0)
        self.assertEqual(rows[0].currency, "USD")
        self.assertEqual(rows[0].unit, "kg")
        self.assertEqual(rows[0].moq, 20.0)

    def test_product_code_column_is_not_mapped_as_ingredient_name(self) -> None:
        rows = parse_catalog_table_text(
            "Product Code | Product Name | Specification | Price\n"
            "JRG1291-A322 | 5-Amino-1-methylquinolinium Chloride | Purity >=98.0% | 1477\n"
            "JRG0436-A32 | 3,3'-Diindolylmethane | Assay >=99.0% | 30\n"
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].ingredient_name, "5-Amino-1-methylquinolinium Chloride")
        self.assertEqual(rows[0].specification, "Purity >=98.0%")
        self.assertEqual(rows[0].price_per_unit, 1477.0)
        self.assertEqual(rows[1].ingredient_name, "3,3'-Diindolylmethane")
        self.assertNotIn("JRG1291-A322", [row.ingredient_name for row in rows])

    def test_code_only_or_spec_only_rows_are_skipped(self) -> None:
        rows = parse_catalog_table_text(
            "Product Code | Specification | Price | MOQ\n"
            "JRG1291-A322 | Purity >=98.0% | 1477 | 1 kg\n"
        )

        self.assertEqual(rows, [])

    def test_country_label_is_never_accepted_as_a_catalogue_ingredient(self) -> None:
        rows = parse_catalog_table_text(
            "Product | Price | Quantity\n"
            "Canada | 12 | 100 kg\n"
            "Citric Acid | 12 | 100 kg\n"
        )

        self.assertEqual([row.ingredient_name for row in rows], ["Citric Acid"])

    def test_unverified_llm_item_is_not_given_fake_source_provenance(self) -> None:
        service = object.__new__(EmailIngestionService)
        item = ExtractedCatalogItem(
            ingredient_name="Citric Acid",
            price_per_unit=12,
            currency="USD",
            notes="original_price=USD 12",
        )

        ungrounded = service._with_source_note(item, "Supplier address: Toronto, Canada")

        self.assertNotIn("source=", ungrounded.notes or "")
        self.assertFalse(service._has_required_grounded_values(ungrounded))

    def test_generic_table_extracts_specification_column_and_keeps_variants(self) -> None:
        rows = parse_catalog_table_text(
            "No | Product | Specification | Quantity\n"
            "04 | Berberine | 97% Powder | 5,700KG\n"
            "05 | Berberine | Berberine Extract 20:1 | 1,850KG\n"
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].ingredient_name, "Berberine")
        self.assertEqual(rows[0].specification, "97% Powder")
        self.assertEqual(rows[0].available_qty, 5700.0)
        self.assertEqual(rows[0].unit, "kg")
        self.assertEqual(rows[1].specification, "Berberine Extract 20:1")

    def test_numbered_ocr_rows_keep_specification_and_quantity_aligned(self) -> None:
        rows = parse_catalog_table_text(
            "19 Ginger Powder Pb0.3-0.8 ppm 7,500KG\n"
            "20 Ginger Extract Powder 1% HPLC 1,550KG\n"
            "21 Ginger Extract Powder 5% HPLC 5,000KG\n"
        )

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].ingredient_name, "Ginger Powder")
        self.assertEqual(rows[0].specification, "Pb0.3-0.8 ppm")
        self.assertEqual(rows[0].available_qty, 7500.0)
        self.assertIsNone(rows[0].price_per_unit)
        self.assertEqual(rows[1].ingredient_name, "Ginger Extract Powder")
        self.assertEqual(rows[1].specification, "1% HPLC")
        self.assertEqual(rows[2].specification, "5% HPLC")

    def test_numbered_rows_keep_parenthetical_product_and_multiline_specification(self) -> None:
        rows = parse_catalog_table_text(
            "12 Bilberry Fruit Extract ( Europe ) Anthocyanins 36% HPLC Anthocyanidins 25%UV 300KG\n"
            "13 Bilberry Fruit Extract ( Europe ) Anthocyanins 25% HPLC Anthocyanidins18%UV 500KG\n"
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].ingredient_name, "Bilberry Fruit Extract ( Europe )")
        self.assertEqual(rows[0].specification, "Anthocyanins 36% HPLC Anthocyanidins 25%UV")
        self.assertEqual(rows[0].available_qty, 300.0)
        self.assertEqual(rows[1].specification, "Anthocyanins 25% HPLC Anthocyanidins18%UV")

    def test_specification_preserves_numbers_and_special_characters(self) -> None:
        rows = parse_catalog_table_text(
            "14 Ferrous Bisglycinate Fe2+: 20.0%-23.7%, Nitrogen: 10.0%-12.0% 14KG\n"
            "15 Berberine Extract 10:1 >=98.5% (HPLC) 2,000KG\n"
        )

        self.assertEqual(rows[0].ingredient_name, "Ferrous Bisglycinate")
        self.assertEqual(rows[0].specification, "Fe2+: 20.0%-23.7%, Nitrogen: 10.0%-12.0%")
        self.assertEqual(rows[1].ingredient_name, "Berberine Extract")
        self.assertEqual(rows[1].specification, "10:1 >=98.5% (HPLC)")

    def test_supplier_identity_uses_full_sender_email(self) -> None:
        from backend.app.services.email_ingestion import get_supplier_domain

        self.assertEqual(get_supplier_domain("sales@alpha.com"), "sales@alpha.com")
        self.assertEqual(get_supplier_domain("pricing@alpha.com"), "pricing@alpha.com")

    def test_display_payload_adds_unit_when_quantity_cell_is_numeric_only(self) -> None:
        service = object.__new__(EmailIngestionService)
        item = ExtractedCatalogItem(
            ingredient_name="Sea Moss Powder",
            price_per_unit=11.0,
            currency="USD",
            available_qty=446.02,
            unit="kg",
            notes="original_quantity=446.02; original_price=CIF Vancouver $11.00/kg",
        )

        payload = service._exact_display_payload(item, "Sea Moss Powder | 446.02 | kg | CIF Vancouver $11.00/kg")

        self.assertEqual(payload["quantity_display"], "446.02 kg")
        self.assertEqual(payload["price_display"], "CIF Vancouver $11.00/kg")

    def test_display_payload_preserves_inline_currency_unit_and_terms(self) -> None:
        service = object.__new__(EmailIngestionService)
        item = ExtractedCatalogItem(
            ingredient_name="Biotin",
            price_per_unit=31.0,
            currency="USD",
            available_qty=125.0,
            unit="kg",
            notes="source='We offer Biotin at USD 31/kg (DAP) for a quantity of 125 kg.'",
        )

        payload = service._exact_display_payload(
            item,
            "We are pleased to offer the price of Biotin at USD 31/kg (DAP) for a quantity of 125 kg.",
        )

        self.assertEqual(payload["price_display"], "USD 31/kg (DAP)")
        self.assertEqual(payload["quantity_display"], "125 kg")

    def test_assistant_replaces_false_negative_when_rows_exist(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        self.assertTrue(engine._looks_like_false_negative("I couldn't find any matching data for Nicotinamide."))
        summary = engine._fallback_summary(
            "find supplier for Nicotinamide",
            [
                {
                    "supplier_name": "Prince Sikotra",
                    "ingredient_name": "Nicotinamide (Vitamin B3)",
                    "price_per_unit": 10.5,
                    "price_display": "CIF Vancouver $10.50/kg",
                    "currency": "USD",
                    "available_qty": 9.99,
                    "quantity_display": "9.99 kg",
                    "unit": "kg",
                    "is_updated": True,
                }
            ],
        )

        self.assertIn("nicotinamide (vitamin b3) (u)", summary.lower())
        self.assertIn("Prince Sikotra", summary)

    def test_procuraai_summary_context_does_not_expose_scores(self) -> None:
        from backend.app.services.llm import OpenRouterClient

        client = object.__new__(OpenRouterClient)
        captured = {}

        def fake_chat(*, messages, temperature=0, json_mode=False):
            captured["messages"] = messages
            return "Prince Sikotra has the best available catalogue price for Biotin."

        client._chat = fake_chat

        answer = client.summarize_answer(
            "find supplier for biotin",
            [
                {
                    "supplier_name": "Prince Sikotra",
                    "ingredient_name": "Biotin",
                    "price_per_unit": 31.0,
                    "price_display": "USD 31/kg (DAP)",
                    "currency": "USD",
                    "available_qty": 125.0,
                    "quantity_display": "125 kg",
                    "unit": "kg",
                    "recommendation_score": 99.95,
                    "is_updated": True,
                }
            ],
        )

        serialized_prompt = str(captured["messages"])
        self.assertEqual(answer, "Prince Sikotra has the best available catalogue price for Biotin.")
        self.assertIn("Biotin (U)", serialized_prompt)
        self.assertNotIn("99.95", serialized_prompt)
        self.assertNotIn("recommendation_score", serialized_prompt)

    def test_ranker_dedupes_same_supplier_requested_item_updates(self) -> None:
        ranker = object.__new__(SupplierRanker)
        rows = ranker._dedupe_supplier_item_rows(
            [
                {
                    "supplier_name": "Prince Sikotra",
                    "email_domain": "prisik.da45@gmail.com",
                    "ingredient_name": "Biotin",
                    "specification": "",
                    "price_display": "$5/kg",
                    "quantity_display": "125 kg",
                    "available_qty": 125.0,
                    "unit": "kg",
                    "received_at": "2026-07-22T10:00:00+00:00",
                    "is_updated": False,
                },
                {
                    "supplier_name": "Prince Sikotra",
                    "email_domain": "prisik.da45@gmail.com",
                    "ingredient_name": "Biotin",
                    "specification": "",
                    "price_display": "$31.00/kg",
                    "quantity_display": "125 kg",
                    "available_qty": 125.0,
                    "unit": "kg",
                    "received_at": "2026-07-22T10:00:00+00:00",
                    "is_updated": True,
                },
            ],
            "biotin",
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_display"], "$31.00/kg")
        self.assertTrue(rows[0]["is_updated"])

    def test_ranker_keeps_same_item_with_different_specification_as_distinct_rows(self) -> None:
        ranker = object.__new__(SupplierRanker)
        rows = ranker._dedupe_supplier_item_rows(
            [
                {
                    "supplier_name": "Prince Sikotra",
                    "email_domain": "prisik.da45@gmail.com",
                    "ingredient_name": "Berberine",
                    "specification": "97% Powder",
                    "quantity_display": "5,700 kg",
                    "available_qty": 5700.0,
                    "unit": "kg",
                },
                {
                    "supplier_name": "Prince Sikotra",
                    "email_domain": "prisik.da45@gmail.com",
                    "ingredient_name": "Berberine",
                    "specification": "Berberine Extract 20:1",
                    "quantity_display": "1,850 kg",
                    "available_qty": 1850.0,
                    "unit": "kg",
                },
            ],
            "berberine",
        )

        self.assertEqual(len(rows), 2)

    def test_ranker_relevance_returns_all_partial_ingredient_variants(self) -> None:
        ranker = object.__new__(SupplierRanker)
        rows = [
            {"ingredient_name": "Marigold Extract Zeaxanthin 5% Powder (HPLC)", "price_per_unit": 11},
            {"ingredient_name": "Ginger Extract Powder", "price_per_unit": 8},
            {"ingredient_name": "Marigold Extract Lutein 20% Oil (HPLC)", "price_per_unit": 10},
            {"ingredient_name": "Marigold Extract Meso-Zeaxanthin 20% Oil (HPLC)", "price_per_unit": 12},
        ]

        ranked = ranker._rank_rows_by_relevance(rows, "marigold")
        matched = [row for row in ranked if ranker._row_relevance_score(row, "marigold") >= 300]

        self.assertEqual(len(matched), 3)
        self.assertTrue(all("Marigold" in row["ingredient_name"] for row in matched))

    def test_ranker_relevance_ignores_punctuation_for_multi_word_search(self) -> None:
        ranker = object.__new__(SupplierRanker)
        row = {"ingredient_name": "Vitamin D3 Powder (Lichen) 100,000 IU/g"}

        self.assertGreater(ranker._row_relevance_score(row, "vitamin d3"), 0)
        self.assertGreater(ranker._row_relevance_score(row, "Vitamin-D3"), 0)
        self.assertGreater(ranker._row_relevance_score(row, " vitamin   d3 "), 0)

    def test_query_engine_dedupes_rows_after_execution_before_summary(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)
        engine.cache = SimpleNamespace(get=lambda key: None, setex=lambda *args, **kwargs: None)
        engine.llm = SimpleNamespace(
            plan_query=lambda question: SimpleNamespace(operation="catalog_search", ingredient_name="biotin", min_quantity=None, unit=None, limit=10),
            summarize_answer=lambda question, rows: f"{len(rows)} row(s)",
        )
        engine.ranker = object.__new__(SupplierRanker)
        engine._log_query = lambda *args, **kwargs: None
        engine._ground_plan_in_catalog = lambda question, plan, tenant_id=None: plan
        engine._execute_plan = lambda plan, tenant_id=None: [
            {
                "supplier_name": "Prince Sikotra",
                "email_domain": "prisik.da45@gmail.com",
                "ingredient_name": "Biotin",
                "specification": "",
                "price_display": "$5/kg",
                "quantity_display": "125 kg",
                "available_qty": 125.0,
                "unit": "kg",
                "received_at": "2026-07-22T10:00:00+00:00",
                "is_updated": False,
            },
            {
                "supplier_name": "Prince Sikotra",
                "email_domain": "prisik.da45@gmail.com",
                "ingredient_name": "Biotin",
                "specification": "",
                "price_display": "$31.00/kg",
                "quantity_display": "125 kg",
                "available_qty": 125.0,
                "unit": "kg",
                "received_at": "2026-07-22T10:00:00+00:00",
                "is_updated": True,
            },
        ]

        response = engine.answer("price of biotin")

        self.assertEqual(response.answer, "1 row(s)")
        self.assertEqual(len(response.rows), 1)
        self.assertEqual(response.rows[0]["price_display"], "$31.00/kg")

    def test_query_engine_normalizes_sql_email_date_alias(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)
        engine.db = SimpleNamespace()

        rows = engine._normalize_sql_rows(
            [
                {
                    "supplier_name": "Prince Sikotra",
                    "ingredient_name": "Marigold Extract Lutein 10% Powder (HPLC)",
                    "available_qty": 500,
                    "unit": "kg",
                    "email_date": datetime(2026, 7, 22, 10, 30, tzinfo=UTC),
                }
            ]
        )

        self.assertEqual(rows[0]["received_at"], "2026-07-22T10:30:00+00:00")
        self.assertEqual(rows[0]["quantity_display"], "500.0 kg")

    def test_query_engine_matches_misspelled_ingredient_before_querying(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        matched = engine._best_ingredient_result_from_candidates(
            "aswahgandha supplier name",
            [
                "5-Amino-1-methylquinolinium Chloride",
                "Zinc Gluconate",
                "Ashwagandha Extract 12:1",
                "Organic Ashwagandha Powder",
                "Magnesium Citrate",
            ],
        )

        self.assertEqual(matched.search_phrase, "ashwagandha")
        self.assertIn("Ashwagandha Extract 12:1", matched.matched_names)
        self.assertIn("Organic Ashwagandha Powder", matched.matched_names)
        self.assertNotIn("5-Amino-1-methylquinolinium Chloride", matched.matched_names)

    def test_query_engine_matches_partial_ingredient_phrase(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        matched = engine._best_ingredient_result_from_candidates(
            "ginger price",
            [
                "Ginger Powder",
                "Ginger Extract",
                "Organic Ginger Root Powder",
                "Magnesium Citrate",
            ],
        )

        self.assertEqual(matched.search_phrase, "ginger")
        self.assertEqual(
            set(matched.matched_names),
            {"Ginger Powder", "Ginger Extract", "Organic Ginger Root Powder"},
        )

    def test_query_engine_prefers_an_exact_catalogue_chemical_name(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        matched = engine._best_ingredient_result_from_candidates(
            "Show supplier prices for Citric Acid",
            [
                "Citric Acid",
                "Citric Acid Anhydrous",
                "Citric Acid Monohydrate",
                "Sodium Citrate",
            ],
        )

        self.assertEqual(matched.search_phrase, "Citric Acid")
        self.assertEqual(matched.matched_names, ["Citric Acid"])
        self.assertEqual(matched.confidence, 1.0)

    def test_query_engine_expands_common_ingredient_abbreviations(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        matched = engine._best_ingredient_result_from_candidates(
            "vit d3",
            [
                "Vitamin D3 Powder (Lichen)",
                "Vitamin D3 100,000 IU/g",
                "Vitamin B12",
            ],
        )

        self.assertEqual(matched.search_phrase, "vitamin d3")
        self.assertEqual(
            set(matched.matched_names),
            {"Vitamin D3 Powder (Lichen)", "Vitamin D3 100,000 IU/g"},
        )

    def test_query_engine_normalizes_common_typos_and_partial_entities(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        citrus = engine._best_ingredient_result_from_candidates(
            "who sells citrous",
            ["Citrus Bioflavonoids", "Citric Acid", "Ashwagandha Extract"],
        )
        zinc = engine._best_ingredient_result_from_candidates(
            "zinc 12 supplier",
            ["Zinc Gluconate 12%", "Zinc Oxide", "Magnesium Citrate"],
        )
        vitamin_c = engine._best_ingredient_result_from_candidates(
            "best supplier for vit c",
            ["Ascorbic Acid", "Vitamin D3 Powder", "Citric Acid"],
        )

        self.assertEqual(citrus.search_phrase, "citrus")
        self.assertIn("Citrus Bioflavonoids", citrus.matched_names)
        self.assertEqual(zinc.search_phrase, "Zinc Gluconate 12%")
        self.assertIn("Zinc Gluconate 12%", zinc.matched_names)
        self.assertIn(vitamin_c.search_phrase, {"ascorbic", "ascorbic acid", "vitamin c"})
        self.assertIn("Ascorbic Acid", vitamin_c.matched_names)

    def test_query_understanding_does_not_force_item_for_general_procurement_question(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        understood = engine._understand_query("Supplier from Germany")

        self.assertEqual(understood.intent, "country_origin")
        self.assertFalse(understood.requires_item)
        self.assertTrue(understood.needs_database)
        self.assertEqual(understood.filters["country"], "Germany")

    def test_query_understanding_extracts_entity_before_filters(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        price_query = engine._understand_query("Citrus available at what price in 2025")
        related_query = engine._understand_query("List all citrus related items")
        supplier_query = engine._understand_query("Cheapest citrus supplier")

        self.assertEqual(price_query.intent, "price_lookup")
        self.assertEqual(price_query.entity_phrase, "citrus")
        self.assertEqual(related_query.intent, "product_search")
        self.assertEqual(related_query.entity_phrase, "citrus")
        self.assertEqual(supplier_query.intent, "price_lookup")
        self.assertEqual(supplier_query.operation, "best_price")
        self.assertEqual(supplier_query.entity_phrase, "citrus")

    def test_query_understanding_supports_no_item_supplier_filters(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        india = engine._understand_query("is there any supplier from india")
        moq = engine._understand_query("best supplier with MOQ below 100")
        certificate = engine._understand_query("show suppliers with certificate")
        updates = engine._understand_query("which supplier updated prices today")
        lead_time = engine._understand_query("which supplier has lowest lead time")
        supplier_compare = engine._understand_query("compare Prince Sikotra and CSN")

        self.assertEqual(india.intent, "country_origin")
        self.assertFalse(india.requires_item)
        self.assertTrue(india.needs_database)
        self.assertEqual(india.entity_phrase, "")
        self.assertEqual(india.filters["country"], "India")
        self.assertEqual(moq.intent, "moq")
        self.assertFalse(moq.requires_item)
        self.assertEqual(moq.filters["max_moq"], 100.0)
        self.assertEqual(certificate.intent, "certifications")
        self.assertFalse(certificate.requires_item)
        self.assertTrue(certificate.filters["has_certificate"])
        self.assertEqual(updates.intent, "updates")
        self.assertFalse(updates.requires_item)
        self.assertTrue(updates.filters["updated_only"])
        self.assertEqual(updates.entity_phrase, "")
        self.assertEqual(lead_time.intent, "lead_time")
        self.assertFalse(lead_time.requires_item)
        self.assertEqual(lead_time.filters["rank_by"], "lead_time")
        self.assertEqual(supplier_compare.intent, "compare_suppliers")
        self.assertFalse(supplier_compare.requires_item)
        self.assertEqual(supplier_compare.filters["supplier_names"], ["Prince Sikotra", "CSN"])

    def test_query_normalization_preserves_spec_ratio_for_joined_terms(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        self.assertEqual(engine._extract_ingredient_phrase("ashwagandha12 supplier"), "ashwagandha 12 1")

    def test_query_engine_offers_possible_matches_for_low_confidence_ingredient(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        matched = engine._best_ingredient_result_from_candidates(
            "ashwgnd supplier",
            ["Ashwagandha Extract", "Amla Extract", "Citrus Extract"],
        )
        answer = engine._ingredient_clarification_answer("ashwgnd", matched)

        self.assertIsNone(matched.search_phrase)
        self.assertIn("possible matches", answer)

    def test_query_engine_answers_current_item_from_memory_without_database(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)
        engine.conversation_state = {"last_search_phrase": "citrus"}
        engine._log_query = lambda *args, **kwargs: None

        response = engine.answer("Which item did I ask?")

        self.assertEqual(response.answer, "You asked about citrus.")
        self.assertEqual(response.rows, [])

    def test_query_engine_rejects_unrelated_weak_ingredient_match(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)

        matched = engine._best_ingredient_result_from_candidates(
            "give me supplier of ashwangandha",
            [
                "5-Amino-1-methylquinolinium Chloride",
                "Zinc Gluconate",
                "Magnesium Citrate",
            ],
        )

        self.assertIsNone(matched.search_phrase)
        self.assertEqual(matched.matched_names, [])

    def test_supplier_country_detection_normalizes_usa_address(self) -> None:
        country = detect_supplier_country(
            "USA Warehouse & Office\n"
            "Herbal Creations USA\n"
            "Ontario, CA 91761\n"
            "United States"
        )

        self.assertEqual(country, "United States")

    def test_supplier_country_detection_handles_city_country_signature(self) -> None:
        self.assertEqual(detect_supplier_country("Sales Team\nShanghai, China\nTel: 021-5555"), "China")
        self.assertEqual(detect_supplier_country("Regards\nAhmedabad, Gujarat, India"), "India")

    def test_supplier_country_prefers_registered_footer_address(self) -> None:
        self.assertEqual(
            detect_supplier_country(
                "Ship to: Newark, New Jersey, United States\n"
                "Product catalogue\n"
                "Registered office: 88 Nanhai Road, Shenzhen, Guangdong, China\n"
                "Tel: +86 755 5555"
            ),
            "China",
        )

    def test_general_chat_uses_personal_assistant_without_catalogue_rows(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)
        engine.llm = SimpleNamespace(personal_assistant_answer=lambda question: "Set a reminder for 3 PM.")
        engine._log_query = lambda *args, **kwargs: None

        response = engine.answer("Remind me at 3 PM")

        self.assertEqual(response.answer, "Set a reminder for 3 PM.")
        self.assertEqual(response.rows, [])

    def test_procuraai_returns_exact_token_limit_message(self) -> None:
        engine = object.__new__(NaturalLanguageQueryEngine)
        engine._understand_query = lambda question: (_ for _ in ()).throw(TokenLimitReachedError("quota exhausted"))

        response = engine._answer("compare suppliers")

        self.assertEqual(response.answer, "Token Limit Reached")
        self.assertEqual(response.rows, [])

    def test_supplier_country_detection_defaults_unknown_without_address(self) -> None:
        self.assertEqual(detect_supplier_country("New catalogue attached. Best prices this month."), "Unknown")

    def test_certificate_pdf_detection_uses_filename_and_text(self) -> None:
        service = EmailIngestionService(db=SimpleNamespace())

        self.assertTrue(service._is_certificate_pdf("Vitamin-D3-COA.pdf", ".pdf", "Certificate of Analysis"))
        self.assertTrue(service._is_certificate_pdf("supplier-quality.pdf", ".pdf", "ISO 9001 Certificate"))
        self.assertFalse(service._is_certificate_pdf("July catalogue.pdf", ".pdf", "price list inventory"))
        self.assertTrue(service._is_certificate_pdf("COA.docx", ".docx", "Certificate of Analysis"))

    def test_certificate_refs_are_deduped_and_keep_storage_path(self) -> None:
        service = EmailIngestionService(db=SimpleNamespace())

        refs = service._dedupe_certificate_refs(
            [
                {"name": "COA.pdf", "url": "https://storage/coa.pdf", "storage_path": "email/COA.pdf", "type": "COA"},
                {"name": "COA copy.pdf", "url": "https://storage/coa.pdf", "storage_path": "email/COA.pdf", "type": "COA"},
            ]
        )

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["storage_path"], "email/COA.pdf")

    def test_certificate_refs_merge_into_item_payload_without_binary(self) -> None:
        service = EmailIngestionService(db=SimpleNamespace(add=lambda item: None))
        item = SimpleNamespace(raw_payload={"source": "email_extracted_catalogue"})

        service._merge_item_certificate_refs(
            item,
            [{"name": "COA.pdf", "url": "https://storage/coa.pdf", "storage_path": "email/COA.pdf", "type": "COA"}],
        )

        self.assertEqual(item.raw_payload["certificate_pdfs"][0]["url"], "https://storage/coa.pdf")
        self.assertNotIn("payload", item.raw_payload["certificate_pdfs"][0])

    def test_certificate_refs_attach_to_items_when_product_match_is_weak(self) -> None:
        item = SimpleNamespace(
            raw_payload={"source": "email_extracted_catalogue"},
            ingredient_name="Ashwagandha Extract 5% Withanolides",
        )
        query = SimpleNamespace(
            filter=lambda *args, **kwargs: SimpleNamespace(all=lambda: [item])
        )
        db = SimpleNamespace(query=lambda model: query, add=lambda item: None)
        service = EmailIngestionService(db=db)

        service._attach_certificate_refs(
            SimpleNamespace(id="email-id", tenant_id="tenant-id"),
            SimpleNamespace(id="supplier-id"),
            [{"name": "Ashwagandha-Certi.pdf", "url": "https://storage/cert.pdf", "type": "Certificate"}],
        )

        self.assertEqual(item.raw_payload["certificate_pdfs"][0]["name"], "Ashwagandha-Certi.pdf")

    def test_document_classifier_separates_catalogue_certificate_and_other(self) -> None:
        catalogue = classify_document(
            "August price list.pdf",
            ".pdf",
            "Ingredient | Specification | Price | MOQ\nVitamin C | USP 99% | USD 5/kg | 25 KG",
        )
        certificate = classify_document(
            "Vitamin-C-COA.pdf",
            ".pdf",
            "Certificate of Analysis - Vitamin C USP 99%\nBatch No: A123\nAssay: 99.4%",
        )
        other = classify_document("brochure.pdf", ".pdf", "Company profile and office address")

        self.assertEqual(catalogue.category, CATALOGUE)
        self.assertEqual(certificate.category, CERTIFICATE)
        self.assertEqual(certificate.material_hint, "Vitamin C USP 99%")
        self.assertEqual(other.category, OTHER)

    def test_document_classifier_treats_product_specification_brochure_page_as_catalogue(self) -> None:
        document = classify_document(
            "sample 3-2.pdf",
            ".pdf",
            "Used For Sports Nutrition\n"
            "Product Name        Specification\n"
            "Beta Alanine        All Grade\n"
            "BCAA Instantized    Vegan; 2:1:1; 4:1:1; 8:1:1\n"
            "Creatine Monohydrate        99%\n"
            "HMB Calcium        98%\n"
            "L-Citrulline Malate        99%\n"
            "Used For Dietary Supplements\n"
            "Product Name        Specification\n"
            "Quercetin        95% HPLC\n"
            "Rutin        NF II Grade\n"
            "Black Ginger Extract        5,7 Dimethoxyflavone\n"
            "Turmeric Extract        Total curcuminoids 5%-95% HPLC\n"
            "OEM Services(Hard Capsules,Tablets & Soft Gels Form)",
        )

        self.assertEqual(document.category, CATALOGUE)

    def test_document_classifier_treats_body_price_update_as_catalogue(self) -> None:
        result = classify_document(
            "email_body.txt",
            ".txt",
            "hi abhishek,\n\nthe price of Zinc Sulfate is updated to $6/kg.\n\nthanks,\nPrince",
        )

        self.assertEqual(result.category, CATALOGUE)

    def test_document_classifier_treats_body_direct_price_as_catalogue(self) -> None:
        result = classify_document(
            "email_body.txt",
            ".txt",
            "Price of Ashwagandha 20% Content is $60/kg with MOQ 20kg",
        )

        self.assertEqual(result.category, CATALOGUE)

    def test_certificate_matching_does_not_attach_to_unrelated_catalogue_rows(self) -> None:
        service = object.__new__(EmailIngestionService)
        vitamin_c = SimpleNamespace(
            ingredient_name="Vitamin C",
            raw_payload={"specification": "USP 99%"},
        )
        citric_acid = SimpleNamespace(
            ingredient_name="Citric Acid",
            raw_payload={"specification": "Food Grade"},
        )
        ref = {
            "name": "Vitamin-C-COA.pdf",
            "type": "COA",
            "material_hint": "Vitamin C USP 99%",
            "match_text": "Certificate of Analysis - Vitamin C USP 99%",
        }

        self.assertTrue(service._certificate_matches_item(ref, vitamin_c))
        self.assertFalse(service._certificate_matches_item(ref, citric_acid))


if __name__ == "__main__":
    unittest.main()
