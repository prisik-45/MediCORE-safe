"""Spreadsheet (.xlsx, .xls, .csv) file loader using openpyxl / xlrd / pandas.

Owned by: pipeline/ingestion/loader_xlsx.py
"""

import csv
import io
from pathlib import Path
import pandas as pd


class ExcelWrapper:
    """Wrapper around spreadsheet data extraction."""

    def __init__(self, sheets_data: dict[str, pd.DataFrame], raw_text: str | None, file_path: Path):
        self.sheets_data = sheets_data
        self.raw_text = raw_text
        self.file_path = file_path


def format_df_to_markdown(df: pd.DataFrame) -> str:
    """Format DataFrame to clean, unpadded Markdown table."""
    headers = [str(c).strip() for c in df.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in df.itertuples(index=False):
        row_cells = [str(cell if pd.notna(cell) else "").strip() for cell in row]
        lines.append("| " + " | ".join(row_cells) + " |")
    return "\n".join(lines)


MAX_SAFE_SHEETS = 10
MAX_SAFE_ROWS_PER_SHEET = 5000
MAX_SAFE_COLS_PER_SHEET = 50


def load_xlsx(file_path: Path) -> ExcelWrapper:
    """Open spreadsheet file (.xlsx, .xls, .csv) and parse into DataFrames per sheet with safety bounds."""
    suffix = file_path.suffix.lower()
    sheets: dict[str, pd.DataFrame] = {}
    raw_text: str | None = None

    if suffix == ".csv":
        raw_bytes = file_path.read_bytes()
        raw_content = None
        for enc in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "windows-1252", "latin1"):
            try:
                raw_content = raw_bytes.decode(enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if raw_content is None:
            raw_content = raw_bytes.decode("utf-8", errors="ignore")

        raw_text = raw_content
        lines = [line.strip() for line in raw_content.splitlines() if line.strip()]

        if lines:
            delims = ["|", ";", "\t", ","]
            best_delim = max(delims, key=lambda d: sum(line.count(d) for line in lines))

            try:
                reader = csv.reader(io.StringIO(raw_content), delimiter=best_delim)
                all_rows = [row for row in reader if any(cell.strip() for cell in row)]
            except Exception:
                all_rows = [line.split(best_delim) for line in lines]

            header_idx = 0
            for i, r in enumerate(all_rows):
                if sum(1 for c in r if c.strip()) >= 2:
                    header_idx = i
                    break

            table_rows = all_rows[header_idx:header_idx + MAX_SAFE_ROWS_PER_SHEET]
            max_cols = min(max((len(r) for r in table_rows), default=1), MAX_SAFE_COLS_PER_SHEET)
            padded_rows = [
                [" ".join(cell.split()) for cell in r[:max_cols]] + [""] * (max_cols - len(r[:max_cols])) for r in table_rows
            ]

            if len(padded_rows) > 1:
                df = pd.DataFrame(padded_rows[1:], columns=padded_rows[0])
            else:
                df = pd.DataFrame(padded_rows)

            sheets["CSV"] = df.fillna("")
    elif suffix == ".xls":
        with pd.ExcelFile(file_path, engine="xlrd") as excel_file:
            for idx, sheet_name in enumerate(excel_file.sheet_names):
                if idx >= MAX_SAFE_SHEETS:
                    break
                df = pd.read_excel(excel_file, sheet_name=sheet_name, nrows=MAX_SAFE_ROWS_PER_SHEET, dtype=str).fillna("")
                if df.shape[1] > MAX_SAFE_COLS_PER_SHEET:
                    df = df.iloc[:, :MAX_SAFE_COLS_PER_SHEET]
                sheets[sheet_name] = df
    else:  # .xlsx, .xlsm, etc.
        from backend.app.pipeline.ingestion.safe_zip import inspect_and_validate_zip
        inspect_and_validate_zip(file_path)
        with pd.ExcelFile(file_path, engine="openpyxl") as excel_file:
            for idx, sheet_name in enumerate(excel_file.sheet_names):
                if idx >= MAX_SAFE_SHEETS:
                    break
                df = pd.read_excel(excel_file, sheet_name=sheet_name, nrows=MAX_SAFE_ROWS_PER_SHEET, dtype=str).fillna("")
                if df.shape[1] > MAX_SAFE_COLS_PER_SHEET:
                    df = df.iloc[:, :MAX_SAFE_COLS_PER_SHEET]
                sheets[sheet_name] = df

    return ExcelWrapper(sheets_data=sheets, raw_text=raw_text, file_path=file_path)
