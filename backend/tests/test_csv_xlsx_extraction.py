import sys
import unittest
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.services.catalog_table_parser import (
    parse_catalog_table_text,
    _split_table_line,
    _header_map,
)
from backend.app.services.email_ingestion import EmailIngestionService
from backend.app.schemas import ExtractedCatalogItem


class TestCsvXlsxExtraction(unittest.TestCase):

    def test_csv_line_splitting_with_quotes_and_commas(self):
        csv_line = '"Amoxicillin 500mg, USP","Purity 99%, USP grade","1,000","25.50"'
        parts = _split_table_line(csv_line)
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "Amoxicillin 500mg, USP")
        self.assertEqual(parts[1], "Purity 99%, USP grade")
        self.assertEqual(parts[2], "1,000")
        self.assertEqual(parts[3], "25.50")

    def test_csv_extraction_pipeline_multiple_rows(self):
        csv_text = """Product Name,Specification,Quantity (KG),Price (USD)
"Amoxicillin 500mg, USP","Purity >= 98%, Mesh 200","1,000","25.50"
"Paracetamol 500mg, BP","BP Grade, White Powder","5,000","4.20"
"Ibuprofen 400mg, IP","Pharma Grade","2,500","18.00"
"Aspirin 100mg, USP","Fine Powder","10,000","3.10"
"Ciprofloxacin 500mg, USP","USP Grade","750","45.00"
"""
        items = parse_catalog_table_text(csv_text)
        self.assertEqual(len(items), 5)

        # Check Row 1
        self.assertEqual(items[0].ingredient_name, "Amoxicillin 500mg, USP")
        self.assertEqual(items[0].available_qty, 1000.0)
        self.assertEqual(items[0].unit, "kg")
        self.assertEqual(items[0].price_per_unit, 25.50)

        # Check Row 4
        self.assertEqual(items[3].ingredient_name, "Aspirin 100mg, USP")
        self.assertEqual(items[3].available_qty, 10000.0)
        self.assertEqual(items[3].unit, "kg")
        self.assertEqual(items[3].price_per_unit, 3.10)

    def test_rm_volume_kg_table_maps_volume_to_quantity_not_price(self):
        table_text = """RM,Volum (KG)
Thiamine (Chemical Substance) Thiamine mononitrate,25.200
Riboflavin (Chemical Substance) Riboflavin,25.20
Biotin (Chemical Substance) Biotin,0.05
"""
        items = parse_catalog_table_text(table_text)

        self.assertEqual(len(items), 3)
        by_name = {item.ingredient_name: item for item in items}
        self.assertEqual(by_name["Biotin (Chemical Substance) Biotin"].available_qty, 0.05)
        self.assertEqual(by_name["Biotin (Chemical Substance) Biotin"].unit, "kg")
        self.assertIsNone(by_name["Biotin (Chemical Substance) Biotin"].price_per_unit)
        self.assertEqual(by_name["Biotin (Chemical Substance) Biotin"].currency, "")
        self.assertIn("original_quantity=0.05 kg", by_name["Biotin (Chemical Substance) Biotin"].notes or "")

    def test_volume_kg_header_typo_is_not_mapped_as_price(self):
        self.assertEqual(_header_map(["RM", "Volume (KG)"]), {"name": 0, "qty": 1})
        self.assertEqual(_header_map(["RM", "Volum (KG)"]), {"name": 0, "qty": 1})

    def test_quantity_header_unit_is_added_to_numeric_only_cells(self):
        csv_text = """Product Name,Specification,Quantity(KG),Price (USD)
"Marigold Extract","Lutein 20%","446.02","11.00"
"Ginger Extract","Powder","399.42","8.50"
"""
        items = parse_catalog_table_text(csv_text)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].available_qty, 446.02)
        self.assertEqual(items[0].unit, "kg")
        self.assertIn("original_quantity=446.02 kg", items[0].notes or "")
        self.assertEqual(items[1].available_qty, 399.42)
        self.assertEqual(items[1].unit, "kg")
        self.assertIn("original_quantity=399.42 kg", items[1].notes or "")

    def test_header_context_is_added_to_price_moq_and_lead_time_cells(self):
        csv_text = """Product Name,Specification,Quantity(KG),Price (CAD),MOQ (KG),Lead Time (Days)
"Marigold Extract","Lutein 20%","446.02","5","25","14"
"""
        items = parse_catalog_table_text(csv_text)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].available_qty, 446.02)
        self.assertEqual(items[0].unit, "kg")
        self.assertEqual(items[0].currency, "CAD")
        self.assertEqual(items[0].price_per_unit, 5.0)
        self.assertEqual(items[0].moq, 25.0)
        self.assertEqual(items[0].lead_time_days, 14)
        self.assertEqual(items[0].lead_time_text, "14 days")
        self.assertIn("original_quantity=446.02 kg", items[0].notes or "")
        self.assertIn("original_price=CAD 5", items[0].notes or "")
        self.assertIn("moq=25 kg", items[0].notes or "")
        self.assertIn("lead_time=14 days", items[0].notes or "")

    def test_quantity_column_variations(self):
        csv_text = """Item Name,Stock Qty,Rate/Unit
Paracetamol,500 kgs,4.50
Ibuprofen,1200 kgs,12.00
"""
        items = parse_catalog_table_text(csv_text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].available_qty, 500.0)
        self.assertEqual(items[0].unit, "kg")
        self.assertEqual(items[1].available_qty, 1200.0)
        self.assertEqual(items[1].unit, "kg")

    def test_description_header_fallback(self):
        csv_text = """Description,Qty,Price
"Cetirizine HCl 10mg",500,8.50
"Loratadine 10mg",1000,14.00
"""
        items = parse_catalog_table_text(csv_text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].ingredient_name, "Cetirizine HCl 10mg")
        self.assertEqual(items[0].available_qty, 500.0)
        self.assertEqual(items[0].price_per_unit, 8.50)

    def test_two_column_csv_table(self):
        csv_text = """Product,Quantity
Aspirin 100mg,5000 kg
Paracetamol 500mg,10000 kg
"""
        items = parse_catalog_table_text(csv_text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].ingredient_name, "Aspirin 100mg")
        self.assertEqual(items[0].available_qty, 5000.0)
        self.assertEqual(items[0].unit, "kg")

    def test_csv_extractor_detects_encoding_delimiter_header_and_preserves_duplicates(self):
        content = (
            "Great River Biosciences Inventory July\n"
            "sales@greatriverbio.com\n"
            "Tel: XXXXXXX\n"
            "\n"
            "Product Name;Stock;Unit;Notes\n"
            "\"Vitamin D3 Powder, 100,000 IU/g\";\"1,000.50\";\"μg\";\"Supplier said \"\"In Stock\"\"\"\n"
            "\"Vitamin Blend\nPremium Grade\";0.25;kg;25%\n"
            "\"Vitamin D3 Powder, 100,000 IU/g\";1000;kg;duplicate offer\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "great-river.csv"
            csv_path.write_bytes(content.encode("utf-16"))

            service = object.__new__(EmailIngestionService)
            text = service._extract_csv_tables_text(csv_path)

        self.assertIn("| Product Name | Stock | Unit | Notes |", text)
        self.assertIn("Vitamin Blend Premium Grade", text)
        self.assertIn('Supplier said "In Stock"', text)

        items = parse_catalog_table_text(text, dedupe=False)
        names = [item.ingredient_name for item in items]
        self.assertEqual(names.count("Vitamin D3 Powder, 100,000 IU/g"), 2)
        self.assertIn("Vitamin Blend Premium Grade", names)
        self.assertEqual(items[0].available_qty, 1000.50)

    def test_csv_extractor_recovers_uneven_rows_and_pipe_delimiter(self):
        content = (
            "Generated date: 2026-08-01\n"
            "Product|Stock|Unit|Price\n"
            "Aspirin 100mg|5000|kg|3.10|extra commercial note\n"
            "Paracetamol 500mg|10000|kg\n"
            "||||\n"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "pipe.csv"
            csv_path.write_text(content, encoding="windows-1252")

            service = object.__new__(EmailIngestionService)
            text = service._extract_csv_tables_text(csv_path)

        self.assertIn("| Product | Stock | Unit | Price |", text)
        items = parse_catalog_table_text(text, dedupe=False)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].ingredient_name, "Aspirin 100mg")
        self.assertEqual(items[1].ingredient_name, "Paracetamol 500mg")
        self.assertIsNone(items[1].price_per_unit)

    def test_xlsx_extraction_detects_horizontal_vertical_and_multi_sheet_tables(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workbook_path = Path(tmp_dir) / "multi-table.xlsx"
            self._write_xlsx_workbook(
                workbook_path,
                {
                    "Inventory": {
                        "A1": "Product",
                        "B1": "Stock",
                        "C1": "Unit",
                        "A2": "Aspirin 100mg",
                        "B2": "5000",
                        "C2": "kg",
                        "E1": "Product",
                        "F1": "Price",
                        "G1": "Unit",
                        "E2": "Paracetamol 500mg",
                        "F2": "4.20",
                        "G2": "kg",
                        "A6": "Product",
                        "B6": "MOQ",
                        "C6": "Lead Time",
                        "A7": "Ibuprofen 400mg",
                        "B7": "25",
                        "C7": "14 days",
                    },
                    "Specials": {
                        "C3": "Product Name",
                        "D3": "Specification",
                        "E3": "FOB($/kg)",
                        "C4": "Vitamin C",
                        "D4": "USP 99%",
                        "E4": "5",
                    },
                },
            )

            service = object.__new__(EmailIngestionService)
            text = service._extract_xlsx_tables_text(workbook_path)

        self.assertEqual(text.count("[XLSX TABLE]"), 4)
        self.assertIn("Sheet: Inventory Table: 1 Start: R1C1", text)
        self.assertIn("Sheet: Inventory Table: 2 Start: R1C5", text)
        self.assertIn("Sheet: Inventory Table: 3 Start: R6C1", text)
        self.assertIn("Sheet: Specials Table: 4 Start: R3C3", text)
        items = parse_catalog_table_text(text, dedupe=False)
        names = [item.ingredient_name for item in items]
        self.assertIn("Aspirin 100mg", names)
        self.assertIn("Paracetamol 500mg", names)
        self.assertIn("Ibuprofen 400mg", names)
        self.assertIn("Vitamin C", names)
        self.assertEqual(len(items), 4)
        by_name = {item.ingredient_name: item for item in items}
        self.assertIn("source_sheet=Inventory", by_name["Aspirin 100mg"].notes or "")
        self.assertIn("source_table=1", by_name["Aspirin 100mg"].notes or "")
        self.assertIn("source_table=2", by_name["Paracetamol 500mg"].notes or "")
        self.assertIn("source_sheet=Specials", by_name["Vitamin C"].notes or "")

    def test_xlsx_extraction_inspects_all_sheets_noise_and_shuffled_columns(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workbook_path = Path(tmp_dir) / "supplier_catalogue.xlsx"
            self._write_xlsx_workbook(
                workbook_path,
                {
                    "Sheet 1": {
                        "A1": "ABC Chemicals Pvt Ltd",
                        "A2": "Updated Price List - July 2026",
                        "A3": "Contact: sales@example.com",
                        "A5": "Product Name",
                        "B5": "Specification",
                        "C5": "Price / Unit",
                        "D5": "MOQ",
                        "E5": "Stock",
                        "A6": "Citric Acid",
                        "B6": "USP Grade",
                        "C6": "USD 2.50/KG",
                        "D6": "100 KG",
                        "E6": "500 KG",
                    },
                    "Sheet 2": {
                        "B3": "MOQ",
                        "C3": "Material",
                        "D3": "Available Qty",
                        "E3": "Rate",
                        "F3": "Grade",
                        "B4": "25 KG",
                        "C4": "Sodium Benzoate",
                        "D4": "1000 KG",
                        "E4": "$3.20/kg",
                        "F4": "Food Grade",
                    },
                    "Sheet 3": {
                        "A1": "Notes: prices subject to confirmation",
                        "A4": "Ingredient",
                        "B4": "Lead Time",
                        "C4": "Price(USD)",
                        "D4": "Quantity(KG)",
                        "A5": "Ascorbic Acid",
                        "B5": "14 days",
                        "C5": "5",
                        "D5": "250",
                    },
                    "Sheet 4": {
                        "A2": "Product",
                        "B2": "Stock",
                        "C2": "Unit",
                        "D2": "MOQ / Packing",
                        "A3": "Magnesium Citrate",
                        "B3": "750",
                        "C3": "kg",
                        "D3": "25 kg drum",
                    },
                    "Sheet 5": {
                        "C6": "Material Name",
                        "D6": "Grade",
                        "E6": "FOB($/kg)",
                        "F6": "Delivery Time",
                        "C7": "Zinc Gluconate",
                        "D7": "USP",
                        "E7": "8.75",
                        "F7": "21 days",
                    },
                },
            )

            service = object.__new__(EmailIngestionService)
            text = service._extract_xlsx_tables_text(workbook_path)

        self.assertEqual(text.count("[XLSX TABLE]"), 5)
        items = parse_catalog_table_text(text, dedupe=False)
        by_name = {item.ingredient_name: item for item in items}
        self.assertEqual(set(by_name), {
            "Citric Acid",
            "Sodium Benzoate",
            "Ascorbic Acid",
            "Magnesium Citrate",
            "Zinc Gluconate",
        })
        self.assertEqual(by_name["Citric Acid"].price_per_unit, 2.5)
        self.assertEqual(by_name["Citric Acid"].available_qty, 500.0)
        self.assertEqual(by_name["Sodium Benzoate"].moq, 25.0)
        self.assertEqual(by_name["Ascorbic Acid"].lead_time_days, 14)
        self.assertEqual(by_name["Magnesium Citrate"].moq, 25.0)
        self.assertEqual(by_name["Zinc Gluconate"].specification, "USP")

    def test_xlsx_extraction_combines_multi_row_headers_without_llm(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            workbook_path = Path(tmp_dir) / "multi-row-header.xlsx"
            self._write_xlsx_workbook(
                workbook_path,
                {
                    "Split Headers": {
                        "A1": "Supplier intro text",
                        "A3": "Product Name",
                        "B3": "Specification",
                        "C2": "Price / Unit",
                        "D2": "Quantity",
                        "E2": "MOQ",
                        "F2": "Lead Time",
                        "C3": "USD/KG",
                        "D3": "KG",
                        "E3": "KG",
                        "F3": "Days",
                        "A4": "3,3'-Diindolylmethane",
                        "B4": "Assay: >=99.0%",
                        "C4": "30",
                        "D4": "120",
                        "E4": "25",
                        "F4": "14",
                    }
                },
            )

            service = object.__new__(EmailIngestionService)
            text = service._extract_xlsx_tables_text(workbook_path)

        self.assertEqual(text.count("[XLSX TABLE]"), 1)
        items = parse_catalog_table_text(text, dedupe=False)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].ingredient_name, "3,3'-Diindolylmethane")
        self.assertEqual(items[0].specification, "Assay: >=99.0%")
        self.assertEqual(items[0].price_per_unit, 30.0)
        self.assertEqual(items[0].currency, "USD")
        self.assertEqual(items[0].available_qty, 120.0)
        self.assertEqual(items[0].moq, 25.0)
        self.assertEqual(items[0].lead_time_days, 14)

    def test_xlsx_extraction_preserves_large_seven_sheet_catalogue(self):
        rows_per_sheet = 500
        sheet_count = 7
        with tempfile.TemporaryDirectory() as tmp_dir:
            workbook_path = Path(tmp_dir) / "large-seven-sheet-catalogue.xlsx"
            sheets: dict[str, dict[str, str]] = {}
            for sheet_index in range(1, sheet_count + 1):
                cells = {
                    "A1": f"Supplier Sheet {sheet_index}",
                    "A3": "Product Name",
                    "B3": "Specification",
                    "C3": "Price(USD)",
                    "D3": "Quantity(KG)",
                    "E3": "MOQ(KG)",
                    "F3": "Lead Time Days",
                }
                excel_row = 4
                for item_index in range(1, rows_per_sheet + 1):
                    if item_index in {125, 250, 375}:
                        excel_row += 3
                    cells[f"A{excel_row}"] = f"Citric Acid Sheet {sheet_index} Item {item_index}"
                    cells[f"B{excel_row}"] = "USP Grade"
                    cells[f"C{excel_row}"] = f"{2 + (item_index / 100):.2f}"
                    cells[f"D{excel_row}"] = str(1000 + item_index)
                    cells[f"E{excel_row}"] = "25"
                    cells[f"F{excel_row}"] = "14"
                    excel_row += 1
                sheets[f"Sheet {sheet_index}"] = cells
            self._write_xlsx_workbook(workbook_path, sheets)

            service = object.__new__(EmailIngestionService)
            text = service._extract_xlsx_tables_text(workbook_path)

        self.assertEqual(text.count("[XLSX TABLE]"), sheet_count)
        items = parse_catalog_table_text(text, dedupe=False)
        self.assertEqual(len(items), rows_per_sheet * sheet_count)
        self.assertEqual(items[0].ingredient_name, "Citric Acid Sheet 1 Item 1")
        self.assertEqual(items[-1].ingredient_name, "Citric Acid Sheet 7 Item 500")
        self.assertEqual(items[-1].available_qty, 1500.0)

    def test_xlsx_extraction_preserves_product_only_inventory_across_ten_sheets(self):
        rows_per_sheet = 600
        sheet_count = 10
        with tempfile.TemporaryDirectory() as tmp_dir:
            workbook_path = Path(tmp_dir) / "product-only-inventory.xlsx"
            sheets: dict[str, dict[str, str]] = {}
            for sheet_index in range(1, sheet_count + 1):
                cells = {
                    "A1": "Total-Ingredients Inventory",
                    "A2": f"Botanical Category {sheet_index}",
                    "A4": "#",
                    "B4": "Product Name",
                }
                excel_row = 5
                for item_index in range(1, rows_per_sheet + 1):
                    if sheet_index == 1 and item_index == 301:
                        cells[f"A{excel_row}"] = "Notes: second inventory region follows"
                        excel_row += 4
                        cells[f"A{excel_row}"] = "#"
                        cells[f"B{excel_row}"] = "Product Name"
                        excel_row += 1
                    cells[f"A{excel_row}"] = str(item_index)
                    cells[f"B{excel_row}"] = f"Arjuna Leaf S{sheet_index} {item_index} Organic"
                    excel_row += 1
                sheets[f"Sheet {sheet_index}"] = cells
            self._write_xlsx_workbook(workbook_path, sheets)

            service = object.__new__(EmailIngestionService)
            text = service._extract_xlsx_tables_text(workbook_path)

        self.assertEqual(text.count("[XLSX TABLE]"), sheet_count + 1)
        items = parse_catalog_table_text(text, dedupe=False)
        self.assertEqual(len(items), rows_per_sheet * sheet_count)
        self.assertEqual(items[0].ingredient_name, "Arjuna Leaf S1 1 Organic")
        self.assertEqual(items[300].ingredient_name, "Arjuna Leaf S1 301 Organic")
        self.assertEqual(items[-1].ingredient_name, "Arjuna Leaf S10 600 Organic")
        self.assertTrue(all(item.specification is None for item in items))

    def test_docx_anydoc_table_keeps_multiclause_specification_in_same_row(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            docx_path = Path(tmp_dir) / "catalogue.docx"
            self._write_docx_table(
                docx_path,
                [
                    ["Jinrui Product Code", "Product Name", "Product Specification Description", "FOB($/kg)"],
                    [
                        "JRG1289-A321",
                        "Zinc Carnosine (Polaprezinc)",
                        "Carnosine content: 76.0 ~ 80.0%, Zinc content: 21.5 ~ 23.0%",
                        "172",
                    ],
                    [
                        "JRG1104-F397",
                        "Zinc Citrate",
                        "Zinc (dry basis): >=31.3%, Complies with GB 1903.49-2020",
                        "5",
                    ],
                ],
            )

            service = object.__new__(EmailIngestionService)
            text = service._extract_docx_text(docx_path)

        self.assertIn("| Zinc Carnosine (Polaprezinc) |", text)
        self.assertIn("Zinc content: 21.5 ~ 23.0%", text)
        items = parse_catalog_table_text(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].ingredient_name, "Zinc Carnosine (Polaprezinc)")
        self.assertIn("Zinc content: 21.5 ~ 23.0%", items[0].specification or "")
        self.assertEqual(items[0].price_per_unit, 172)
        self.assertNotIn("Zinc content: 21.5 ~ 23.0%", [item.ingredient_name for item in items])

    def test_product_code_column_is_skipped_without_dropping_row(self):
        markdown = """| Product code | Product Name | Product Specification Description | FOB($/kg) |
| --- | --- | --- | --- |
| JRG1287-A319 | 3,3'-Diindolylmethane | Assay: >=99.0% | 30 |
| JRG1291-A322 | 5-Amino-1-methylquinolinium Chloride | Purity: >=98.0% | 1477 |
"""
        items = parse_catalog_table_text(markdown)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].ingredient_name, "3,3'-Diindolylmethane")
        self.assertEqual(items[0].supplier_sku, "JRG1287-A319")
        self.assertEqual(items[0].price_per_unit, 30)
        self.assertEqual(items[1].ingredient_name, "5-Amino-1-methylquinolinium Chloride")
        self.assertEqual(items[1].supplier_sku, "JRG1291-A322")

    def test_specification_text_is_not_stored_as_price_when_columns_shift(self):
        markdown = """| Product code | Product Name | Price(USD/kg) |
| --- | --- | --- |
| JRG1287-A319 | 3,3'-Diindolylmethane | Assay: >=99.0% |
| JRG1291-A322 | 5-Amino-1-methylquinolinium Chloride | Purity: >=98.0% |
"""
        items = parse_catalog_table_text(markdown)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].ingredient_name, "3,3'-Diindolylmethane")
        self.assertEqual(items[0].specification, "Assay: >=99.0%")
        self.assertIsNone(items[0].price_per_unit)
        self.assertNotIn("original_price", items[0].notes or "")
        self.assertEqual(items[1].specification, "Purity: >=98.0%")
        self.assertIsNone(items[1].price_per_unit)

    def test_textual_price_values_are_preserved_when_price_column_is_non_numeric(self):
        markdown = """| Product | Specification | Price |
| --- | --- | --- |
| Citric Acid | Food Grade | On request |
| Sodium Citrate | USP | Negotiable |
"""
        items = parse_catalog_table_text(markdown)

        self.assertEqual(len(items), 2)
        self.assertIsNone(items[0].price_per_unit)
        self.assertIn("original_price=On request", items[0].notes or "")
        self.assertIn("original_price=Negotiable", items[1].notes or "")

    def test_structured_markdown_table_does_not_call_llm_fallback(self):
        class FailingLlm:
            def extract_catalog_items(self, *args, **kwargs):
                raise AssertionError("LLM fallback should not run for parsed structured tables")

        markdown = """| Product code | Product Name | Product Specification Description | FOB($/kg) |
| --- | --- | --- | --- |
| JRG1287-A319 | 3,3'-Diindolylmethane | Assay: >=99.0% | 30 |
"""
        service = object.__new__(EmailIngestionService)
        service.llm = FailingLlm()

        items = service._extract_items_from_text(markdown, "sample2.docx")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].ingredient_name, "3,3'-Diindolylmethane")

    def test_parser_rejects_specification_fragments_as_ingredient_names(self):
        markdown = """| Product Name | Product Specification Description | FOB($/kg) |
| --- | --- | --- |
| Zinc content: 21.5 ~ 23.0% | Carnosine content: 76.0 ~ 80.0% | |
| Zinc Glycinate | Content (dry basis): >=98.0%, Complies with GB 1903.2-2015 | 7 |
"""
        items = parse_catalog_table_text(markdown, dedupe=False)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].ingredient_name, "Zinc Glycinate")

    def _write_docx_table(self, path: Path, rows: list[list[str]]) -> None:
        def cell(text: str) -> str:
            return f"<w:tc><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:tc>"

        def row(values: list[str]) -> str:
            return "<w:tr>" + "".join(cell(value) for value in values) + "</w:tr>"

        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:tbl>"
            + "".join(row(values) for values in rows)
            + "</w:tbl></w:body></w:document>"
        )
        content_types = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>"
        )
        with zipfile.ZipFile(path, "w") as docx:
            docx.writestr("[Content_Types].xml", content_types)
            docx.writestr("_rels/.rels", rels)
            docx.writestr("word/document.xml", document)

    def _write_xlsx_workbook(self, path: Path, sheets: dict[str, dict[str, str]]) -> None:
        def xml_escape(value: str) -> str:
            return escape(str(value), {'"': "&quot;"})

        content_types = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for index in range(1, len(sheets) + 1)
            )
            + "</Types>"
        )
        root_rels = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>"
        )
        workbook = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>"
            + "".join(
                f'<sheet name="{xml_escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
                for index, name in enumerate(sheets, start=1)
            )
            + "</sheets></workbook>"
        )
        workbook_rels = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(
                f'<Relationship Id="rId{index}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{index}.xml"/>'
                for index in range(1, len(sheets) + 1)
            )
            + "</Relationships>"
        )

        with zipfile.ZipFile(path, "w") as xlsx:
            xlsx.writestr("[Content_Types].xml", content_types)
            xlsx.writestr("_rels/.rels", root_rels)
            xlsx.writestr("xl/workbook.xml", workbook)
            xlsx.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            for index, cells in enumerate(sheets.values(), start=1):
                rows: dict[int, list[tuple[str, str]]] = {}
                for ref, value in cells.items():
                    if ref == "__merges__":
                        continue
                    row_index = int("".join(char for char in ref if char.isdigit()))
                    rows.setdefault(row_index, []).append((ref, value))
                sheet_data = "".join(
                    f'<row r="{row_index}">'
                    + "".join(
                        f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(value)}</t></is></c>'
                        for ref, value in sorted(row_cells)
                    )
                    + "</row>"
                    for row_index, row_cells in sorted(rows.items())
                )
                merge_refs = cells.get("__merges__", [])
                merge_xml = ""
                if merge_refs:
                    merge_xml = (
                        f'<mergeCells count="{len(merge_refs)}">'
                        + "".join(f'<mergeCell ref="{xml_escape(ref)}"/>' for ref in merge_refs)
                        + "</mergeCells>"
                    )
                worksheet = (
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    f"<sheetData>{sheet_data}</sheetData>"
                    f"{merge_xml}"
                    "</worksheet>"
                )
                xlsx.writestr(f"xl/worksheets/sheet{index}.xml", worksheet)


if __name__ == "__main__":
    unittest.main()
