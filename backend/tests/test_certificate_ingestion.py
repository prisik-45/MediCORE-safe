import sys
import unittest
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.models import CatalogEmail, CatalogItem, Supplier
from backend.app.schemas import ExtractedCatalogItem
from backend.app.services.document_classifier import CATALOGUE, CERTIFICATE, DocumentClassification
from backend.app.services.email_ingestion import EmailIngestionService


class CertificateIngestionTest(unittest.TestCase):
    def test_certificate_attachment_and_body_catalogue_attach_to_same_extracted_row(self) -> None:
        added_items = []
        catalog_emails = []

        class FakeQuery:
            def __init__(self, model):
                self.model = model

            def join(self, *args, **kwargs):
                return self

            def filter(self, *args, **kwargs):
                return self

            def order_by(self, *args, **kwargs):
                return self

            def first(self):
                return None

            def all(self):
                return list(added_items)

        class FakeDB:
            def query(self, model):
                return FakeQuery(model)

            def add(self, item):
                if isinstance(item, CatalogEmail):
                    if item not in catalog_emails:
                        catalog_emails.append(item)
                elif isinstance(item, CatalogItem):
                    if item not in added_items:
                        added_items.append(item)

            def flush(self):
                pass

            def commit(self):
                pass

        service = object.__new__(EmailIngestionService)
        service.db = FakeDB()
        service.settings = SimpleNamespace(supabase_storage_bucket="catalog-pdfs")
        tenant_id = uuid4()
        supplier = Supplier(id=uuid4(), tenant_id=tenant_id, name="Prince", email_domain="prince@example.com", country="Thailand")
        service._upsert_supplier = lambda sender, display_name=None, tenant_id=None: supplier
        service._upload_file = lambda file_path, raw_email_id, mime_type: (
            f"https://example.supabase.co/storage/v1/object/public/catalog-pdfs/{file_path.name}",
            f"{raw_email_id}/{file_path.name}",
        )
        service._extract_text_from_file = lambda file_path, ext: (
            "Certificate of Analysis\nProduct: Ashwagandha\nBatch No: A-1\nAssay: 20%"
            if ext == ".pdf"
            else file_path.read_text(encoding="utf-8", errors="ignore")
        )
        service._classify_document = lambda filename, ext, text, context_text=None: (
            DocumentClassification(CERTIFICATE, 0.95, "Ashwagandha")
            if ext == ".pdf"
            else DocumentClassification(CATALOGUE, 0.9, None)
        )
        service._certificate_matches_item = lambda ref, item: True
        service._delete_uploaded_files = lambda object_paths: None

        message = EmailMessage()
        message["From"] = "Prince Sikotra <prince@example.com>"
        message["Subject"] = "Certificate"
        message["Date"] = datetime(2026, 8, 9, tzinfo=UTC).strftime("%a, %d %b %Y %H:%M:%S %z")
        message.set_content(
            "Price of Ashwagandha 20% Content is $60/kg with MOQ 20kg\n\n"
            "thanks,\nPrince\nThailand"
        )
        message.add_attachment(
            b"%PDF-1.4 certificate bytes",
            maintype="application",
            subtype="pdf",
            filename="Ashwagandha-Certificate.pdf",
        )

        stored_count = service._process_message(message, raw_email_id="email-1", tenant_id=tenant_id)

        self.assertEqual(stored_count, 1)
        self.assertEqual(len(added_items), 1)
        item = added_items[0]
        self.assertEqual(item.ingredient_name, "Ashwagandha")
        self.assertEqual(item.raw_payload.get("specification"), "20% Content")
        self.assertEqual(float(item.price_per_unit), 60.0)
        self.assertEqual(float(item.moq), 20.0)
        certs = item.raw_payload.get("certificate_pdfs", [])
        self.assertEqual(len(certs), 1)
        self.assertEqual(certs[0].get("name"), "Ashwagandha-Certificate.pdf")
        self.assertEqual(certs[0].get("storage_path"), "email-1/Ashwagandha-Certificate.pdf")
        self.assertEqual(catalog_emails[0].processing_status, "completed")

    def test_certificate_reply_with_inline_price_updates_previous_thread_item(self) -> None:
        tenant_id = uuid4()
        supplier_id = uuid4()
        previous_email_id = uuid4()
        previous_item = CatalogItem(
            id=uuid4(),
            tenant_id=tenant_id,
            catalog_email_id=previous_email_id,
            supplier_id=supplier_id,
            ingredient_name="L-Carnitine",
            price_per_unit=25.0,
            currency="USD",
            available_qty=None,
            unit="kg",
            raw_payload={"source": "email_extracted_catalogue"},
        )
        catalog_emails = []

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

            def first(self):
                return None

            def all(self):
                if self.models and self.models[0] is CatalogItem:
                    return [previous_item]
                if self.models and self.models[0] is CatalogEmail:
                    return []
                return [(previous_email_id, "L-Carnitine offer")]

        class FakeDB:
            def query(self, *models):
                return FakeQuery(*models)

            def add(self, item):
                if isinstance(item, CatalogEmail) and item not in catalog_emails:
                    catalog_emails.append(item)

            def flush(self):
                pass

            def commit(self):
                pass

        service = object.__new__(EmailIngestionService)
        service.db = FakeDB()
        service.settings = SimpleNamespace(supabase_storage_bucket="catalog-pdfs")
        supplier = Supplier(id=supplier_id, tenant_id=tenant_id, name="Supplier", email_domain="supplier@example.com", country="Unknown")
        service._upsert_supplier = lambda sender, display_name=None, tenant_id=None: supplier
        service._upload_file = lambda file_path, raw_email_id, mime_type: (
            f"https://example.supabase.co/storage/v1/object/public/catalog-pdfs/{file_path.name}",
            f"{raw_email_id}/{file_path.name}",
        )
        service._extract_text_from_file = lambda file_path, ext: (
            "Certificate of Analysis\nProduct: L-Carnitine\nBatch No: LC-1\nAssay: 99%"
            if ext == ".pdf"
            else file_path.read_text(encoding="utf-8", errors="ignore")
        )
        service._classify_document = lambda filename, ext, text, context_text=None: (
            DocumentClassification(CERTIFICATE, 0.99, "L-Carnitine")
            if ext == ".pdf"
            else DocumentClassification("other", 0.5, None)
        )
        service._certificate_matches_item = lambda ref, item: True
        service._delete_uploaded_files = lambda object_paths: None

        message = EmailMessage()
        message["From"] = "Supplier <supplier@example.com>"
        message["Subject"] = "Re: L-Carnitine offer"
        message["Date"] = datetime(2026, 8, 9, tzinfo=UTC).strftime("%a, %d %b %Y %H:%M:%S %z")
        message.set_content(
            "Dear Mr.Karim,\n\n"
            "Thank you for your interest in our L-Carnitine.\n\n"
            "Please find our offer below:\n\n"
            "Price: USD22.7/kg CIF by sea\n\n"
            "The COA is attached for your reference. Please check the specs and let us know if they meet your requirements.\n\n"
            "Best regards,\n"
        )
        message.add_attachment(
            b"%PDF-1.4 certificate bytes",
            maintype="application",
            subtype="pdf",
            filename="L-Carnitine-COA.pdf",
        )

        stored_count = service._process_message(message, raw_email_id="email-2", tenant_id=tenant_id)

        self.assertEqual(stored_count, 1)
        self.assertEqual(float(previous_item.price_per_unit), 22.7)
        self.assertEqual(previous_item.currency, "USD")
        self.assertEqual(previous_item.catalog_email_id, catalog_emails[0].id)
        self.assertTrue(previous_item.raw_payload.get("conversation_update"))
        certs = previous_item.raw_payload.get("certificate_pdfs", [])
        self.assertEqual(len(certs), 1)
        self.assertEqual(certs[0].get("name"), "L-Carnitine-COA.pdf")
        self.assertEqual(catalog_emails[0].processing_status, "completed")

    def test_unmatched_certificate_creates_new_catalog_item_entry_with_country(self) -> None:
        added_items = []

        class FakeDB:
            def query(self, model):
                return self

            def filter(self, *args, **kwargs):
                return self

            def all(self):
                # No existing supplier items match
                return []

            def add(self, item):
                added_items.append(item)

        service = object.__new__(EmailIngestionService)
        service.db = FakeDB()
        service._dedupe_certificate_refs = lambda refs: refs
        service._certificate_matches_item = lambda ref, item: False

        catalog_email = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
        supplier = SimpleNamespace(id=uuid4(), email_domain="supplier.com", country="Germany")

        cert_refs = [
            {
                "name": "COA_Zinc_Gluconate.pdf",
                "url": "https://example.supabase.co/storage/v1/object/public/catalog-pdfs/COA_Zinc_Gluconate.pdf",
                "storage_path": "certificates/COA_Zinc_Gluconate.pdf",
                "type": "Certificate of Analysis",
                "material_hint": "Zinc Gluconate",
                "match_text": "Certificate of Analysis Zinc Gluconate 99% Pure Country of Origin: Germany",
            }
        ]

        service._attach_certificate_refs(catalog_email, supplier, cert_refs)

        self.assertEqual(len(added_items), 1)
        new_item = added_items[0]
        self.assertEqual(new_item.ingredient_name, "Zinc Gluconate")
        self.assertEqual(new_item.supplier_id, supplier.id)
        self.assertIsNotNone(new_item.raw_payload)
        self.assertEqual(new_item.raw_payload.get("country_of_origin"), "Germany")
        certs = new_item.raw_payload.get("certificate_pdfs", [])
        self.assertEqual(len(certs), 1)
        self.assertEqual(certs[0].get("url"), "https://example.supabase.co/storage/v1/object/public/catalog-pdfs/COA_Zinc_Gluconate.pdf")

    def test_matched_certificate_attaches_to_existing_catalog_item(self) -> None:
        merged_items = []

        existing_item = CatalogItem(
            id=uuid4(),
            tenant_id=uuid4(),
            supplier_id=uuid4(),
            ingredient_name="Ascorbic Acid",
            raw_payload={},
        )

        class FakeDB:
            def query(self, model):
                return self

            def filter(self, *args, **kwargs):
                return self

            def all(self):
                return [existing_item]

            def add(self, item):
                pass

        service = object.__new__(EmailIngestionService)
        service.db = FakeDB()
        service._dedupe_certificate_refs = lambda refs: refs
        service._certificate_matches_item = lambda ref, item: True

        def fake_merge(item, refs):
            merged_items.append((item, refs))
            item.raw_payload = {"certificate_pdfs": refs}

        service._merge_item_certificate_refs = fake_merge

        catalog_email = SimpleNamespace(id=uuid4(), tenant_id=existing_item.tenant_id)
        supplier = SimpleNamespace(id=existing_item.supplier_id, email_domain="supplier.com", country="China")

        cert_refs = [
            {
                "name": "COA_Ascorbic_Acid.pdf",
                "url": "https://example.supabase.co/storage/v1/object/public/catalog-pdfs/COA_Ascorbic_Acid.pdf",
                "type": "Certificate of Analysis",
            }
        ]

        service._attach_certificate_refs(catalog_email, supplier, cert_refs)

        self.assertEqual(len(merged_items), 1)
        self.assertEqual(existing_item.raw_payload.get("certificate_pdfs"), cert_refs)

    def test_document_classifier_detects_various_certificate_filenames_and_contexts(self) -> None:
        from backend.app.services.document_classifier import CERTIFICATE, classify_document

        filenames = [
            "COA.pdf",
            "COA_Zinc_Gluconate.pdf",
            "COA123.pdf",
            "COA-Ascorbic.pdf",
            "Certificate_Analysis.pdf",
            "Cert_2026.png",
            "Specification_Sheet.pdf",
            "TDS_VitaminC.pdf",
            "Halal_Certificate.pdf",
            "Kosher_Cert.pdf",
            "ISO_Certificate.pdf",
            "Lab_Report.pdf",
            "AnalysisReport.pdf",
        ]

        for fname in filenames:
            ext = "." + fname.rsplit(".", 1)[-1]
            doc = classify_document(fname, ext, "Assay: 99.5% Purity Batch No 10293")
            self.assertEqual(doc.category, CERTIFICATE, f"Failed to classify {fname} as CERTIFICATE")

        # Test context from email subject
        doc_email_ctx = classify_document(
            "Scan_001.pdf",
            ".pdf",
            "Assay: 99.0%",
            context_text="Attached COA for Zinc Gluconate",
        )
        self.assertEqual(doc_email_ctx.category, CERTIFICATE)

    def test_document_classifier_detects_scanned_certificate_from_analytical_fields(self) -> None:
        from backend.app.services.document_classifier import CERTIFICATE, classify_document

        # Image/PDF OCR can lose the certificate heading.  The analytical
        # fields still distinguish a COA from a commercial catalogue table.
        document = classify_document(
            "scan_001.pdf",
            ".pdf",
            "Product: Zinc Gluconate\nBatch No: ZG-2026-17\nAssay: 99.4%\n"
            "Appearance: White powder\nLoss on Drying: 0.3%\nConforms",
        )
        self.assertEqual(document.category, CERTIFICATE)

    def test_ingestion_only_treats_pdf_documents_as_certificates(self) -> None:
        service = object.__new__(EmailIngestionService)

        pdf_doc = service._classify_document(
            "COA_Zinc_Gluconate.pdf",
            ".pdf",
            "Certificate of Analysis\nBatch No: ZG-2026-17\nAssay: 99.4%",
        )
        image_doc = service._classify_document(
            "COA_Zinc_Gluconate.png",
            ".png",
            "Certificate of Analysis\nBatch No: ZG-2026-17\nAssay: 99.4%",
        )
        spreadsheet_doc = service._classify_document(
            "Certificate_Analysis.xlsx",
            ".xlsx",
            "Certificate of Analysis\nBatch No: ZG-2026-17\nAssay: 99.4%",
        )

        self.assertEqual(pdf_doc.category, CERTIFICATE)
        self.assertEqual(image_doc.category, CATALOGUE)
        self.assertEqual(spreadsheet_doc.category, CATALOGUE)
        self.assertFalse(service._is_certificate_pdf("COA_Zinc_Gluconate.png", ".png", image_doc.category))

    def test_image_vision_json_bypasses_classifier_parser_and_llm(self) -> None:
        tenant_id = uuid4()
        supplier = Supplier(
            id=uuid4(),
            tenant_id=tenant_id,
            name="Image Supplier",
            email_domain="image@example.com",
            country="Unknown",
        )
        catalog_emails = []
        stored_calls = []

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return None

        class FakeDB:
            def query(self, model):
                return FakeQuery()

            def add(self, item):
                if isinstance(item, CatalogEmail):
                    catalog_emails.append(item)

            def flush(self):
                pass

            def commit(self):
                pass

        service = object.__new__(EmailIngestionService)
        service.db = FakeDB()
        service.settings = SimpleNamespace(supabase_storage_bucket="catalog-pdfs")
        service._existing_email_status = lambda raw_email_id, tenant_id=None: None
        service._upsert_supplier = lambda sender, display_name=None, tenant_id=None: supplier
        service._upload_file = lambda file_path, raw_email_id, mime_type: (
            f"https://example.supabase.co/storage/v1/object/public/catalog-pdfs/{file_path.name}",
            f"{raw_email_id}/{file_path.name}",
        )
        service._delete_uploaded_files = lambda object_paths: None
        service._update_supplier_country = lambda supplier, *texts: None
        service._extract_text_from_file = lambda *args, **kwargs: self.fail("image text fallback should not run")
        service._classify_document = lambda *args, **kwargs: self.fail("non-PDF classifier should not run")
        service._extract_items_from_text = lambda *args, **kwargs: self.fail("parser/LLM fallback should not run")
        service._extract_catalogue_items_from_image = lambda file_path: [
            ExtractedCatalogItem(
                ingredient_name="Vitamin C",
                price_per_unit=5.0,
                currency="USD",
                available_qty=100.0,
                unit="kg",
                notes="source='Vitamin C USD 5/kg Qty 100kg'",
            )
        ]

        def fake_store(catalog_email, supplier, items, text, tenant_id=None, source_name=None):
            stored_calls.append((items, text, source_name))
            return len(items)

        service._store_catalog_items = fake_store

        message = EmailMessage()
        message["From"] = "Image Supplier <image@example.com>"
        message["Subject"] = "Image catalogue"
        message["Date"] = datetime(2026, 8, 9, tzinfo=UTC).strftime("%a, %d %b %Y %H:%M:%S %z")
        message.set_content("Attached catalogue image")

        count = service._process_message(
            message,
            raw_email_id="image-email-1",
            parse_targets=[
                {
                    "name": "catalogue.jpg",
                    "payload": b"image-bytes",
                    "ext": ".jpg",
                    "mime_type": "image/jpeg",
                    "is_body": False,
                }
            ],
            tenant_id=tenant_id,
        )

        self.assertEqual(count, 1)
        self.assertEqual(catalog_emails[0].processing_status, "completed")
        self.assertEqual(stored_calls[0][0][0].ingredient_name, "Vitamin C")
        self.assertEqual(stored_calls[0][2], "catalogue.jpg")

    def test_non_pdf_classifier_is_not_called_when_image_vision_falls_back(self) -> None:
        tenant_id = uuid4()
        supplier = Supplier(
            id=uuid4(),
            tenant_id=tenant_id,
            name="Fallback Supplier",
            email_domain="fallback@example.com",
            country="Unknown",
        )

        class FakeQuery:
            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return None

        class FakeDB:
            def query(self, model):
                return FakeQuery()

            def add(self, item):
                pass

            def flush(self):
                pass

            def commit(self):
                pass

        service = object.__new__(EmailIngestionService)
        service.db = FakeDB()
        service.settings = SimpleNamespace(supabase_storage_bucket="catalog-pdfs")
        service._existing_email_status = lambda raw_email_id, tenant_id=None: None
        service._upsert_supplier = lambda sender, display_name=None, tenant_id=None: supplier
        service._upload_file = lambda file_path, raw_email_id, mime_type: (
            f"https://example.supabase.co/storage/v1/object/public/catalog-pdfs/{file_path.name}",
            f"{raw_email_id}/{file_path.name}",
        )
        service._delete_uploaded_files = lambda object_paths: None
        service._update_supplier_country = lambda supplier, *texts: None
        service._extract_catalogue_items_from_image = lambda file_path: []
        service._extract_text_from_file = lambda file_path, ext: "Vitamin C USD 5/kg source row"
        service._classify_document = lambda *args, **kwargs: self.fail("non-PDF classifier should not run")
        service._extract_items_from_text = lambda text, source_name, reference_date=None: [
            ExtractedCatalogItem(
                ingredient_name="Vitamin C",
                price_per_unit=5.0,
                currency="USD",
                unit="kg",
                notes="source='Vitamin C USD 5/kg source row'",
            )
        ]
        service._store_catalog_items = lambda catalog_email, supplier, items, text, tenant_id=None, source_name=None: len(items)

        message = EmailMessage()
        message["From"] = "Fallback Supplier <fallback@example.com>"
        message["Subject"] = "Fallback image catalogue"
        message["Date"] = datetime(2026, 8, 9, tzinfo=UTC).strftime("%a, %d %b %Y %H:%M:%S %z")
        message.set_content("Attached catalogue image")

        count = service._process_message(
            message,
            raw_email_id="image-email-2",
            parse_targets=[
                {
                    "name": "catalogue.jpg",
                    "payload": b"image-bytes",
                    "ext": ".jpg",
                    "mime_type": "image/jpeg",
                    "is_body": False,
                }
            ],
            tenant_id=tenant_id,
        )

        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
