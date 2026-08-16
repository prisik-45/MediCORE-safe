"""DOCX file loader using Mammoth.

Owned by: pipeline/ingestion/loader_docx.py
"""

from pathlib import Path
from bs4 import BeautifulSoup
import mammoth

from backend.app.pipeline.ingestion.safe_zip import inspect_and_validate_zip


class DocxWrapper:
    """Wrapper around Mammoth docx extraction."""

    def __init__(self, raw_html: str, raw_text: str, file_path: Path):
        self.raw_html = raw_html
        self.raw_text = raw_text
        self.file_path = file_path

    def get_formatted_parts(self) -> list[str]:
        """Extract text and markdown-formatted tables in document flow order."""
        if not self.raw_html:
            return [self.raw_text.strip()] if self.raw_text.strip() else []

        soup = BeautifulSoup(self.raw_html, "html.parser")
        tables = soup.find_all("table")

        if not tables:
            return [self.raw_text.strip()] if self.raw_text.strip() else []

        parts: list[str] = []

        # Extract top-level elements (paragraphs, tables)
        for element in soup.body.children if soup.body else soup.children:
            if element.name == "table":
                rows: list[list[str]] = []
                for tr in element.find_all("tr"):
                    cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["td", "th"])]
                    if any(cells):
                        rows.append(cells)
                if rows:
                    max_cols = max(len(r) for r in rows)
                    header = rows[0] + [""] * (max_cols - len(rows[0]))
                    data_rows = rows[1:] if len(rows) > 1 else []
                    md_lines = [
                        "| " + " | ".join(header) + " |",
                        "| " + " | ".join(["---"] * len(header)) + " |",
                    ]
                    for r in data_rows:
                        padded = r + [""] * (max_cols - len(r))
                        md_lines.append("| " + " | ".join(padded[:max_cols]) + " |")
                    parts.append("\n".join(md_lines))
            elif hasattr(element, "get_text"):
                txt = element.get_text(separator="\n", strip=True)
                if txt:
                    parts.append(txt)

        return parts if parts else ([self.raw_text.strip()] if self.raw_text.strip() else [])


def load_docx(file_path: Path) -> DocxWrapper:
    """Open docx file and extract markdown/html content."""
    inspect_and_validate_zip(file_path)
    with open(file_path, "rb") as docx_file:
        html_result = mammoth.convert_to_html(docx_file)
        docx_file.seek(0)
        text_result = mammoth.extract_raw_text(docx_file)
        return DocxWrapper(
            raw_html=html_result.value or "",
            raw_text=text_result.value or "",
            file_path=file_path,
        )
